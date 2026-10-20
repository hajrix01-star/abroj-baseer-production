#!/usr/bin/env bash
# Fresh-install signing lineage starting at 0.5.3. It cannot update the 0.5.2 certificate.
# Uses an explicitly supplied local key. Never generates or exports a private key.
set -euo pipefail
: "${ANDROID_HOME:?Existing Android SDK is required}"
: "${BWORK_LEGACY_SIGNING_KEY:?Path to the authorized independent preview keystore is required}"
: "${BWORK_LEGACY_SIGNING_PASSWORD_FILE:?Local password-file path is required}"
[[ $# == 2 ]] || { echo 'Usage: sign-preview-apk.sh INPUT.apk OUTPUT.apk' >&2; exit 2; }
[[ -f "$BWORK_LEGACY_SIGNING_KEY" && -f "$BWORK_LEGACY_SIGNING_PASSWORD_FILE" ]] || { echo 'Signing inputs are unavailable.' >&2; exit 1; }
[[ ! -e "$2" ]] || { echo 'Refusing to overwrite an existing signed artifact.' >&2; exit 1; }
BT="${BUILD_TOOLS:-$ANDROID_HOME/build-tools/35.0.0}"
APKSIGNER="$BT/apksigner"
if [[ ! -e "$APKSIGNER" && -e "$BT/apksigner.bat" ]]; then APKSIGNER="$BT/apksigner.bat"; fi
pending="$2.pending.$$"
trap 'rm -f -- "$pending" "$pending.idsig"' EXIT
"$APKSIGNER" sign --ks "$BWORK_LEGACY_SIGNING_KEY" --ks-key-alias bwork-preview --ks-pass "file:$BWORK_LEGACY_SIGNING_PASSWORD_FILE" --out "$pending" "$1"
verification=$("$APKSIGNER" verify --verbose --print-certs "$pending")
verification=${verification//$'\r'/}
expected_cert='f4a5a07e49fdcf9f0e5d5112bbd318636a2bc566329163aec7bcd71b44e3158c'
if [[ $'\n'$verification$'\n' != *$'\nNumber of signers: 1\n'* || $'\n'$verification$'\n' != *$'\n'"Signer #1 certificate SHA-256 digest: $expected_cert"$'\n'* ]]; then
  echo 'Signed APK does not match the authorized fresh-install certificate.' >&2
  exit 1
fi
mv -- "$pending" "$2"
rm -f -- "$pending.idsig"
trap - EXIT
printf '%s\n' "$verification"
