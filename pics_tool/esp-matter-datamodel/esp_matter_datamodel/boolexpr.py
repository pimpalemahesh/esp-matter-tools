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
"""Generic boolean-expression core.

This module knows nothing about Matter, conformance, or PICS. It provides a
tiny immutable AST (``And``/``Or``/``Not``/``Atom``) and an ``evaluate`` that
walks it, delegating the meaning of each leaf ``Atom`` to a caller-supplied
``resolve(payload) -> bool`` callback.

That dependency inversion is deliberate: the same boolean engine is reused by
two very different domains without either leaking into this file:

* the data-model conformance evaluator, whose atoms are feature/attribute/
  command references resolved against a cluster's state, and
* consumers such as a PICS generator, whose atoms are PICS codes resolved
  against a set of enabled codes.

A small ``parse`` helper turns a boolean *string* (``"A AND (B OR NOT C)"``,
also accepting the symbols ``& | !``) into the same AST, with each identifier
becoming an ``Atom`` whose payload is the identifier ``str``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Union


@dataclass(frozen=True)
class Atom:
    """A leaf whose truth value is decided by the resolver."""

    payload: Any


@dataclass(frozen=True)
class Not:
    arg: "Expr"


@dataclass(frozen=True)
class And:
    args: tuple["Expr", ...]


@dataclass(frozen=True)
class Or:
    args: tuple["Expr", ...]


# A boolean literal (``True``/``False``) is also a valid expression; it lets an
# empty/unconditional rule be represented as the constant ``True``.
Expr = Union[bool, Atom, Not, And, Or]

Resolver = Callable[[Any], bool]


def evaluate(expr: Expr, resolve: Resolver) -> bool:
    """Evaluate ``expr``, calling ``resolve`` on each ``Atom``'s payload."""
    match expr:
        case bool():
            return expr
        case Atom(payload):
            return resolve(payload)
        case Not(arg):
            return not evaluate(arg, resolve)
        case And(args):
            return all(evaluate(a, resolve) for a in args)
        case Or(args):
            return any(evaluate(a, resolve) for a in args)
        case _:
            raise TypeError(f"not a boolean expression node: {expr!r}")


# --------------------------------------------------------------------------- #
# String parser: "A AND (B OR NOT C)"  /  "A & (B | !C)"  ->  Expr
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(
    r"""
      \s*(?:
          (?P<lparen>\()
        | (?P<rparen>\))
        | (?P<and>\bAND\b|&&|&)
        | (?P<or>\bOR\b|\|\||\|)
        | (?P<not>\bNOT\b|!)
        | (?P<atom>[A-Za-z0-9_.]+)
      )
    """,
    re.VERBOSE,
)


class ExpressionSyntaxError(ValueError):
    """Raised when a boolean-expression string cannot be parsed."""


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise ExpressionSyntaxError(
                f"unexpected character {text[pos]!r} at index {pos} in {text!r}"
            )
        kind = m.lastgroup
        assert kind is not None
        tokens.append((kind, m.group(kind)))
        pos = m.end()
    return tokens


def parse(text: str) -> Expr:
    """Parse a boolean-expression string into an :data:`Expr`.

    ``AND``/``OR``/``NOT`` (and the symbols ``& | !``) are operators; every
    other identifier becomes ``Atom(identifier_str)``. Precedence is the usual
    ``NOT`` > ``AND`` > ``OR``; parentheses group. An empty/whitespace string
    means "no condition" and parses to the constant ``True``.
    """
    tokens = _tokenize(text)
    if not tokens:
        return True

    pos = 0

    def peek() -> str | None:
        return tokens[pos][0] if pos < len(tokens) else None

    def parse_or() -> Expr:
        nonlocal pos
        node = parse_and()
        args = [node]
        while peek() == "or":
            pos += 1
            args.append(parse_and())
        return Or(tuple(args)) if len(args) > 1 else node

    def parse_and() -> Expr:
        nonlocal pos
        node = parse_unary()
        args = [node]
        while peek() == "and":
            pos += 1
            args.append(parse_unary())
        return And(tuple(args)) if len(args) > 1 else node

    def parse_unary() -> Expr:
        nonlocal pos
        if peek() == "not":
            pos += 1
            return Not(parse_unary())
        return parse_primary()

    def parse_primary() -> Expr:
        nonlocal pos
        kind = peek()
        if kind is None:
            raise ExpressionSyntaxError(f"unexpected end of expression in {text!r}")
        if kind == "lparen":
            pos += 1
            node = parse_or()
            if peek() != "rparen":
                raise ExpressionSyntaxError(f"expected ')' in {text!r}")
            pos += 1
            return node
        if kind == "atom":
            value = tokens[pos][1]
            pos += 1
            return Atom(value)
        raise ExpressionSyntaxError(f"unexpected token {tokens[pos]!r} in {text!r}")

    result = parse_or()
    if pos != len(tokens):
        raise ExpressionSyntaxError(f"trailing tokens in {text!r}: {tokens[pos:]!r}")
    return result
