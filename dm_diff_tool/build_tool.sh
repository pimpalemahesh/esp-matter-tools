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

# Builds the local data files dm_diff_tool needs to run.
#
# Sparse-clones connectedhomeip (data_model only) into /tmp if MATTER_SDK_PATH
# is not set, then builds the per-version zip archives and data_manifest.json
# that are not committed to the repository. Pass --serve to also start a local static HTTP server so you can
# open the tool in a browser.
#
# Usage:
#   ./build_tool.sh                                    # auto-clones connectedhomeip
#   MATTER_SDK_PATH=/path/to/connectedhomeip ./build_tool.sh
#   ./build_tool.sh --serve                            # build, then serve on :8000
#   ./build_tool.sh --serve --port 9000                # build, then serve on :9000

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHIP_CLONE_DIR="/tmp/connectedhomeip"

# Pin to a specific commit for reproducibility.
# Update this SHA when new data model versions need to be picked up.
CHIP_COMMIT="HEAD"

usage() {
  cat <<'EOF'
Builds the local data files dm_diff_tool needs to run, and optionally serves them.

Usage:
  ./build_tool.sh                                    # auto-clones connectedhomeip, builds zips
  MATTER_SDK_PATH=/path/to/connectedhomeip ./build_tool.sh
  ./build_tool.sh --serve                            # build, then serve on :8000
  ./build_tool.sh --serve --port 9000                # build, then serve on :9000

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

# Track whether this script cloned the repo itself, so cleanup only ever
# removes a clone we created — never a user-supplied MATTER_SDK_PATH.
DID_CLONE=false

cleanup() {
  if [ "$DID_CLONE" = true ] && [ -d "$CHIP_CLONE_DIR" ]; then
    echo "Removing temporary clone at $CHIP_CLONE_DIR ..."
    rm -rf "$CHIP_CLONE_DIR"
    DID_CLONE=false
  fi
}
trap cleanup EXIT

if [ -z "${MATTER_SDK_PATH:-}" ]; then
  echo "MATTER_SDK_PATH not set — sparse-cloning connectedhomeip (data_model only)..."
  rm -rf "$CHIP_CLONE_DIR"
  git clone --depth=1 --filter=blob:none --sparse \
    https://github.com/project-chip/connectedhomeip.git "$CHIP_CLONE_DIR"
  DID_CLONE=true
  cd "$CHIP_CLONE_DIR" && git sparse-checkout set data_model
  if [ "$CHIP_COMMIT" != "HEAD" ]; then
    git fetch --depth=1 origin "$CHIP_COMMIT"
    git checkout "$CHIP_COMMIT"
  fi
  MATTER_SDK_PATH="$CHIP_CLONE_DIR"
fi

cd "$SCRIPT_DIR"

echo "Building dm_diff_tool zips from $MATTER_SDK_PATH/data_model ..."
MATTER_SDK_PATH="$MATTER_SDK_PATH" python3 build_zips.py

echo ""
echo "Build complete. Zips are in dm_diff_tool/data_model/zips/."

# Delete the cloned repository
cleanup

if [ "$SERVE" = true ]; then
  echo "Serving on http://localhost:$PORT — press Ctrl+C to stop."
  exec python3 -m http.server "$PORT"
else
  echo "Serve the tool with: ./build_tool.sh --serve"
fi
