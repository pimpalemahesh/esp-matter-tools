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

"""
Matter Data Model Diff Engine
Accepts XML strings, returns JSON-serializable dicts.
"""

import json
from collections import OrderedDict

try:
    # CLI / test context: import from submodules on the filesystem
    from dm_parser import (  # noqa: F401
        _render_choice,
        _render_conformance_single,
        _render_expr,
        _render_value_term,
        get_conformance,
        parse_access,
        parse_cluster_xml_string,
        parse_conformance,
        parse_constraint,
        parse_device_type_xml_string,
        parse_field,
        parse_quality,
    )
    from dm_differ import (  # noqa: F401
        _deep_match,
        _ELEMENT_SECTIONS,
        _element_name_match,
        _filter_changes_focused,
        _filter_full_item_focused,
        _filter_section_diff,
        _NAME_FIELDS,
        _name_matches,
        _normalize,
        compute_diff,
        diff_dicts,
        diff_item,
        diff_list_of_dicts,
        diff_ordered_dict_items,
        diff_simple_dict,
        filter_diff,
        make_serializable,
    )
except ModuleNotFoundError:
    # Pyodide context: dm_parser.py and dm_differ.py were already loaded via
    # runPython, so these names are already in the global __main__ namespace.
    pass


def run_diff(old_xml_map, new_xml_map, name_filter, item_type):
    """Run diff on two maps of {filename: xml_string}.
    item_type: 'clusters' or 'device_types'. Returns a JSON string.
    """
    parse_fn = (
        parse_cluster_xml_string
        if item_type == "clusters"
        else parse_device_type_xml_string
    )

    old_items = OrderedDict()
    for fname in sorted(old_xml_map.keys()):
        parsed = parse_fn(old_xml_map[fname])
        if parsed:
            old_items[fname] = parsed

    new_items = OrderedDict()
    for fname in sorted(new_xml_map.keys()):
        parsed = parse_fn(new_xml_map[fname])
        if parsed:
            new_items[fname] = parsed

    diff = compute_diff(old_items, new_items)

    norm_filter = _normalize(name_filter) if name_filter else ""
    if norm_filter:
        diff = filter_diff(diff, norm_filter)

    return json.dumps(make_serializable(diff))
