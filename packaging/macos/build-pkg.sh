#!/bin/sh

set -eu

if [ "$#" -ne 3 ]; then
  echo "usage: build-pkg.sh <macos-app-bundle> <output.pkg> <version>" >&2
  exit 2
fi

app_bundle="$1"
output="$2"
version="$3"
script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
work_dir="$(mktemp -d)"
root="$work_dir/root"
component="$work_dir/dualkey-signal-light-component.pkg"

cleanup() {
  rm -rf "$work_dir"
}
trap cleanup EXIT INT TERM

if [ ! -x "$app_bundle/Contents/MacOS/dualkey-light" ]; then
  echo "missing app executable: $app_bundle/Contents/MacOS/dualkey-light" >&2
  exit 2
fi

mkdir -p \
  "$root/Applications" \
  "$root/usr/local/bin" \
  "$root/Library/LaunchAgents" \
  "$(dirname -- "$output")"

/usr/bin/ditto "$app_bundle" "$root/Applications/DualKey Signal Light.app"
ln -s "/Applications/DualKey Signal Light.app/Contents/MacOS/dualkey-light" \
  "$root/usr/local/bin/dualkey-light"
install -m 0644 \
  "$script_dir/io.github.a1az.dualkey-signal-light.plist" \
  "$root/Library/LaunchAgents/io.github.a1az.dualkey-signal-light.plist"

chmod 0755 "$script_dir/scripts/preinstall" "$script_dir/scripts/postinstall"

/usr/bin/pkgbuild \
  --root "$root" \
  --scripts "$script_dir/scripts" \
  --identifier io.github.a1az.dualkey-signal-light \
  --version "$version" \
  --install-location / \
  "$component"

if [ -n "${MACOS_INSTALLER_IDENTITY:-}" ]; then
  /usr/bin/productbuild --sign "$MACOS_INSTALLER_IDENTITY" --package "$component" "$output"
else
  /usr/bin/productbuild --package "$component" "$output"
fi
