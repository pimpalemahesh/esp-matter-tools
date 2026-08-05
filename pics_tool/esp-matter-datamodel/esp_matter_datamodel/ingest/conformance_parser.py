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
"""Parse a spec-XML conformance element into a :class:`Conformance` AST.

Feature/attribute/command terms in the XML reference elements *by name/code*;
this module resolves those to the bit/id form the AST stores, using a
:class:`Resolver` built from the enclosing cluster. Anything it cannot map is
preserved as an ``Unsupported`` / ``OpaqueOperand`` node (never dropped) and
logged, matching the fail-closed-but-visible policy of the evaluator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from xml.etree.ElementTree import Element

from .. import boolexpr
from ..boolexpr import Expr
from ..model.conformance import (
    AttributeRef,
    Choice,
    CommandRef,
    Compare,
    Conformance,
    ConditionRef,
    FeatureRef,
    LiteralOperand,
    OpaqueOperand,
    RevisionOperand,
    Unsupported,
)

logger = logging.getLogger(__name__)

# conform container tag -> our conformance type
_SIMPLE_CONFORM = {
    "mandatoryConform": "mandatory",
    "optionalConform": "optional",
    "provisionalConform": "provisional",
    "disallowConform": "disallowed",
    "deprecateConform": "deprecated",
    "describedConform": "optional",  # "see description" -> not required
}
_CONFORM_TAGS = set(_SIMPLE_CONFORM) | {"otherwiseConform"}

# comparison term tag -> compare op
_CMP_TAGS = {
    "greaterTerm": "gt",
    "greaterOrEqualTerm": "ge",
    "lessTerm": "lt",
    "lessOrEqualTerm": "le",
    "equalTerm": "eq",
    "notEqualTerm": "ne",
}

_LOGIC_TAGS = {"andTerm", "orTerm", "notTerm"}
_REF_TAGS = {"feature", "attribute", "command", "condition"}
_TERM_TAGS = _REF_TAGS | _LOGIC_TAGS | set(_CMP_TAGS)


@dataclass
class Resolver:
    """Maps names/codes used in conformance terms to their resolved refs."""

    features_by_key: dict[str, FeatureRef] = field(default_factory=dict)
    attribute_ids_by_name: dict[str, str] = field(default_factory=dict)
    command_ids_by_name: dict[str, str] = field(default_factory=dict)
    context: str = ""

    def feature(self, key: str | None) -> FeatureRef | None:
        return self.features_by_key.get(key) if key else None

    def attribute_id(self, name: str | None) -> str | None:
        return self.attribute_ids_by_name.get(name) if name else None

    def command_id(self, name: str | None) -> str | None:
        return self.command_ids_by_name.get(name) if name else None


def find_conformance(element: Element, resolver: Resolver) -> Conformance:
    """Return the conformance of ``element`` (its first conform child).

    Elements without an explicit conform are treated as optional (allowed but
    not required) and logged.
    """
    for child in element:
        if child.tag in _CONFORM_TAGS:
            return _parse_conform(child, resolver)
    logger.debug("no conformance found in <%s> (%s); defaulting to optional",
                 element.tag, resolver.context)
    return Conformance("optional")


def _parse_conform(el: Element, resolver: Resolver) -> Conformance:
    if el.tag == "otherwiseConform":
        items = [_parse_conform(c, resolver) for c in el if c.tag in _CONFORM_TAGS]
        return Conformance("otherwise", items=tuple(items))

    ctype = _SIMPLE_CONFORM[el.tag]
    choice = _parse_choice(el)
    terms = [c for c in el if c.tag in _TERM_TAGS]
    condition = _parse_terms(terms, resolver)
    return Conformance(ctype, condition=condition, choice=choice)


def _parse_choice(el: Element) -> Choice | None:
    marker = el.attrib.get("choice")
    if not marker:
        return None
    return Choice(marker=marker, more=el.attrib.get("more") == "true")


def _parse_terms(elements: list[Element], resolver: Resolver) -> Expr | None:
    exprs = [_parse_term(e, resolver) for e in elements]
    exprs = [e for e in exprs if e is not None]
    if not exprs:
        return None
    if len(exprs) == 1:
        return exprs[0]
    return boolexpr.And(tuple(exprs))  # implicit AND of sibling terms


def _parse_term(el: Element, resolver: Resolver) -> Expr:
    tag = el.tag
    if tag == "feature":
        name = el.attrib.get("name")
        ref = resolver.feature(name)
        if ref is None:
            logger.warning("unresolved feature %r in %s", name, resolver.context)
            return boolexpr.Atom(Unsupported(f"feature:{name}"))
        return boolexpr.Atom(ref)
    if tag == "attribute":
        name = el.attrib.get("name")
        aid = resolver.attribute_id(name)
        if aid is None:
            return boolexpr.Atom(Unsupported(f"attribute:{name}"))
        return boolexpr.Atom(AttributeRef(name, aid))
    if tag == "command":
        name = el.attrib.get("name")
        cid = resolver.command_id(name)
        if cid is None:
            return boolexpr.Atom(Unsupported(f"command:{name}"))
        return boolexpr.Atom(CommandRef(name, cid))
    if tag == "condition":
        return boolexpr.Atom(ConditionRef(el.attrib["name"]))
    if tag == "andTerm":
        return boolexpr.And(tuple(_child_terms(el, resolver)))
    if tag == "orTerm":
        return boolexpr.Or(tuple(_child_terms(el, resolver)))
    if tag == "notTerm":
        inner = _parse_terms([c for c in el if c.tag in _TERM_TAGS], resolver)
        return boolexpr.Not(inner if inner is not None else boolexpr.Atom(Unsupported("not:empty")))
    if tag in _CMP_TAGS:
        operands = [c for c in el]
        if len(operands) != 2:
            logger.warning("comparison %s with %d operands in %s", tag, len(operands),
                           resolver.context)
            return boolexpr.Atom(Unsupported(f"compare:{tag}"))
        left = _parse_operand(operands[0])
        right = _parse_operand(operands[1])
        return boolexpr.Atom(Compare(_CMP_TAGS[tag], left, right))
    logger.warning("unsupported conformance term <%s> in %s", tag, resolver.context)
    return boolexpr.Atom(Unsupported(tag))


def _child_terms(el: Element, resolver: Resolver) -> list[Expr]:
    return [_parse_term(c, resolver) for c in el if c.tag in _TERM_TAGS]


def _parse_operand(el: Element) -> object:
    if el.tag == "revision":
        return RevisionOperand()
    if el.tag == "literal":
        return LiteralOperand(el.attrib.get("value"))
    # Attribute values, statuses, enum items, etc. are not tracked -> opaque.
    detail = el.attrib.get("name") or el.tag
    return OpaqueOperand(f"{el.tag}:{detail}" if el.attrib.get("name") else el.tag)
