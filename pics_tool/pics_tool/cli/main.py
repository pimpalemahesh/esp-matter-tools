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
"""``esp-matter-pics`` CLI: generate PICS from a device profile."""

from __future__ import annotations

import logging

import click
from esp_matter_datamodel import loader

from ..generate.cluster_engine import all_enabled_cluster_ids, generate_cluster_pics
from ..generate.mcore_engine import compute_mcore_pics
from ..generate.profile import load_profile
from ..generate.writer import write_pics


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def main(verbose: bool) -> None:
    """Offline Matter PICS generator."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@main.command("gen-pics")
@click.option("--profile", "profile_path", type=click.Path(exists=True),
              help="Path to a device-profile.(yaml|json).")
@click.option("--spec-version", help="Override profile spec_version (e.g. 1.6).")
@click.option("--device-type", help="Override profile device_type (name).")
@click.option("--transport", multiple=True,
              help="Override transport (repeatable): wifi_2g/wifi_5g/thread/ethernet.")
@click.option("--role", help="Override role: commissionee/commissioner/controller.")
@click.option("--node-device-type", "node_device_types", multiple=True,
              help="Extra node-level device type (repeatable), e.g. 'OTA Requestor', 'Aggregator'.")
@click.option("--model", "model_path", type=click.Path(exists=True),
              help="Data-model JSON to use instead of the packaged one for the version.")
@click.option("-o", "--output", default="pics_out", show_default=True,
              help="Output directory.")
def gen_pics(profile_path, spec_version, device_type, transport, role,
             node_device_types, model_path, output):
    """Generate per-endpoint PICS XML for a device profile."""
    profile = load_profile(
        profile_path,
        spec_version=spec_version,
        device_type=device_type,
        transport=list(transport) or None,
        role=role,
        node_device_types=list(node_device_types) or None,
    )

    model = loader.load(model_path) if model_path else loader.load_version(profile.spec_version)

    cluster_endpoints = generate_cluster_pics(model, profile)
    cluster_ids = all_enabled_cluster_ids(cluster_endpoints)
    mcore = compute_mcore_pics(profile, profile.spec_version, cluster_ids)

    endpoints_enabled = {ep.endpoint: set(ep.pics) for ep in cluster_endpoints}
    endpoints_enabled.setdefault(0, set()).update(mcore)  # MCORE lives on endpoint 0

    summary = write_pics(profile.spec_version, endpoints_enabled, output)

    click.echo(f"Device type : {profile.device_type}  (spec {profile.spec_version})")
    click.echo(f"Transport   : {', '.join(profile.transport)}  role={profile.role}")
    for ep in sorted(endpoints_enabled):
        click.echo(f"  endpoint{ep}: {len(endpoints_enabled[ep])} PICS codes enabled")
    click.echo(f"Wrote {len(summary.files)} files ({summary.supported} supported items) to {output}/")


if __name__ == "__main__":
    main()
