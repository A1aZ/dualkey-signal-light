import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "dualkey_light.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("dualkey_light", MODULE_PATH)
dualkey_light = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dualkey_light
assert SPEC.loader is not None
SPEC.loader.exec_module(dualkey_light)


class HookMappingTests(unittest.TestCase):
    def test_codex_working_event(self):
        decision = dualkey_light.choose_hook_action("PreToolUse", {})
        self.assertEqual(decision, dualkey_light.HookDecision("set", "working"))

    def test_permission_is_blocked(self):
        decision = dualkey_light.choose_hook_action("PermissionRequest", {})
        self.assertEqual(decision.state, "blocked")

    def test_structured_failure_overrides_event(self):
        decision = dualkey_light.choose_hook_action(
            "PostToolUse", {"tool": {"exit_status": 2}}
        )
        self.assertEqual(decision.state, "blocked")

    def test_stop_is_control_action(self):
        self.assertEqual(
            dualkey_light.choose_hook_action("Stop", {}).action,
            "turn_end",
        )

    def test_gemini_after_agent_completes_turn(self):
        self.assertEqual(
            dualkey_light.choose_hook_action("AfterAgent", {}).action,
            "turn_end",
        )

    def test_gemini_before_tool_is_working(self):
        self.assertEqual(
            dualkey_light.choose_hook_action("BeforeTool", {}).state,
            "working",
        )


class AggregationTests(unittest.TestCase):
    def test_highest_priority_session_wins(self):
        store = dualkey_light.SessionStore()
        store.apply("a", dualkey_light.HookDecision("set", "working"))
        store.apply("b", dualkey_light.HookDecision("set", "attention"))
        store.apply("c", dualkey_light.HookDecision("set", "blocked"))
        self.assertEqual(store.aggregate(), "blocked")

    def test_stop_clears_work_but_preserves_alert(self):
        store = dualkey_light.SessionStore()
        store.apply("working", dualkey_light.HookDecision("set", "working"))
        store.apply("alert", dualkey_light.HookDecision("set", "blocked"))
        self.assertTrue(store.apply("working", dualkey_light.HookDecision("turn_end")))
        self.assertTrue(store.apply("alert", dualkey_light.HookDecision("turn_end")))
        self.assertNotIn("working", store.sessions)
        self.assertEqual(store.sessions["alert"].state, "blocked")

    def test_session_end_removes_urgent_state(self):
        store = dualkey_light.SessionStore()
        store.apply("a", dualkey_light.HookDecision("set", "blocked"))
        self.assertTrue(store.apply("a", dualkey_light.HookDecision("session_end")))
        self.assertEqual(store.aggregate(), "idle")

    def test_direct_off_clears_sessions(self):
        store = dualkey_light.SessionStore()
        store.apply("a", dualkey_light.HookDecision("set", "working"))
        store.set_direct("off")
        self.assertEqual(store.sessions, {})


class ConcurrentAgentBridgeTests(unittest.IsolatedAsyncioTestCase):
    class FakeWriter:
        def __init__(self):
            self.connected = True
            self.transport_name = "ble"
            self.desired_state = "idle"
            self.last_error = None
            self.device_event_handler = None

        def set_state(self, state):
            self.desired_state = state

    async def test_higher_priority_agent_state_wins(self):
        writer = self.FakeWriter()
        bridge = dualkey_light.Bridge(writer)

        await bridge.handle(
            {"op": "hook", "event": "PreToolUse", "session": "codex:same"}
        )
        await bridge.handle(
            {"op": "hook", "event": "PermissionRequest", "session": "claude:same"}
        )

        self.assertEqual(writer.desired_state, "blocked")
        self.assertEqual(
            bridge.store.snapshot(),
            {"codex:same": "working", "claude:same": "blocked"},
        )

    async def test_completion_never_masks_another_agent_alert(self):
        writer = self.FakeWriter()
        bridge = dualkey_light.Bridge(writer)
        await bridge.handle(
            {"op": "hook", "event": "PermissionRequest", "session": "claude:alert"}
        )
        await bridge.handle(
            {"op": "hook", "event": "PreToolUse", "session": "codex:work"}
        )

        await bridge.handle({"op": "hook", "event": "Stop", "session": "codex:work"})

        self.assertEqual(writer.desired_state, "blocked")
        self.assertEqual(bridge.store.snapshot(), {"claude:alert": "blocked"})

    async def test_completion_never_masks_another_working_session(self):
        writer = self.FakeWriter()
        bridge = dualkey_light.Bridge(writer)
        await bridge.handle(
            {"op": "hook", "event": "UserPromptSubmit", "session": "codex:s1"}
        )
        await bridge.handle(
            {"op": "hook", "event": "UserPromptSubmit", "session": "claude:s2"}
        )
        response = await bridge.handle(
            {"op": "hook", "event": "Stop", "session": "codex:s1"}
        )
        self.assertEqual(response["display"], "working")
        self.assertEqual(writer.desired_state, "working")
        self.assertEqual(bridge.store.snapshot(), {"claude:s2": "working"})

    async def test_physical_clear_resets_all_agents(self):
        writer = self.FakeWriter()
        bridge = dualkey_light.Bridge(writer)
        await bridge.handle(
            {"op": "hook", "event": "PreToolUse", "session": "codex:a"}
        )
        await bridge.handle(
            {"op": "hook", "event": "Notification", "session": "gemini:b"}
        )

        bridge.handle_device_event("EVENT CLEAR")

        self.assertEqual(bridge.store.snapshot(), {})
        self.assertEqual(writer.desired_state, "off")


class HookInstallerTests(unittest.TestCase):
    def test_install_is_additive_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hooks.json"
            path.write_text(
                '{"hooks":{"PreToolUse":[{"hooks":[{"type":"command","command":"existing"}]}]}}',
                encoding="utf-8",
            )
            _, first_added = dualkey_light.install_codex_hooks(path)
            _, second_added = dualkey_light.install_codex_hooks(path)
            data = __import__("json").loads(path.read_text(encoding="utf-8"))

            self.assertEqual(first_added, len(dualkey_light.CODEX_EVENTS))
            self.assertEqual(second_added, 0)
            existing = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
            self.assertEqual(existing, "existing")

    def test_old_managed_entries_are_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".codex" / "hooks.json"
            path.parent.mkdir()
            path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "SessionEnd": [
                                {
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": "python /old/dualkey_light.py hook SessionEnd",
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            dualkey_light.install_codex_hooks(path, command="/opt/dualkey-light hook")
            data = json.loads(path.read_text(encoding="utf-8"))

            self.assertNotIn("SessionEnd", data["hooks"])
            self.assertIn("SessionStart", data["hooks"])
            command = data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
            self.assertEqual(command, "/opt/dualkey-light hook --agent codex")


class MultiAgentIntegrationTests(unittest.TestCase):
    def test_auto_detects_claude_and_gemini_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".claude" / "projects").mkdir(parents=True)
            (home / ".gemini").mkdir()
            (home / ".gemini" / "settings.json").write_text("{}", encoding="utf-8")

            with mock.patch("integrations.shutil.which", return_value=None):
                first = dualkey_light.reconcile_integrations(
                    "auto", home=home, command="/opt/dualkey-light hook"
                )
                second = dualkey_light.reconcile_integrations(
                    "auto", home=home, command="/opt/dualkey-light hook"
                )

            self.assertEqual([item.key for item in first], ["claude", "gemini"])
            self.assertTrue(all(item.changed for item in first))
            self.assertTrue(all(not item.changed for item in second))

            claude = json.loads((home / ".claude" / "settings.json").read_text("utf-8"))
            gemini = json.loads((home / ".gemini" / "settings.json").read_text("utf-8"))
            self.assertIn("PostToolUseFailure", claude["hooks"])
            gemini_handler = gemini["hooks"]["BeforeAgent"][0]["hooks"][0]
            self.assertEqual(gemini_handler["timeout"], 5000)
            self.assertEqual(gemini_handler["name"], "dualkey-signal-light")
            self.assertTrue(gemini_handler["command"].endswith("--agent gemini"))

    def test_uninstall_preserves_unrelated_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".claude" / "settings.json"
            path.parent.mkdir()
            path.write_text(
                json.dumps(
                    {
                        "theme": "dark",
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [
                                        {"type": "command", "command": "existing-policy"},
                                        {"type": "command", "command": "echo dualkey-light"},
                                    ],
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            dualkey_light.reconcile_integrations(
                "claude", home=home, command="/opt/dualkey-light hook", install=True
            )
            result = dualkey_light.reconcile_integrations(
                "claude", home=home, command="/opt/dualkey-light hook", install=False
            )[0]
            data = json.loads(path.read_text("utf-8"))

            self.assertTrue(result.changed)
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(
                [
                    handler["command"]
                    for handler in data["hooks"]["PreToolUse"][0]["hooks"]
                ],
                ["existing-policy", "echo dualkey-light"],
            )

    def test_existing_settings_receive_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".codex" / "hooks.json"
            path.parent.mkdir()
            path.write_text('{"custom":true}', encoding="utf-8")
            result = dualkey_light.reconcile_integrations(
                "codex", home=home, command="/opt/dualkey-light hook"
            )[0]
            self.assertIsNotNone(result.backup)
            self.assertTrue(result.backup.exists())

    def test_utf8_bom_settings_are_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / ".codex" / "hooks.json"
            path.parent.mkdir()
            path.write_bytes(b"\xef\xbb\xbf{\"custom\":true}")
            result = dualkey_light.reconcile_integrations(
                "codex", home=home, command="/opt/dualkey-light hook"
            )[0]
            self.assertTrue(result.changed)
            self.assertTrue(json.loads(path.read_text("utf-8"))["custom"])

    def test_unknown_agent_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unknown agent"):
                dualkey_light.reconcile_integrations(
                    "unknown", home=Path(directory), command="dualkey-light hook"
                )


class PlatformMessageTests(unittest.TestCase):
    def test_macos_bluetooth_permission_message_is_actionable(self):
        class BleakBluetoothNotAvailableError(Exception):
            pass

        message = dualkey_light.describe_ble_error(
            BleakBluetoothNotAvailableError("Bluetooth authorization denied"),
            platform="darwin",
        )
        self.assertIn("Privacy & Security > Bluetooth", message)

    def test_other_platform_preserves_ble_error(self):
        self.assertEqual(
            dualkey_light.describe_ble_error(RuntimeError("radio off"), platform="win32"),
            "radio off",
        )


if __name__ == "__main__":
    unittest.main()
