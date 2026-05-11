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

"""XML parsing functions for Matter Data Model XML files"""

import xml.etree.ElementTree as ET
from collections import OrderedDict


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
