#!/usr/bin/env python3

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

"""CLI for the Matter Data Model Diff tool"""

import argparse
import json
import os
import sys
import zipfile
from pathlib import Path

_SECTIONS = [
    ("features", "Features"),
    ("attributes", "Attributes"),
    ("commands", "Commands"),
    ("events", "Events"),
    ("dataTypes", "Data Types"),
    ("clusters", "Clusters"),
    ("conditions", "Conditions"),
    ("conditionRequirements", "Condition Requirements"),
]


def _item_label(item: dict) -> str:
    name = item.get("name", "?")
    iid = item.get("id", "")
    return f"{name} ({iid})" if iid else name


def _rev_info(item: dict) -> tuple[str, str, bool, bool]:
    changes = item.get("changes", {})
    old = item.get("old", {})
    new = item.get("new", {})
    rev_change = changes.get("revision", {})
    if isinstance(rev_change, dict) and "old" in rev_change:
        old_rev, new_rev = rev_change["old"], rev_change["new"]
    else:
        old_rev = old.get("revision", "?")
        new_rev = new.get("revision", "?")
    content_changed = any(k != "revision" for k in changes)
    return old_rev, new_rev, content_changed, old_rev != new_rev


def _strip_internal(obj):
    """Recursively remove keys starting with '_' (internal renderer hints)."""
    if isinstance(obj, dict):
        return {k: _strip_internal(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_internal(i) for i in obj]
    return obj


def _load_xml_map(zip_path: Path, category: str) -> dict:
    prefix = category + "/"
    result = {}
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.startswith(prefix) and name.endswith(".xml"):
                    result[name[len(prefix) :]] = zf.read(name).decode("utf-8")
    except zipfile.BadZipFile:
        sys.exit(f"error: '{zip_path}' is not a valid ZIP file")
    return result


class _Fmt:
    """Terminal color formatter. Emits ANSI escape codes when color is enabled."""

    def __init__(self, color: bool):
        self._color = color

    def _c(self, code: str, text: str) -> str:
        return f"{code}{text}\033[0m" if self._color else text

    def bold(self, t: str) -> str:
        return self._c("\033[1m", t)

    def green(self, t: str) -> str:
        return self._c("\033[32m", t)

    def red(self, t: str) -> str:
        return self._c("\033[31m", t)

    def yellow(self, t: str) -> str:
        return self._c("\033[33m", t)

    def cyan(self, t: str) -> str:
        return self._c("\033[36m", t)

    def dim(self, t: str) -> str:
        return self._c("\033[2m", t)


def _term_section(changes: dict, label: str, fmt: _Fmt, indent: str = "      "):
    added = changes.get("added") or {}
    removed = changes.get("removed") or {}
    modified = changes.get("modified") or {}
    if not (added or removed or modified):
        return
    print(f"{indent}{fmt.bold(label)}:")
    for key, it in added.items() if isinstance(added, dict) else []:
        name = it.get("name", key) if isinstance(it, dict) else key
        conf = it.get("conformance", "") if isinstance(it, dict) else ""
        print(f"{indent}  {fmt.green(f'+ {name}')}" + (f"  [{conf}]" if conf else ""))
    for key, it in removed.items() if isinstance(removed, dict) else []:
        name = it.get("name", key) if isinstance(it, dict) else key
        print(f"{indent}  {fmt.red(f'- {name}')}")
    for key, it in modified.items() if isinstance(modified, dict) else []:
        old_it = it.get("_old", {}) if isinstance(it, dict) else {}
        field_changes = it.get("_changes", {}) if isinstance(it, dict) else {}
        name = old_it.get("name", key) if old_it else key
        parts = [
            f"{f}: {v['old']} → {v['new']}"
            for f, v in field_changes.items()
            if isinstance(v, dict) and "old" in v
        ]
        print(
            f"{indent}  {fmt.yellow(f'~ {name}')}"
            + (f"  ({', '.join(parts)})" if parts else "")
        )


def _term_modified(fname: str, item: dict, fmt: _Fmt):
    name = item.get("name", fname)
    old_rev, new_rev, content_changed, rev_bumped = _rev_info(item)
    warn = (
        f"  {fmt.yellow('[No Revision Update]')}"
        if content_changed and not rev_bumped
        else ""
    )
    print(f"    {fmt.bold(name)}  {fmt.dim(f'rev {old_rev} → {new_rev}')}{warn}")
    for key, label in _SECTIONS:
        section = item.get("changes", {}).get(key)
        if isinstance(section, dict) and any(
            section.get(k) for k in ("added", "removed", "modified")
        ):
            _term_section(section, label, fmt)
    print()


def _term_category(diff: dict, label: str, fmt: _Fmt):
    added = diff.get("added", {})
    removed = diff.get("removed", {})
    modified = diff.get("modified", {})
    unchanged = diff.get("unchanged", [])
    total = len(added) + len(removed) + len(modified) + len(unchanged)

    print(fmt.bold(f"\n{'━' * 60}"))
    print(fmt.bold(f"  {label}") + f"  ({total} total)")
    print(
        f"  {fmt.green(f'added: {len(added)}')}  "
        f"{fmt.red(f'removed: {len(removed)}')}  "
        f"{fmt.yellow(f'modified: {len(modified)}')}  "
        f"unchanged: {len(unchanged)}"
    )

    if added:
        print(f"\n  {fmt.bold('➕ Added')}")
        for _, it in sorted(
            added.items(), key=lambda x: x[1].get("name", x[0]).lower()
        ):
            print(f"    {fmt.green('• ' + _item_label(it))}")
    if removed:
        print(f"\n  {fmt.bold('➖ Removed')}")
        for _, it in sorted(
            removed.items(), key=lambda x: x[1].get("name", x[0]).lower()
        ):
            print(f"    {fmt.red('• ' + _item_label(it))}")
    if modified:
        print(f"\n  {fmt.bold('✏  Modified')}")
        for fname, it in sorted(
            modified.items(), key=lambda x: x[1].get("name", x[0]).lower()
        ):
            _term_modified(fname, it, fmt)


def _diff_item_line(prefix: str, it, key: str) -> str:
    """Format a single added/removed element as a diff line."""
    name = it.get("name", key) if isinstance(it, dict) else key
    iid = it.get("id", "") if isinstance(it, dict) else ""
    conf = it.get("conformance", "") if isinstance(it, dict) else ""
    parts = [name]
    if iid and iid != name:
        parts.append(f"({iid})")
    if conf:
        parts.append(f"[{conf}]")
    return f"{prefix} {' '.join(parts)}"


def _md_modified(fname: str, item: dict) -> list[str]:
    lines = []
    name = item.get("name", fname)
    old_rev, new_rev, content_changed, rev_bumped = _rev_info(item)
    warn = " ⚠️ No Revision Update" if content_changed and not rev_bumped else ""

    lines.append(f"#### {name} — rev {old_rev} → {new_rev}{warn}")
    lines.append("")
    lines.append("```diff")

    has_content = False
    for key, label in _SECTIONS:
        section = item.get("changes", {}).get(key)
        if not isinstance(section, dict):
            continue
        added = section.get("added") or {}
        removed = section.get("removed") or {}
        modified = section.get("modified") or {}
        if not (added or removed or modified):
            continue

        if has_content:
            lines.append("")
        lines.append(f"@@ {label} @@")
        has_content = True

        for k, it in added.items() if isinstance(added, dict) else []:
            lines.append(_diff_item_line("+", it, k))
        for k, it in removed.items() if isinstance(removed, dict) else []:
            lines.append(_diff_item_line("-", it, k))
        for k, it in modified.items() if isinstance(modified, dict) else []:
            old_it = it.get("_old", {}) if isinstance(it, dict) else {}
            field_changes = it.get("_changes", {}) if isinstance(it, dict) else {}
            n = old_it.get("name", k) if old_it else k
            parts = [
                f"{f}: {v['old']} -> {v['new']}"
                for f, v in field_changes.items()
                if isinstance(v, dict) and "old" in v
            ]
            lines.append("  ~ " + n + (f" ({', '.join(parts)})" if parts else ""))

    if not has_content:
        lines.append("  (revision or metadata only)")

    lines.append("```")
    lines.append("")
    return lines


def _md_category(diff: dict, label: str) -> list[str]:
    lines = []
    added = diff.get("added", {})
    removed = diff.get("removed", {})
    modified = diff.get("modified", {})
    unchanged = diff.get("unchanged", [])

    lines.append(f"## {label}")
    lines.append("")
    lines.append(
        f"**➕ Added:** {len(added)} &nbsp; "
        f"**➖ Removed:** {len(removed)} &nbsp; "
        f"**✏️ Modified:** {len(modified)} &nbsp; "
        f"**Unchanged:** {len(unchanged)}"
    )
    lines.append("")

    if added:
        lines.append(f"### ➕ Added ({len(added)})")
        lines.append("")
        lines.append("```diff")
        for _, it in sorted(
            added.items(), key=lambda x: x[1].get("name", x[0]).lower()
        ):
            lines.append(_diff_item_line("+", it, ""))
        lines.append("```")
        lines.append("")

    if removed:
        lines.append(f"### ➖ Removed ({len(removed)})")
        lines.append("")
        lines.append("```diff")
        for _, it in sorted(
            removed.items(), key=lambda x: x[1].get("name", x[0]).lower()
        ):
            lines.append(_diff_item_line("-", it, ""))
        lines.append("```")
        lines.append("")

    if modified:
        lines.append(f"### ✏️ Modified ({len(modified)})")
        lines.append("")
        for fname, it in sorted(
            modified.items(), key=lambda x: x[1].get("name", x[0]).lower()
        ):
            lines.extend(_md_modified(fname, it))

    return lines


def _build_markdown(
    old_label: str, new_label: str, filter_term: str, results: dict
) -> str:
    lines = []
    lines.append(f"# Matter Data Model Diff: {old_label} → {new_label}")
    lines.append("")
    if filter_term:
        lines.append(f"> Filter: `{filter_term}`")
        lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Category | ➕ Added | ➖ Removed | ✏️ Modified | Unchanged |")
    lines.append("|----------|---------|----------|-----------|-----------|")
    label_map = {"clusters": "Clusters", "device_types": "Device Types"}
    for cat, diff in results.items():
        a = len(diff.get("added", {}))
        r = len(diff.get("removed", {}))
        m = len(diff.get("modified", {}))
        u = len(diff.get("unchanged", []))
        lines.append(f"| {label_map.get(cat, cat)} | {a} | {r} | {m} | {u} |")
    lines.append("")

    for cat, diff in results.items():
        lines.extend(_md_category(diff, label_map.get(cat, cat)))

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        prog="dm-diff",
        description="Compare Matter data model versions and show what changed.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("old", help="Old version (e.g. 1.3) or path to zip")
    parser.add_argument("new", help="New version (e.g. 1.4) or path to zip")
    parser.add_argument(
        "--type",
        choices=["clusters", "device_types", "all"],
        default="all",
        metavar="TYPE",
        help="clusters | device_types | all  (default: all)",
    )
    parser.add_argument(
        "--filter", metavar="TERM", default="", help="Filter by name or content"
    )
    parser.add_argument(
        "--output-json",
        metavar="PATH",
        default=None,
        help="Write full diff JSON (default: diff_<old>_<new>.json)",
    )
    parser.add_argument(
        "--output-readme",
        metavar="PATH",
        default=None,
        help="Write Markdown diff report (default: diff_<old>_<new>.md)",
    )
    parser.add_argument(
        "--data-dir",
        metavar="DIR",
        default=None,
        help="Directory containing version zips (default: <script dir>/data_model/zips/)",
    )
    parser.add_argument(
        "--no-color", action="store_true", help="Disable colored terminal output"
    )
    args = parser.parse_args()

    fmt = _Fmt(color=not args.no_color and sys.stdout.isatty() and os.name != "nt")

    script_dir = Path(__file__).resolve().parent
    data_dir = (
        Path(args.data_dir) if args.data_dir else script_dir / "data_model" / "zips"
    )

    def resolve_zip(arg: str) -> Path:
        p = Path(arg)
        if p.suffix == ".zip":
            if not p.exists():
                sys.exit(f"error: '{arg}' does not exist.")
            return p
        zp = data_dir / f"{arg}.zip"
        if not zp.exists():
            sys.exit(
                f"error: version '{arg}' not found — '{zp}' does not exist.\n"
                f"       Run './build_tool.sh' first, or pass a zip file path directly."
            )
        return zp

    old_zip = resolve_zip(args.old)
    new_zip = resolve_zip(args.new)

    sys.path.insert(0, str(script_dir))
    from diff_engine import run_diff  # noqa: PLC0415

    categories = ["clusters", "device_types"] if args.type == "all" else [args.type]
    labels = {"clusters": "Clusters", "device_types": "Device Types"}

    print(
        fmt.bold(
            f"\nMatter Data Model Diff: {fmt.cyan(args.old)} → {fmt.cyan(args.new)}"
        )
    )
    if args.filter:
        print(fmt.dim(f"Filter: {args.filter}"))

    all_results = {}

    for cat in categories:
        old_xml = _load_xml_map(old_zip, cat)
        new_xml = _load_xml_map(new_zip, cat)
        if not old_xml and not new_xml:
            continue
        diff = json.loads(run_diff(old_xml, new_xml, args.filter, cat))
        all_results[cat] = diff

        a = len(diff.get("added", {}))
        r = len(diff.get("removed", {}))
        m = len(diff.get("modified", {}))
        u = len(diff.get("unchanged", []))
        print(
            f"  {fmt.bold(labels[cat])}: "
            f"{fmt.green(f'added {a}')}  "
            f"{fmt.red(f'removed {r}')}  "
            f"{fmt.yellow(f'modified {m}')}  "
            f"unchanged {u}"
        )

    slug = f"{args.old}_{args.new}".replace("/", "-")
    out_dir = Path("out")
    out_dir.mkdir(exist_ok=True)
    json_path = (
        Path(args.output_json) if args.output_json else out_dir / f"diff_{slug}.json"
    )
    readme_path = (
        Path(args.output_readme) if args.output_readme else out_dir / f"diff_{slug}.md"
    )

    out = {
        "old": args.old,
        "new": args.new,
        "filter": args.filter,
        "results": _strip_internal(all_results),
    }
    json_path.write_text(json.dumps(out, indent=2))
    print(f"  JSON   → {fmt.bold(str(json_path))}")

    md = _build_markdown(args.old, args.new, args.filter, all_results)
    readme_path.write_text(md)
    print(f"  README → {fmt.bold(str(readme_path))}")

    print()


if __name__ == "__main__":
    main()
