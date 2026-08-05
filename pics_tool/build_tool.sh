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

# Builds the Pyodide bundle the PICS Generator web app needs, and optionally
# serves it. Unlike dm_diff_tool this needs no connectedhomeip clone -- the data
# model JSON and PICS templates already live in the repo, so the bundle is just
# the two Python packages zipped together.
#
# Usage:
#   ./build_tool.sh                 # build ui/web_bundle/pics_bundle.zip
#   ./build_tool.sh --serve         # build, then serve the ui/ folder on :8000
#   ./build_tool.sh --serve --port 9000

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Builds the Pyodide bundle for the PICS Generator, and optionally serves it.

Usage:
  ./build_tool.sh                 # build ui/web_bundle/pics_bundle.zip
  ./build_tool.sh --serve         # build, then serve the ui/ folder on :8000
  ./build_tool.sh --serve --port 9000

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

cd "$SCRIPT_DIR"

# --- Ensure the per-version datamodel JSONs exist -------------------------------
# They are DERIVED from connectedhomeip's data_model/ and are NOT tracked in git.
# Generate any that are missing from a Matter SDK checkout ($MATTER_SDK_PATH) or a
# shallow clone. Idempotent: does nothing (and needs no checkout) once built.
DM_DIR="esp-matter-datamodel/esp_matter_datamodel/datamodels"
TPL_DIR="pics_tool/templates"
CHIP_CLONE_DIR="/tmp/connectedhomeip-pics"
DID_CLONE=false
cleanup() { [ "$DID_CLONE" = true ] && rm -rf "$CHIP_CLONE_DIR"; }
trap cleanup EXIT

versions=""
for d in "$TPL_DIR"/*/; do [ -d "$d" ] && versions="$versions $(basename "$d")"; done

missing=""
for v in $versions; do
  [ -f "$DM_DIR/datamodel_$v.json" ] || missing="$missing $v"
done

if [ -n "${missing// }" ]; then
  CHIP="${MATTER_SDK_PATH:-$CHIP_CLONE_DIR}"
  if [ ! -d "$CHIP/data_model" ]; then
    if [ -n "${MATTER_SDK_PATH:-}" ]; then
      echo "error: MATTER_SDK_PATH=$MATTER_SDK_PATH has no data_model/ directory" >&2
      exit 1
    fi
    echo "Datamodels missing (${missing# }); cloning connectedhomeip data_model ..."
    git clone --depth 1 --filter=blob:none --sparse \
      https://github.com/project-chip/connectedhomeip "$CHIP_CLONE_DIR"
    git -C "$CHIP_CLONE_DIR" sparse-checkout set data_model
    DID_CLONE=true
  fi
  mkdir -p "$DM_DIR"
  for v in $missing; do
    echo "Building datamodel_$v.json ..."
    PYTHONPATH="esp-matter-datamodel" python3 -m esp_matter_datamodel.cli.main build-model \
      --data-model-dir "$CHIP/data_model" --version "$v" \
      --output "$DM_DIR/datamodel_$v.json"
  done
fi

echo "Building PICS engine bundle..."
python3 build_web.py

echo ""
echo "Build complete. Bundle is in ui/web_bundle/pics_bundle.zip."

if [ "$SERVE" = true ]; then
  exec python3 serve.py "$PORT"
else
  echo "Serve the tool with: ./build_tool.sh --serve"
fi
