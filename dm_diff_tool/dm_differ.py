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

"""Diff computation and filtering for Matter Data Model items"""

from collections import OrderedDict


def diff_dicts(old, new):
    old_keys = set(old.keys())
    new_keys = set(new.keys())
    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    common = sorted(old_keys & new_keys)
    return added, removed, common


def diff_simple_dict(old, new):
    changes = []
    all_keys = sorted(set(list(old.keys()) + list(new.keys())))
    for k in all_keys:
        ov = old.get(k, "")
        nv = new.get(k, "")
        if ov != nv:
            changes.append({"field": k, "old": ov, "new": nv})
    return changes


def diff_list_of_dicts(old_list, new_list, id_field="name"):
    old_map = OrderedDict()
    for item in old_list:
        old_map[item.get(id_field, "")] = item
    new_map = OrderedDict()
    for item in new_list:
        new_map[item.get(id_field, "")] = item
    added, removed, common = diff_dicts(old_map, new_map)

    result = {"added": [], "removed": [], "modified": []}
    for k in added:
        result["added"].append(new_map[k])
    for k in removed:
        result["removed"].append(old_map[k])
    for k in common:
        changes = diff_simple_dict(old_map[k], new_map[k])
        if changes:
            result["modified"].append({"key": k, "changes": changes})
    return result


def diff_ordered_dict_items(old_dict, new_dict):
    added, removed, common = diff_dicts(old_dict, new_dict)
    result = {
        "added": OrderedDict(),
        "removed": OrderedDict(),
        "modified": OrderedDict(),
    }
    for k in added:
        result["added"][k] = new_dict[k]
    for k in removed:
        result["removed"][k] = old_dict[k]
    for k in common:
        ov, nv = old_dict[k], new_dict[k]
        if ov == nv:
            continue
        if isinstance(ov, dict) and isinstance(nv, dict):
            item_changes = diff_item(ov, nv)
            if item_changes:
                result["modified"][k] = {
                    "_changes": item_changes,
                    "_old": ov,
                    "_new": nv,
                }
        else:
            result["modified"][k] = {"old": ov, "new": nv}
    return result


def diff_item(old, new):
    if old == new:
        return None
    changes = OrderedDict()
    all_keys = list(OrderedDict.fromkeys(list(old.keys()) + list(new.keys())))
    for k in all_keys:
        ov = old.get(k)
        nv = new.get(k)
        if ov == nv:
            continue
        if isinstance(ov, OrderedDict) and isinstance(nv, OrderedDict):
            sub = diff_ordered_dict_items(ov, nv)
            if sub["added"] or sub["removed"] or sub["modified"]:
                changes[k] = sub
        elif isinstance(ov, list) and isinstance(nv, list):
            sample = ov[0] if ov else (nv[0] if nv else None)
            if sample and isinstance(sample, dict):
                id_key = (
                    "name"
                    if "name" in sample
                    else ("id" if "id" in sample else "value")
                )
                sub = diff_list_of_dicts(ov, nv, id_field=id_key)
                if sub["added"] or sub["removed"] or sub["modified"]:
                    changes[k] = sub
            else:
                changes[k] = {"old": ov, "new": nv}
        elif isinstance(ov, dict) and isinstance(nv, dict):
            sub = diff_simple_dict(ov, nv)
            if sub:
                changes[k] = sub
        else:
            changes[k] = {"old": ov, "new": nv}
    return changes if changes else None


def compute_diff(old_items, new_items):
    """Compute diff between two dicts of parsed items (clusters or device types)."""
    added, removed, common = diff_dicts(old_items, new_items)

    result = {
        "added": {k: new_items[k] for k in added},
        "removed": {k: old_items[k] for k in removed},
        "modified": OrderedDict(),
        "unchanged": [],
    }
    for k in common:
        changes = diff_item(old_items[k], new_items[k])
        if changes:
            result["modified"][k] = {
                "name": new_items[k]["name"],
                "old": old_items[k],
                "new": new_items[k],
                "changes": changes,
            }
        else:
            result["unchanged"].append(k)
    return result


def _normalize(s):
    return s.lower().replace(" ", "").replace("-", "").replace("_", "")


def _deep_match(obj, term):
    """Recursive substring match across all string values. Used for focused search."""
    if isinstance(obj, str):
        return term in _normalize(obj)
    if isinstance(obj, dict):
        return any(_deep_match(v, term) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_deep_match(v, term) for v in obj)
    return False


_ELEMENT_SECTIONS = (
    "features",
    "attributes",
    "commands",
    "events",
    "dataTypes",
    "clusters",
    "conditions",
    "conditionRequirements",
)

# Fields that contain human-readable descriptions — excluded from broad search
# to avoid false positives like "identifying" matching "identify".
_NAME_FIELDS = ("name", "code")


def _element_name_match(obj, term):
    """Match only against element names (not summaries/descriptions).
    Used for the broad fallback to avoid false positives from prose text.
    """
    if isinstance(obj, str):
        return _normalize(obj) == term
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _NAME_FIELDS:
                if isinstance(v, str) and term in _normalize(v):
                    return True
            elif isinstance(v, (dict, list, tuple, OrderedDict)):
                if _element_name_match(v, term):
                    return True
        return False
    if isinstance(obj, (list, tuple)):
        return any(_element_name_match(v, term) for v in obj)
    return False


def _filter_section_diff(section_diff, term):
    result = {}
    for bucket in ("added", "removed"):
        items = section_diff.get(bucket, {})
        if isinstance(items, dict):
            matching = {
                k: v
                for k, v in items.items()
                if term in _normalize(k) or _deep_match(v, term)
            }
            if matching:
                result[bucket] = matching
        elif isinstance(items, list):
            matching = [v for v in items if _deep_match(v, term)]
            if matching:
                result[bucket] = matching
    modified = section_diff.get("modified", {})
    if isinstance(modified, dict):
        matching = {
            k: v
            for k, v in modified.items()
            if term in _normalize(k) or _deep_match(v, term)
        }
        if matching:
            result["modified"] = matching
    elif isinstance(modified, list):
        matching = [v for v in modified if _deep_match(v, term)]
        if matching:
            result["modified"] = matching
    has = any(result.get(b) for b in ("added", "removed", "modified"))
    return result if has else None


def _filter_changes_focused(changes, term):
    filtered = {}
    for section in _ELEMENT_SECTIONS:
        section_data = changes.get(section)
        if not section_data:
            continue
        if isinstance(section_data, dict) and any(
            k in section_data for k in ("added", "removed", "modified")
        ):
            fs = _filter_section_diff(section_data, term)
            if fs:
                filtered[section] = fs
        elif _deep_match(section_data, term):
            filtered[section] = section_data
    return filtered or None


def _filter_full_item_focused(item, term):
    matching_sections = {}
    for section in _ELEMENT_SECTIONS:
        data = item.get(section)
        if not data or not isinstance(data, dict):
            continue
        matching = OrderedDict()
        for k, v in data.items():
            if term in _normalize(k) or _deep_match(v, term):
                matching[k] = v
        if matching:
            matching_sections[section] = matching
    if not matching_sections:
        return None
    result = {}
    for k in ("id", "name", "revision", "classification", "revisions"):
        if k in item:
            result[k] = item[k]
    result.update(matching_sections)
    return result


def _name_matches(term, filename, item):
    return term in _normalize(filename) or term in _normalize(item.get("name", ""))


def filter_diff(diff, term):
    result = {
        "added": {},
        "removed": {},
        "modified": OrderedDict(),
        "unchanged": [],
        "_focused": False,
    }
    has_name_match = False
    has_element_match = False

    for k, v in diff["added"].items():
        if _name_matches(term, k, v):
            result["added"][k] = v
            has_name_match = True

    for k, v in diff["removed"].items():
        if _name_matches(term, k, v):
            result["removed"][k] = v
            has_name_match = True

    for k, v in diff["modified"].items():
        if _name_matches(term, k, v) or _name_matches(term, k, v.get("new", {})):
            result["modified"][k] = v
            has_name_match = True

    for k in diff["unchanged"]:
        if term in _normalize(k):
            result["unchanged"].append(k)

    for k, v in diff["modified"].items():
        if k in result["modified"]:
            continue
        fc = _filter_changes_focused(v.get("changes", {}), term)
        if fc:
            result["modified"][k] = {
                "name": v.get("name", ""),
                "old": v.get("old", {}),
                "new": v.get("new", {}),
                "changes": fc,
            }
            has_element_match = True

    for k, v in diff["added"].items():
        if k in result["added"]:
            continue
        fi = _filter_full_item_focused(v, term)
        if fi:
            result["added"][k] = fi
            has_element_match = True

    for k, v in diff["removed"].items():
        if k in result["removed"]:
            continue
        fi = _filter_full_item_focused(v, term)
        if fi:
            result["removed"][k] = fi
            has_element_match = True

    if has_name_match or has_element_match:
        result["_focused"] = True
        return result

    broad = {
        "added": {},
        "removed": {},
        "modified": OrderedDict(),
        "unchanged": [],
        "_focused": False,
    }
    for k, v in diff["added"].items():
        if _element_name_match(v, term):
            broad["added"][k] = v
    for k, v in diff["removed"].items():
        if _element_name_match(v, term):
            broad["removed"][k] = v
    for k, v in diff["modified"].items():
        # Only match against the actual diff delta, not the full old/new data
        if _element_name_match(v.get("changes", {}), term):
            broad["modified"][k] = v
    for k in diff["unchanged"]:
        if term in _normalize(k):
            broad["unchanged"].append(k)
    return broad


def make_serializable(obj):
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_serializable(i) for i in obj]
    return obj
