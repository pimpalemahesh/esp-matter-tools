#!/usr/bin/env bash

# Copyright 2026 Espressif Systems (Shanghai) PTE LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Builds the local assets the mfg_tool browser UI needs to run (git-ignored),
# and optionally serves the tool locally.
#
#   wheels/      sdist-only deps (PyQRCode, esp-secure-cert-tool) built as wheels
#   test_certs/  bundled test certs copied from ../test_data (single source)
#
# Pass --serve to also start a local static HTTP server so you can open the tool
# in a browser. Keep the wheel versions in sync with VENDORED_WHEELS in app.js.
#
# Usage:
#   ./build_tool.sh                       # build assets
#   ./build_tool.sh --serve               # build, then serve on :8000
#   ./build_tool.sh --serve --port 9000   # build, then serve on :9000

set -euo pipefail

PYQRCODE_VERSION="1.2.1"
ESP_SECURE_CERT_VERSION="2.3.6"

usage() {
  cat <<'EOF'
Builds the mfg_tool browser UI's local assets, and optionally serves them.

Usage:
  ./build_tool.sh                       # build wheels + test certs
  ./build_tool.sh --serve               # build, then serve on :8000
  ./build_tool.sh --serve --port 9000   # build, then serve on :9000

Options:
  --serve        Start a local static HTTP server after building.
  --port PORT    Port for --serve (default: 8000).
  -h, --help     Show this help.
EOF
}

SERVE=false
PORT=8000
while [ $# -gt 0 ]; do
  case "$1" in
    --serve) SERVE=true; shift ;;
    --port) PORT="${2:?--port requires a value}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "error: unknown argument '$1'" >&2; usage >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- 1. vendored wheels ---
rm -f wheels/*.whl
mkdir -p wheels
python3 -m pip wheel --no-deps -w wheels \
    "pyqrcode==${PYQRCODE_VERSION}" \
    "esp-secure-cert-tool==${ESP_SECURE_CERT_VERSION}"

# Normalize wheel filenames to lowercase. Modern pip already does this, but
# older pip keeps the original casing (e.g. PyQRCode-...whl), which would not
# match the lowercase names the page requests.
for w in wheels/*.whl; do
    lower="wheels/$(basename "$w" | tr '[:upper:]' '[:lower:]')"
    [ "$w" != "$lower" ] && mv -f "$w" "$lower"
done

# --- 2. bundled test certificates (from the tool's test fixtures) ---
TD="../test_data"
mkdir -p test_certs
cp "$TD/Chip-Test-PAA-NoVID-Cert.pem"     test_certs/paa_cert.pem
cp "$TD/Chip-Test-PAA-NoVID-Key.pem"      test_certs/paa_key.pem
cp "$TD/Chip-Test-PAI-FFF2-8001-Cert.pem" test_certs/pai_cert.pem
cp "$TD/Chip-Test-PAI-FFF2-8001-Key.pem"  test_certs/pai_key.pem
cp "$TD/Chip-Test-CD-FFF2-8001.der"       test_certs/cd.der

echo ""
echo "Assets ready:"
ls -1 wheels/*.whl
ls -1 test_certs/*

if [ "$SERVE" = true ]; then
  echo ""
  echo "Serving on http://localhost:$PORT — press Ctrl+C to stop."
  exec python3 -m http.server "$PORT"
else
  echo ""
  echo "Serve the tool locally with: ./build_tool.sh --serve"
fi
