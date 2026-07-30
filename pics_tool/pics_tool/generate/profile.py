# Copyright 2025 Espressif Systems (Shanghai) PTE LTD
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
"""The device profile: the small set of user inputs that drive PICS generation.

Loaded from a ``device-profile.(yaml|json)`` file and optionally overridden by
CLI flags. The object is intentionally open/extensible: unknown keys are kept in
``extra`` (with a warning) so new optional facts can be added later without
breaking older profiles.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

VALID_TRANSPORTS = {"wifi_2g", "wifi_5g", "thread", "ethernet"}
VALID_ROLES = {"commissionee", "commissioner", "controller"}
VALID_ONBOARDING = {"qr", "manual_pairing_code", "nfc"}
VALID_POWER = {"mains", "battery"}

# Recognized profile keys (everything else goes to .extra).
_KNOWN_KEYS = {
    "spec_version", "device_type", "transport", "role", "ble_commissioning",
    "onboarding", "node_device_types", "is_icd", "icd_mode", "power_source",
    "im_client",
}


class ProfileError(ValueError):
    """Raised for an invalid or unparseable device profile."""


@dataclass
class DeviceProfile:
    spec_version: str
    device_type: str
    transport: list[str]
    role: str = "commissionee"
    ble_commissioning: bool | None = None  # None -> derived in __post_init__
    onboarding: list[str] = field(default_factory=lambda: ["qr", "manual_pairing_code"])
    # Extra node-level device types the node implements beyond the application
    # device type (e.g. "OTA Requestor", "OTA Provider", "Aggregator"). OTA and
    # bridge node-level PICS are DERIVED from the clusters these pull in, rather
    # than asked as separate flags.
    node_device_types: list[str] = field(default_factory=list)
    # Interaction Model role override: None = derive from the device type's
    # mandatory client clusters; True/False = the user states the device does /
    # does not act as an IM client (initiates reads/writes/invokes to others).
    im_client: bool | None = None
    # Deferred facts (ICD/SIT-LIT depends on the ICD cluster feature; skipped for now).
    is_icd: bool = False
    icd_mode: str | None = None  # "sit" | "lit"
    power_source: str = "mains"
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.spec_version:
            raise ProfileError("spec_version is required")
        if not self.device_type:
            raise ProfileError("device_type is required")
        self.transport = [t.lower() for t in self.transport]
        _require_subset("transport", self.transport, VALID_TRANSPORTS, allow_empty=False)
        _require_member("role", self.role, VALID_ROLES)
        _require_subset("onboarding", self.onboarding, VALID_ONBOARDING)
        _require_member("power_source", self.power_source, VALID_POWER)
        if self.icd_mode is not None:
            _require_member("icd_mode", self.icd_mode, {"sit", "lit"})
        if self.is_icd and self.icd_mode is None:
            self.icd_mode = "sit"  # SIT is the default ICD flavor

        if self.ble_commissioning is None:
            # BLE is used for commissioning unless the device is Ethernet-only.
            self.ble_commissioning = set(self.transport) != {"ethernet"}

    # --- factories -------------------------------------------------------- #

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceProfile":
        known = {k: v for k, v in data.items() if k in _KNOWN_KEYS}
        extra = {k: v for k, v in data.items() if k not in _KNOWN_KEYS}
        if extra:
            logger.warning("unrecognized profile keys kept in 'extra': %s", sorted(extra))
        if "transport" not in known:
            raise ProfileError("transport is required")
        return cls(extra=extra, **known)


def _require_subset(name: str, values: list[str], valid: set[str],
                    allow_empty: bool = True) -> None:
    if not values and not allow_empty:
        raise ProfileError(f"{name} must not be empty")
    invalid = [v for v in values if v not in valid]
    if invalid:
        raise ProfileError(f"invalid {name} value(s) {invalid}; allowed: {sorted(valid)}")


def _require_member(name: str, value: str, valid: set[str]) -> None:
    if value not in valid:
        raise ProfileError(f"invalid {name} {value!r}; allowed: {sorted(valid)}")


def load_profile_data(path: str | Path) -> dict:
    """Read a profile file (``.yaml``/``.yml``/``.json``) into a dict."""
    p = Path(path).expanduser()
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml  # imported lazily; only needed for YAML profiles
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ProfileError(f"profile {p} must contain a mapping at the top level")
    return data


def merge_overrides(data: dict, **overrides) -> dict:
    """Return ``data`` with non-None ``overrides`` applied (CLI wins)."""
    merged = dict(data)
    for key, value in overrides.items():
        if value is not None:
            merged[key] = value
    return merged


def load_profile(path: str | Path | None = None, **overrides) -> DeviceProfile:
    """Load a profile from ``path`` (optional) and apply non-None CLI ``overrides``."""
    data = load_profile_data(path) if path else {}
    data = merge_overrides(data, **overrides)
    return DeviceProfile.from_dict(data)
