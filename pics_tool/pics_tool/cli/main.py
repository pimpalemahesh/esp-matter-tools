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
"""``esp-matter-pics`` CLI: generate PICS / esp-matter code from a selection."""

from __future__ import annotations

import logging

import click
from esp_matter_datamodel import loader

from .. import service
from ..generate.profile import load_profile
from ..generate.selection import Selection, load_selection


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
def main(verbose: bool) -> None:
    """Offline Matter PICS generator."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


def _selection_options(f):
    """Shared input options for both commands: a selection doc, a profile, or flags."""
    opts = [
        click.option(
            "--selection",
            "selection_path",
            type=click.Path(exists=True),
            help="Path to a canonical selection.(yaml|json) -- multi-endpoint + claims.",
        ),
        click.option(
            "--profile",
            "profile_path",
            type=click.Path(exists=True),
            help="Path to a device-profile.(yaml|json).",
        ),
        click.option(
            "--spec-version", help="Override profile spec_version (e.g. 1.6)."
        ),
        click.option("--device-type", help="Override profile device_type (name)."),
        click.option(
            "--transport",
            multiple=True,
            help="Override transport (repeatable): wifi_2g/wifi_5g/thread/ethernet.",
        ),
        click.option(
            "--role", help="Override role: commissionee/commissioner/controller."
        ),
        click.option(
            "--wifi-paf",
            "wifi_paf",
            is_flag=True,
            default=None,
            help="Device supports commissioning discovery over Wi-Fi PAF.",
        ),
        click.option(
            "--vendor-ota",
            "vendor_specific_ota",
            is_flag=True,
            default=None,
            help="Device supports a vendor-specific OTA mechanism.",
        ),
        click.option(
            "--model",
            "model_path",
            type=click.Path(exists=True),
            help="Data-model JSON to use instead of the packaged one for the version.",
        ),
    ]
    for opt in reversed(opts):
        f = opt(f)
    return f


def _resolve_selection(
    selection_path,
    profile_path,
    spec_version,
    device_type,
    transport,
    role,
    wifi_paf,
    vendor_specific_ota,
    model_path,
):
    """A Selection + its DataModel from either a selection doc, a profile, or flags."""
    if selection_path:
        selection = load_selection(selection_path)
    else:
        profile = load_profile(
            profile_path,
            spec_version=spec_version,
            device_type=device_type,
            transport=list(transport) or None,
            role=role,
            wifi_paf=wifi_paf,
            vendor_specific_ota=vendor_specific_ota,
        )
        selection = Selection.from_profile(profile)
    model = (
        loader.load(model_path)
        if model_path
        else loader.load_version(selection.profile.spec_version)
    )
    return selection, model


def _generate_pics(selection: Selection, model, output: str):
    """Run the engines for a selection and write per-endpoint PICS XML."""
    return service.pics_for_selection(selection, model, output)


def _echo_selection(selection: Selection) -> None:
    p = selection.profile
    click.echo(
        f"Spec        : {p.spec_version}   transport={', '.join(p.transport)}   role={p.role}"
    )
    for epid, ep in enumerate(selection.endpoints, start=1):
        line = f"  endpoint{epid}: {' + '.join(ep.device_types)}"
        if ep.claims:
            line += f"   claims: {', '.join(ep.claims)}"
        click.echo(line)
    if selection.mcore_claims:
        click.echo(f"  mcore claims: {', '.join(selection.mcore_claims)}")


def _echo_snippet(result) -> None:
    """Print the data-model construction code to paste into app_main.cpp."""
    click.echo("// paste into app_main() (esp_matter namespaces in scope)")
    click.echo(result.snippet.rstrip("\n"))


@main.command("gen-pics")
@_selection_options
@click.option(
    "-o", "--output", default="pics_out", show_default=True, help="Output directory."
)
def gen_pics(
    selection_path,
    profile_path,
    spec_version,
    device_type,
    transport,
    role,
    wifi_paf,
    vendor_specific_ota,
    model_path,
    output,
):
    """Generate per-endpoint PICS XML for a selection / device profile."""
    selection, model = _resolve_selection(
        selection_path,
        profile_path,
        spec_version,
        device_type,
        transport,
        role,
        wifi_paf,
        vendor_specific_ota,
        model_path,
    )

    summary = _generate_pics(selection, model, output)

    _echo_selection(selection)
    click.echo(
        f"Wrote {len(summary.files)} files ({summary.supported} supported items) to {output}/"
    )
    if summary.pixits:
        click.echo(
            f"Note: {summary.pixits} PIXIT values need manual entry -- see PIXIT_CHECKLIST.md"
        )


@main.command("gen-scaffold")
@_selection_options
@click.option(
    "-o",
    "--output",
    default=None,
    help="Optional: also write the snippet to <dir>/app_data_model.cpp.",
)
@click.option(
    "--pics-output",
    default="pics_out",
    show_default=True,
    help="Directory for the intermediate PICS XML.",
)
@click.option(
    "--esp-matter-path",
    "esp_matter_path",
    type=click.Path(exists=True),
    default=None,
    help="Path to a local esp_matter component/SDK: generate exact code "
    "against THAT component (any version) instead of the bundled one.",
)
def gen_scaffold(
    selection_path,
    profile_path,
    spec_version,
    device_type,
    transport,
    role,
    wifi_paf,
    vendor_specific_ota,
    model_path,
    output,
    pics_output,
    esp_matter_path,
):
    """Generate the esp-matter data-model construction code from a selection.

    Prints the ``node::create`` / ``endpoint::<device_type>::create`` block to
    paste into app_main.cpp -- the construction the user would otherwise
    hand-write. One run, inputs given once.

    By default it uses the esp_matter signatures bundled with the tool for the
    spec version (exact where available, else ``/* ... */`` placeholders). Pass
    ``--esp-matter-path`` to generate exact code against a local component.
    """
    selection, model = _resolve_selection(
        selection_path,
        profile_path,
        spec_version,
        device_type,
        transport,
        role,
        wifi_paf,
        vendor_specific_ota,
        model_path,
    )

    knowledge = None
    if esp_matter_path:
        from ..generate.codegen.targets.esp_matter.knowledge import from_component

        knowledge = from_component(esp_matter_path, selection.profile.spec_version)

    _generate_pics(selection, model, pics_output)
    result = service.scaffold_for_selection(
        selection, model, output, knowledge=knowledge
    )

    _echo_snippet(result)
    click.echo(f"\n// esp_matter signatures: {result.knowledge_source}")
    if result.unresolved:
        click.echo(
            f"// {len(result.unresolved)} element(s) had no matching esp_matter API "
            f"and are left as comments in the code above -- add them manually."
        )
    if result.file:
        click.echo(f"// also written to: {result.file}")


@main.command("refresh-esp-matter-knowledge")
@click.option(
    "--version",
    "pics_version",
    required=True,
    help="PICS spec version to refresh, e.g. 1.5.1.",
)
@click.option(
    "--component",
    "component_dir",
    type=click.Path(exists=True),
    default=None,
    help="Local esp_matter component/SDK checkout to parse.",
)
@click.option(
    "--download",
    is_flag=True,
    help="Download the mapped released component from the ESP registry.",
)
def refresh_esp_matter_knowledge(pics_version, component_dir, download):
    """(Maintainer) Regenerate the committed caps_<version>.json for a version.

    Parses a released esp_matter component's data_model headers into the bundled
    signature index. Provide --component <dir> or --download.
    """
    from ..generate.codegen.targets.esp_matter import refresh as _refresh

    out, count = _refresh.refresh(
        pics_version, component_dir=component_dir, download=download
    )
    compver = _refresh.component_version_for(pics_version)
    click.echo(f"Wrote {out} ({count} symbols) from esp_matter component {compver}.")


if __name__ == "__main__":
    main()
