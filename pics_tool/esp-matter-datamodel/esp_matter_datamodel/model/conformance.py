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
"""The conformance model: a lossless tagged AST plus a pure evaluator.

A ``Conformance`` node carries a ``type`` (mandatory/optional/provisional/
disallowed/deprecated) with an optional boolean ``condition`` over feature/
attribute/command references, or ``type == "otherwise"`` with an ordered list
of fallback clauses (the spec's ``,`` list).

Evaluation is a single pure function, :func:`evaluate`, dispatched with a
``match`` over the node ``type``. The condition's boolean structure is handled
by the domain-neutral :mod:`esp_matter_datamodel.boolexpr`; only the *leaves*
are conformance-specific and are resolved here against a
:class:`ConformanceContext` (the chosen feature mask + present element ids).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional

from .. import boolexpr
from ..boolexpr import Expr

logger = logging.getLogger(__name__)


class Decision(Enum):
    """The outcome of evaluating a conformance in a given context."""

    MANDATORY = auto()
    OPTIONAL = auto()
    PROVISIONAL = auto()
    DISALLOWED = auto()
    NOT_APPLICABLE = auto()  # allowed-absent: not required for this state


# --- condition leaf references (payloads of boolexpr Atoms) ---------------- #


@dataclass(frozen=True)
class FeatureRef:
    code: str
    bit: int


@dataclass(frozen=True)
class AttributeRef:
    name: str
    id: str


@dataclass(frozen=True)
class CommandRef:
    name: str
    id: str


@dataclass(frozen=True)
class ConditionRef:
    """A device-level condition, e.g. "Wi-Fi", "IP", "Server", "SIT"."""

    name: str


@dataclass(frozen=True)
class RevisionOperand:
    """Refers to the cluster revision in a comparison."""


@dataclass(frozen=True)
class LiteralOperand:
    value: object


@dataclass(frozen=True)
class OpaqueOperand:
    """An operand we intentionally do not resolve (e.g. an attribute value)."""

    detail: str


@dataclass(frozen=True)
class Compare:
    """A numeric comparison term, e.g. ``revision >= 2``."""

    cmp: str  # one of: gt, ge, lt, le, eq, ne
    left: object
    right: object


@dataclass(frozen=True)
class Unsupported:
    """A conformance term we preserve losslessly but cannot evaluate."""

    detail: str


@dataclass(frozen=True)
class Choice:
    """A choice group: pick exactly one (``more=False``) or one-or-more."""

    marker: str
    more: bool


# --- the conformance node -------------------------------------------------- #

_CONDITIONAL_TYPES = {"mandatory", "optional", "provisional"}
_VALID_TYPES = _CONDITIONAL_TYPES | {"disallowed", "deprecated", "otherwise"}


@dataclass(frozen=True)
class Conformance:
    type: str
    condition: Optional[Expr] = None
    items: tuple["Conformance", ...] = ()
    choice: Optional[Choice] = None

    def __post_init__(self) -> None:
        if self.type not in _VALID_TYPES:
            raise ValueError(f"unknown conformance type: {self.type!r}")


@dataclass(frozen=True)
class ConformanceResult:
    decision: Decision
    choice: Optional[Choice] = None

    def is_mandatory(self) -> bool:
        return self.decision == Decision.MANDATORY

    def is_optional(self) -> bool:
        return self.decision == Decision.OPTIONAL


@dataclass
class ConformanceContext:
    """The device/cluster state a condition is evaluated against."""

    feature_mask: int = 0
    attribute_ids: frozenset[str] = field(default_factory=frozenset)
    command_ids: frozenset[str] = field(default_factory=frozenset)
    cluster_revision: int = 1
    active_conditions: frozenset[str] = field(default_factory=frozenset)


# The empty context: nothing enabled. Useful for state-independent checks such
# as classifying a device-type's cluster requirement (which never depends on
# cluster element state).
EMPTY_CONTEXT = ConformanceContext()

UnknownHandler = Callable[[Any], None]


_warned_unknown: set[str] = set()


def _default_unknown(payload: Any) -> None:
    # D9: fail-closed but visible — treat as absent, keep going. The same
    # reference is evaluated once per element per engine run, so warn only
    # once per distinct payload or a single generation floods the output.
    key = repr(payload)
    if key not in _warned_unknown:
        _warned_unknown.add(key)
        logger.warning("unresolvable conformance reference treated as absent: %s", key)


_CMP_OPS = {
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


def _operand_value(operand: Any, ctx: ConformanceContext) -> int | None:
    """Return the numeric value of a comparison operand, or None if unknowable."""
    match operand:
        case RevisionOperand():
            return ctx.cluster_revision
        case LiteralOperand(value):
            try:
                return int(value, 0) if isinstance(value, str) else int(value)
            except (TypeError, ValueError):
                return None
        case _:
            return None  # e.g. an attribute value we do not track


def _make_resolver(ctx: ConformanceContext, on_unknown: UnknownHandler) -> boolexpr.Resolver:
    def resolve(payload: Any) -> bool:
        match payload:
            case FeatureRef(_, bit):
                return bool(ctx.feature_mask & (1 << bit))
            case AttributeRef(_, id):
                return id in ctx.attribute_ids
            case CommandRef(_, id):
                return id in ctx.command_ids
            case ConditionRef(name):
                return name in ctx.active_conditions
            case Compare(cmp, left, right):
                lv = _operand_value(left, ctx)
                rv = _operand_value(right, ctx)
                if lv is None or rv is None:
                    on_unknown(payload)  # fail-closed on unresolvable comparison
                    return False
                return _CMP_OPS[cmp](lv, rv)
            case Unsupported(_):
                on_unknown(payload)
                return False
            case _:
                on_unknown(payload)
                return False

    return resolve


def evaluate(
    conformance: Conformance,
    ctx: ConformanceContext,
    *,
    on_unknown: UnknownHandler | None = None,
) -> ConformanceResult:
    """Evaluate ``conformance`` in ``ctx`` and return a :class:`ConformanceResult`."""
    resolve = _make_resolver(ctx, on_unknown or _default_unknown)
    return _evaluate(conformance, resolve)


def _evaluate(conformance: Conformance, resolve: boolexpr.Resolver) -> ConformanceResult:
    match conformance.type:
        case "mandatory":
            if _condition_holds(conformance, resolve):
                return ConformanceResult(Decision.MANDATORY)
            return ConformanceResult(Decision.NOT_APPLICABLE)
        case "optional":
            if _condition_holds(conformance, resolve):
                return ConformanceResult(Decision.OPTIONAL, conformance.choice)
            return ConformanceResult(Decision.NOT_APPLICABLE)
        case "provisional":
            if _condition_holds(conformance, resolve):
                return ConformanceResult(Decision.PROVISIONAL)
            return ConformanceResult(Decision.NOT_APPLICABLE)
        case "disallowed" | "deprecated":
            return ConformanceResult(Decision.DISALLOWED)
        case "otherwise":
            # Ordered fallback: first clause that applies wins.
            for item in conformance.items:
                result = _evaluate(item, resolve)
                if result.decision != Decision.NOT_APPLICABLE:
                    return result
            return ConformanceResult(Decision.NOT_APPLICABLE)
        case _:  # pragma: no cover - guarded by Conformance.__post_init__
            raise ValueError(f"unknown conformance type: {conformance.type!r}")


def _condition_holds(conformance: Conformance, resolve: boolexpr.Resolver) -> bool:
    if conformance.condition is None:
        return True
    return boolexpr.evaluate(conformance.condition, resolve)


# --------------------------------------------------------------------------- #
# JSON (de)serialization — the on-disk form of the conformance AST.
# --------------------------------------------------------------------------- #


def _operand_from_json(node: dict) -> object:
    op = node["op"]
    match op:
        case "revision":
            return RevisionOperand()
        case "literal":
            return LiteralOperand(node["value"])
        case "opaque":
            return OpaqueOperand(node.get("detail", ""))
        case _:
            raise ValueError(f"unknown comparison operand op: {op!r}")


def _operand_to_json(operand: object) -> dict:
    match operand:
        case RevisionOperand():
            return {"op": "revision"}
        case LiteralOperand(value):
            return {"op": "literal", "value": value}
        case OpaqueOperand(detail):
            return {"op": "opaque", "detail": detail}
        case _:
            raise TypeError(f"cannot serialize comparison operand: {operand!r}")


def condition_from_json(node: dict) -> Expr:
    op = node["op"]
    match op:
        case "and":
            return boolexpr.And(tuple(condition_from_json(a) for a in node["args"]))
        case "or":
            return boolexpr.Or(tuple(condition_from_json(a) for a in node["args"]))
        case "not":
            return boolexpr.Not(condition_from_json(node["arg"]))
        case "feature":
            return boolexpr.Atom(FeatureRef(node["code"], node["bit"]))
        case "attribute":
            return boolexpr.Atom(AttributeRef(node["name"], node["id"]))
        case "command":
            return boolexpr.Atom(CommandRef(node["name"], node["id"]))
        case "condition":
            return boolexpr.Atom(ConditionRef(node["name"]))
        case "compare":
            left, right = node["args"]
            return boolexpr.Atom(
                Compare(node["cmp"], _operand_from_json(left), _operand_from_json(right))
            )
        case "unsupported":
            return boolexpr.Atom(Unsupported(node.get("detail", "")))
        case _:
            raise ValueError(f"unknown condition op: {op!r}")


def condition_to_json(expr: Expr) -> dict:
    match expr:
        case boolexpr.And(args):
            return {"op": "and", "args": [condition_to_json(a) for a in args]}
        case boolexpr.Or(args):
            return {"op": "or", "args": [condition_to_json(a) for a in args]}
        case boolexpr.Not(arg):
            return {"op": "not", "arg": condition_to_json(arg)}
        case boolexpr.Atom(FeatureRef(code, bit)):
            return {"op": "feature", "code": code, "bit": bit}
        case boolexpr.Atom(AttributeRef(name, id)):
            return {"op": "attribute", "name": name, "id": id}
        case boolexpr.Atom(CommandRef(name, id)):
            return {"op": "command", "name": name, "id": id}
        case boolexpr.Atom(ConditionRef(name)):
            return {"op": "condition", "name": name}
        case boolexpr.Atom(Compare(cmp, left, right)):
            return {"op": "compare", "cmp": cmp,
                    "args": [_operand_to_json(left), _operand_to_json(right)]}
        case boolexpr.Atom(Unsupported(detail)):
            return {"op": "unsupported", "detail": detail}
        case _:
            raise TypeError(f"cannot serialize condition node: {expr!r}")


def conformance_from_json(node: dict) -> Conformance:
    ctype = node["type"]
    if ctype == "otherwise":
        return Conformance(
            "otherwise",
            items=tuple(conformance_from_json(i) for i in node["items"]),
        )
    condition = condition_from_json(node["condition"]) if "condition" in node else None
    choice = None
    if "choice" in node:
        choice = Choice(node["choice"]["marker"], node["choice"]["more"])
    return Conformance(ctype, condition=condition, choice=choice)


def conformance_to_json(conformance: Conformance) -> dict:
    if conformance.type == "otherwise":
        return {
            "type": "otherwise",
            "items": [conformance_to_json(i) for i in conformance.items],
        }
    out: dict = {"type": conformance.type}
    if conformance.condition is not None:
        out["condition"] = condition_to_json(conformance.condition)
    if conformance.choice is not None:
        out["choice"] = {
            "marker": conformance.choice.marker,
            "more": conformance.choice.more,
        }
    return out
