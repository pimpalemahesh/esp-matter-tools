#!/usr/bin/env bash
# Prepare the local-only assets the browser UI needs to be served. These are
# build artifacts (git-ignored), regenerated here so nothing is duplicated in
# the repo.
#
# 1. Vendored wheels (wheels/)
#    esp-matter-mfg-tool and most of its deps are installed in the browser from
#    PyPI by micropip. Two deps — PyQRCode and esp-secure-cert-tool — publish
#    *only* an sdist, which micropip cannot build in the browser. Both are pure
#    Python, so `pip wheel` turns each into a universal py3-none-any wheel that
#    the page installs from wheels/.
#
# 2. Bundled test certificates (test_certs/)
#    Copied from the tool's existing test fixtures in ../test_data so they live
#    in exactly one place in the repo. They power the one-click "bundled test
#    certs" attestation modes. These are Matter *development* credentials.
#
# WHO runs it:
#   The GitHub Pages workflow (.github/workflows/deploy-tools.yml) runs this on
#   every deploy. Run it yourself once before serving the site locally.
#
# Keep the wheel versions in sync with VENDORED_WHEELS in app.js.
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
