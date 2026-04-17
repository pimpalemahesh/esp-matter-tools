"""
Matter Data Model Diff Engine — Pyodide-compatible (no Flask, no filesystem).
Accepts XML strings, returns JSON-serializable dicts.
"""

import json
import xml.etree.ElementTree as ET
from collections import OrderedDict


# ---------------------------------------------------------------------------
# XML Parsing
# ---------------------------------------------------------------------------


def _text(el, default=""):
    return (el.text or "").strip() if el is not None else default


def _attr(el, name, default=""):
    return el.get(name, default) if el is not None else default


def _render_choice(el):
    choice = el.get("choice", "")
    if not choice:
        return ""
    n = el.get("min", "")
    more = el.get("more", "") == "true"
    result = f".{choice}"
    if n and n != "1":
        result += n
    if more:
        result += "+"
    return result


def _render_value_term(el):
    tag = el.tag
    ops = {
        "equalTerm": "==",
        "greaterTerm": ">",
        "greaterOrEqualTerm": ">=",
        "lessTerm": "<",
        "lessOrEqualTerm": "<=",
    }
    op = ops.get(tag, "?")
    children = list(el)
    if len(children) == 2:
        left = children[0]
        right = children[1]
        lv = left.get("name", "") or left.get("value", left.tag)
        rv = right.get("name", "") or right.get("value", right.tag)
        return f"{lv} {op} {rv}"
    return tag


def _render_expr(el, parent_tag=None):
    tag = el.tag
    if tag == "feature":
        return el.get("name", "?")
    if tag == "attribute":
        return el.get("name", "?")
    if tag == "condition":
        return el.get("name", "?")
    if tag == "field":
        return el.get("name", "?")
    if tag == "literal":
        return el.get("value", "?")
    if tag in (
        "equalTerm",
        "greaterTerm",
        "greaterOrEqualTerm",
        "lessTerm",
        "lessOrEqualTerm",
    ):
        return _render_value_term(el)
    if tag == "notTerm":
        children = list(el)
        if len(children) == 1:
            inner = _render_expr(children[0], None)
            if children[0].tag in ("orTerm", "andTerm", "xorTerm"):
                return f"!({inner})"
            return f"!{inner}"
        return "!" + " & ".join(_render_expr(c, None) for c in children)
    if tag == "orTerm":
        parts = [_render_expr(c, tag) for c in el]
        expr = " | ".join(parts)
        if parent_tag in ("andTerm", "notTerm"):
            return f"({expr})"
        return expr
    if tag == "andTerm":
        parts = [_render_expr(c, tag) for c in el]
        expr = " & ".join(parts)
        if parent_tag in ("orTerm", "notTerm"):
            return f"({expr})"
        return expr
    if tag == "xorTerm":
        parts = [_render_expr(c, tag) for c in el]
        return " ^ ".join(parts)
    if tag in (
        "mandatoryConform",
        "optionalConform",
        "provisionalConform",
        "deprecateConform",
        "describedConform",
        "disallowConform",
        "otherwiseConform",
    ):
        return _render_conformance_single(el)
    return tag


def _render_conformance_single(el):
    tag = el.tag
    if tag == "mandatoryConform":
        children = list(el)
        if not children:
            return "M"
        return _render_expr(children[0])
    if tag == "optionalConform":
        children = list(el)
        choice_str = _render_choice(el)
        if not children:
            return f"O{choice_str}"
        return f"[{_render_expr(children[0])}]{choice_str}"
    if tag == "otherwiseConform":
        branches = [_render_conformance_single(b) for b in el]
        return ", ".join(branches)
    if tag == "provisionalConform":
        return "P"
    if tag == "deprecateConform":
        return "D"
    if tag == "disallowConform":
        return "X"
    if tag == "describedConform":
        return "desc"
    if tag == "feature":
        return el.get("name", "?")
    if tag == "condition":
        return el.get("name", "?")
    return tag


def parse_conformance(el):
    if el is None:
        return ""
    parts = []
    for child in el:
        parts.append(_render_conformance_single(child))
    return ", ".join(parts) if parts else ""


def get_conformance(el):
    conf_tags = {
        "mandatoryConform",
        "optionalConform",
        "otherwiseConform",
        "deprecateConform",
        "provisionalConform",
        "describedConform",
        "disallowConform",
    }
    fake_parent = ET.Element("_wrap")
    for child in el:
        if child.tag in conf_tags:
            fake_parent.append(child)
    return parse_conformance(fake_parent)


def parse_access(el):
    acc = el.find("access")
    if acc is None:
        return ""
    parts = []
    r = acc.get("read")
    w = acc.get("write")
    if r == "true" and w == "true":
        parts.append("read/write")
    elif r == "true":
        parts.append("readable")
    elif w == "true":
        parts.append("writable")
    rp = acc.get("readPrivilege")
    if rp:
        parts.append(f"read: {rp}")
    wp = acc.get("writePrivilege")
    if wp:
        parts.append(f"write: {wp}")
    ip = acc.get("invokePrivilege")
    if ip:
        parts.append(f"invoke: {ip}")
    if acc.get("fabricScoped") == "true":
        parts.append("fabric-scoped")
    if acc.get("fabricSensitive") == "true":
        parts.append("fabric-sensitive")
    if acc.get("timed") == "true":
        parts.append("timed")
    return ", ".join(parts)


def parse_quality(el):
    q = el.find("quality")
    if q is None:
        return ""
    parts = []
    for k in sorted(q.attrib):
        parts.append(f"{k}={q.get(k)}")
    return "; ".join(parts)


def parse_constraint(el):
    c = el.find("constraint")
    if c is None:
        return ""
    parts = []
    for child in c:
        tag = child.tag
        if tag == "desc":
            parts.append("desc")
        elif tag in ("min", "max", "maxLength", "maxCount"):
            parts.append(f"{tag}={child.get('value', '?')}")
        elif tag == "between" or tag == "countBetween":
            fr = child.find("from")
            to = child.find("to")
            fv = fr.get("value", "?") if fr is not None else "?"
            tv = to.get("value", "?") if to is not None else "?"
            parts.append(f"{tag}[{fv}..{tv}]")
        elif tag == "allowed":
            parts.append(f"allowed={child.get('value', '?')}")
    return "; ".join(parts)


def parse_field(field_el):
    return {
        "id": field_el.get("id", ""),
        "name": field_el.get("name", ""),
        "type": field_el.get("type", ""),
        "conformance": get_conformance(field_el),
        "access": parse_access(field_el),
        "quality": parse_quality(field_el),
        "constraint": parse_constraint(field_el),
    }


def parse_cluster_xml_string(xml_string):
    """Parse a cluster XML string and return structured data."""
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None
    if root.tag != "cluster":
        return None

    cluster = OrderedDict()
    cluster["id"] = root.get("id", "")
    cluster["name"] = root.get("name", "")
    cluster["revision"] = root.get("revision", "")

    rh = root.find("revisionHistory")
    cluster["revisions"] = []
    if rh is not None:
        for rev in rh.findall("revision"):
            cluster["revisions"].append(
                {
                    "revision": rev.get("revision", ""),
                    "summary": rev.get("summary", ""),
                }
            )

    cls = root.find("classification")
    if cls is not None:
        cluster["classification"] = {
            k: cls.get(k, "") for k in ("hierarchy", "role", "picsCode", "scope")
        }
    else:
        cluster["classification"] = {}

    cluster["features"] = OrderedDict()
    feat_el = root.find("features")
    if feat_el is not None:
        feat_list = []
        for f in feat_el.findall("feature"):
            feat_list.append(
                {
                    "bit": f.get("bit", ""),
                    "code": f.get("code", ""),
                    "name": f.get("name", ""),
                    "summary": f.get("summary", ""),
                    "conformance": get_conformance(f),
                }
            )
        feat_list.sort(key=lambda x: int(x["bit"]) if x["bit"].isdigit() else 999)
        for fd in feat_list:
            cluster["features"][fd["name"] or fd["code"]] = fd

    cluster["dataTypes"] = OrderedDict()
    dt_el = root.find("dataTypes")
    if dt_el is not None:
        for child in dt_el:
            tag = child.tag
            name = child.get("name", "")
            key = f"{tag}:{name}"
            if tag == "enum":
                items = []
                for item in child.findall("item"):
                    items.append(
                        {
                            "value": item.get("value", ""),
                            "name": item.get("name", ""),
                            "summary": item.get("summary", ""),
                            "conformance": get_conformance(item),
                        }
                    )
                cluster["dataTypes"][key] = {
                    "kind": "enum",
                    "name": name,
                    "items": items,
                }
            elif tag == "bitmap":
                fields = []
                for bf in child.findall("bitfield"):
                    fields.append(
                        {
                            "bit": bf.get("bit", ""),
                            "name": bf.get("name", ""),
                            "summary": bf.get("summary", ""),
                            "conformance": get_conformance(bf),
                        }
                    )
                cluster["dataTypes"][key] = {
                    "kind": "bitmap",
                    "name": name,
                    "fields": fields,
                }
            elif tag == "struct":
                fields = []
                for sf in child.findall("field"):
                    fields.append(parse_field(sf))
                cluster["dataTypes"][key] = {
                    "kind": "struct",
                    "name": name,
                    "fields": fields,
                }
            elif tag == "number":
                cluster["dataTypes"][key] = {
                    "kind": "number",
                    "name": name,
                    "type": child.get("type", ""),
                }

    attrs = []
    attr_el = root.find("attributes")
    if attr_el is not None:
        for a in attr_el.findall("attribute"):
            aid = a.get("id", "")
            attrs.append(
                (
                    aid,
                    {
                        "id": aid,
                        "name": a.get("name", ""),
                        "type": a.get("type", ""),
                        "conformance": get_conformance(a),
                        "access": parse_access(a),
                        "quality": parse_quality(a),
                        "constraint": parse_constraint(a),
                    },
                )
            )
    attrs.sort(key=lambda x: int(x[0], 16) if x[0].startswith("0x") else 0)
    cluster["attributes"] = OrderedDict(attrs)

    cmds = []
    cmd_el = root.find("commands")
    if cmd_el is not None:
        for c in cmd_el.findall("command"):
            cid = c.get("id", "")
            cname = c.get("name", "")
            key = f"{cid}_{cname}"
            fields = [parse_field(f) for f in c.findall("field")]
            cmds.append(
                (
                    key,
                    {
                        "id": cid,
                        "name": cname,
                        "direction": c.get("direction", ""),
                        "response": c.get("response", ""),
                        "conformance": get_conformance(c),
                        "access": parse_access(c),
                        "fields": fields,
                    },
                )
            )
    cmds.sort(
        key=lambda x: (
            int(x[1]["id"], 16) if x[1]["id"].startswith("0x") else 0,
            x[1]["name"],
        )
    )
    cluster["commands"] = OrderedDict(cmds)

    evts = []
    evt_el = root.find("events")
    if evt_el is not None:
        for e in evt_el.findall("event"):
            eid = e.get("id", "")
            fields = [parse_field(f) for f in e.findall("field")]
            evts.append(
                (
                    eid,
                    {
                        "id": eid,
                        "name": e.get("name", ""),
                        "priority": e.get("priority", ""),
                        "conformance": get_conformance(e),
                        "access": parse_access(e),
                        "fields": fields,
                    },
                )
            )
    evts.sort(key=lambda x: int(x[0], 16) if x[0].startswith("0x") else 0)
    cluster["events"] = OrderedDict(evts)

    return cluster


def parse_device_type_xml_string(xml_string):
    """Parse a device type XML string and return structured data."""
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None
    if root.tag != "deviceType":
        return None

    dt = OrderedDict()
    dt["id"] = root.get("id", "")
    dt["name"] = root.get("name", "")
    dt["revision"] = root.get("revision", "")

    rh = root.find("revisionHistory")
    dt["revisions"] = []
    if rh is not None:
        for rev in rh.findall("revision"):
            dt["revisions"].append(
                {
                    "revision": rev.get("revision", ""),
                    "summary": rev.get("summary", ""),
                }
            )

    cls = root.find("classification")
    if cls is not None:
        dt["classification"] = {k: cls.get(k, "") for k in ("class", "scope")}
    else:
        dt["classification"] = {}

    dt["conditions"] = OrderedDict()
    cond_el = root.find("conditions")
    if cond_el is not None:
        for c in cond_el.findall("condition"):
            dt["conditions"][c.get("name", "")] = c.get("summary", "")

    dt["conditionRequirements"] = OrderedDict()
    cr_el = root.find("conditionRequirements")
    if cr_el is not None:
        for dt_el_inner in cr_el.findall("deviceType"):
            dt_id = dt_el_inner.get("id", "")
            dt_name = dt_el_inner.get("name", "")
            reqs = OrderedDict()
            for req in dt_el_inner.findall("conditionRequirement"):
                req_name = req.get("name", "")
                reqs[req_name] = {
                    "name": req_name,
                    "conformance": get_conformance(req),
                }
            dt["conditionRequirements"][f"{dt_id}_{dt_name}"] = {
                "id": dt_id,
                "name": dt_name,
                "requirements": reqs,
            }

    dt["clusters"] = OrderedDict()
    clusters_el = root.find("clusters")
    if clusters_el is not None:
        for c in clusters_el.findall("cluster"):
            cid = c.get("id", "")
            side = c.get("side", "server")
            key = f"{cid}_{side}"
            cluster_info = {
                "id": cid,
                "name": c.get("name", ""),
                "side": side,
                "conformance": get_conformance(c),
            }
            feats = OrderedDict()
            feat_el = c.find("features")
            if feat_el is not None:
                for f in feat_el.findall("feature"):
                    code = f.get("code", "")
                    feats[code] = {
                        "code": code,
                        "conformance": get_conformance(f),
                    }
            cluster_info["features"] = feats

            attrs = OrderedDict()
            attr_el = c.find("attributes")
            if attr_el is not None:
                for a in attr_el.findall("attribute"):
                    acode = a.get("code", a.get("id", ""))
                    attrs[acode] = {
                        "code": acode,
                        "name": a.get("name", ""),
                        "constraint": parse_constraint(a),
                    }
            cluster_info["attributes"] = attrs

            cmds = OrderedDict()
            cmd_el = c.find("commands")
            if cmd_el is not None:
                for cmd in cmd_el.findall("command"):
                    cmd_id = cmd.get("id", "")
                    cmds[cmd_id] = {
                        "id": cmd_id,
                        "name": cmd.get("name", ""),
                        "conformance": get_conformance(cmd),
                    }
            cluster_info["commands"] = cmds

            dt["clusters"][key] = cluster_info

    return dt


# ---------------------------------------------------------------------------
# Diff Engine
# ---------------------------------------------------------------------------


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
    """Compute diff between two OrderedDicts of parsed items (clusters or device types)."""
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


# ---------------------------------------------------------------------------
# Search / Filter
# ---------------------------------------------------------------------------


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
    Used for the broad fallback to avoid false positives from prose text."""
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
    if isinstance(obj, OrderedDict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [make_serializable(i) for i in obj]
    return obj


# ---------------------------------------------------------------------------
# Public API — called from JavaScript via Pyodide
# ---------------------------------------------------------------------------


def run_diff(old_xml_map, new_xml_map, category, name_filter, item_type):
    """
    Run diff on two maps of {filename: xml_string}.
    item_type: 'clusters' or 'device_types'
    Returns a JSON string.
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
