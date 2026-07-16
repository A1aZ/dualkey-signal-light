import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "dualkey_light.py"
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
