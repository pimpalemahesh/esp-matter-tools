#!/usr/bin/env bash
# Build the UI's git-ignored assets (run by the deploy workflow and locally):
#   wheels/      sdist-only deps (PyQRCode, esp-secure-cert-tool) built as wheels
#   test_certs/  bundled test certs copied from ../test_data (single source)
# Keep wheel versions in sync with VENDORED_WHEELS in app.js.
set -euo pipefail

cd "$(dirname "$0")"

PYQRCODE_VERSION="1.2.1"
ESP_SECURE_CERT_VERSION="2.3.6"

# --- 1. wheels ---
rm -f wheels/*.whl
mkdir -p wheels
python3 -m pip wheel --no-deps -w wheels \
    "pyqrcode==${PYQRCODE_VERSION}" \
    "esp-secure-cert-tool==${ESP_SECURE_CERT_VERSION}"

# Normalize wheel filenames to lowercase.
for w in wheels/*.whl; do
    lower="wheels/$(basename "$w" | tr '[:upper:]' '[:lower:]')"
    [ "$w" != "$lower" ] && mv -f "$w" "$lower"
done

# --- 2. test certificates (from the tool's test fixtures) ---
TD="../test_data"
mkdir -p test_certs
cp "$TD/Chip-Test-PAA-NoVID-Cert.pem"     test_certs/paa_cert.pem
cp "$TD/Chip-Test-PAA-NoVID-Key.pem"      test_certs/paa_key.pem
cp "$TD/Chip-Test-PAI-FFF2-8001-Cert.pem" test_certs/pai_cert.pem
cp "$TD/Chip-Test-PAI-FFF2-8001-Key.pem"  test_certs/pai_key.pem
cp "$TD/Chip-Test-CD-FFF2-8001.der"       test_certs/cd.der

echo
echo "Prepared assets:"
ls -1 wheels/*.whl
ls -1 test_certs/*
