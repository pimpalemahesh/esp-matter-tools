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
import pytest

from esp_matter_datamodel import boolexpr
from esp_matter_datamodel.boolexpr import And, Atom, ExpressionSyntaxError, Not, Or


def resolve_set(enabled):
    return lambda atom: atom in enabled


def test_evaluate_atoms_and_ops():
    expr = And((Atom("A"), Or((Atom("B"), Not(Atom("C"))))))
    assert boolexpr.evaluate(expr, resolve_set({"A", "B"})) is True
    assert boolexpr.evaluate(expr, resolve_set({"A"})) is True  # not C
    assert boolexpr.evaluate(expr, resolve_set({"B", "C"})) is False  # A missing
    assert boolexpr.evaluate(expr, resolve_set({"A", "C"})) is False  # B missing, C present


def test_evaluate_bool_constants():
    assert boolexpr.evaluate(True, resolve_set(set())) is True
    assert boolexpr.evaluate(False, resolve_set(set())) is False


def test_parse_empty_is_true():
    assert boolexpr.parse("") is True
    assert boolexpr.parse("   ") is True


def test_parse_precedence_not_over_and_over_or():
    # A OR B AND C  ==  A OR (B AND C)
    expr = boolexpr.parse("A OR B AND C")
    assert boolexpr.evaluate(expr, resolve_set({"B", "C"})) is True
    assert boolexpr.evaluate(expr, resolve_set({"B"})) is False
    assert boolexpr.evaluate(expr, resolve_set({"A"})) is True


def test_parse_not_binds_tightest():
    expr = boolexpr.parse("NOT A AND B")  # (NOT A) AND B
    assert boolexpr.evaluate(expr, resolve_set({"B"})) is True
    assert boolexpr.evaluate(expr, resolve_set({"A", "B"})) is False


def test_parse_parentheses_override():
    expr = boolexpr.parse("(A OR B) AND C")
    assert boolexpr.evaluate(expr, resolve_set({"A", "C"})) is True
    assert boolexpr.evaluate(expr, resolve_set({"A"})) is False


def test_parse_symbol_operators():
    expr = boolexpr.parse("A & (B | !C)")
    assert boolexpr.evaluate(expr, resolve_set({"A", "B"})) is True
    assert boolexpr.evaluate(expr, resolve_set({"A"})) is True
    assert boolexpr.evaluate(expr, resolve_set({"A", "C"})) is False


def test_parse_dotted_atoms():
    expr = boolexpr.parse("MCORE.ROLE.COMMISSIONER AND MCORE.COM.BLE")
    assert boolexpr.evaluate(
        expr, resolve_set({"MCORE.ROLE.COMMISSIONER", "MCORE.COM.BLE"})
    ) is True
    assert boolexpr.evaluate(expr, resolve_set({"MCORE.COM.BLE"})) is False


def test_unknown_atom_resolves_false():
    expr = boolexpr.parse("A")
    assert boolexpr.evaluate(expr, resolve_set(set())) is False


@pytest.mark.parametrize("bad", ["A AND", "(A OR B", "A B", ")", "AND A"])
def test_parse_syntax_errors(bad):
    with pytest.raises(ExpressionSyntaxError):
        boolexpr.parse(bad)
