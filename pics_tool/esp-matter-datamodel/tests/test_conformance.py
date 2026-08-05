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
from esp_matter_datamodel.model import conformance as C
from esp_matter_datamodel.model.conformance import (
    ConformanceContext,
    Decision,
    conformance_from_json,
    conformance_to_json,
)

# Illustrative feature bits (On/Off-like): LT=0, OFFONLY=2, FAULTEV=3.
CTX_NONE = ConformanceContext(feature_mask=0)
CTX_LT = ConformanceContext(feature_mask=1 << 0)
CTX_OFFONLY = ConformanceContext(feature_mask=1 << 2)
CTX_FAULTEV = ConformanceContext(feature_mask=1 << 3)


def test_unconditional_mandatory():
    conf = conformance_from_json({"type": "mandatory"})
    assert C.evaluate(conf, CTX_NONE).is_mandatory()


def test_mandatory_if_feature():
    conf = conformance_from_json(
        {"type": "mandatory", "condition": {"op": "feature", "code": "LT", "bit": 0}}
    )
    assert C.evaluate(conf, CTX_LT).is_mandatory()
    assert C.evaluate(conf, CTX_NONE).decision == Decision.NOT_APPLICABLE


def test_mandatory_if_not_feature():
    conf = conformance_from_json(
        {"type": "mandatory",
         "condition": {"op": "not", "arg": {"op": "feature", "code": "OFFONLY", "bit": 2}}}
    )
    assert C.evaluate(conf, CTX_NONE).is_mandatory()
    assert C.evaluate(conf, CTX_OFFONLY).decision == Decision.NOT_APPLICABLE


def test_optional_carries_choice():
    conf = conformance_from_json(
        {"type": "optional", "choice": {"marker": "a", "more": False}}
    )
    result = C.evaluate(conf, CTX_NONE)
    assert result.decision == Decision.OPTIONAL
    assert result.choice is not None
    assert result.choice.marker == "a" and result.choice.more is False


def test_otherwise_first_applicable_wins():
    conf = conformance_from_json(
        {"type": "otherwise", "items": [
            {"type": "mandatory", "condition": {"op": "feature", "code": "FAULTEV", "bit": 3}},
            {"type": "optional"},
        ]}
    )
    assert C.evaluate(conf, CTX_FAULTEV).is_mandatory()
    assert C.evaluate(conf, CTX_NONE).decision == Decision.OPTIONAL


def test_disallowed_and_deprecated():
    assert C.evaluate(conformance_from_json({"type": "disallowed"}), CTX_NONE).decision \
        == Decision.DISALLOWED
    assert C.evaluate(conformance_from_json({"type": "deprecated"}), CTX_NONE).decision \
        == Decision.DISALLOWED


def test_and_or_condition():
    conf = conformance_from_json(
        {"type": "mandatory", "condition": {"op": "or", "args": [
            {"op": "feature", "code": "LT", "bit": 0},
            {"op": "feature", "code": "FAULTEV", "bit": 3},
        ]}}
    )
    assert C.evaluate(conf, CTX_LT).is_mandatory()
    assert C.evaluate(conf, CTX_FAULTEV).is_mandatory()
    assert C.evaluate(conf, CTX_OFFONLY).decision == Decision.NOT_APPLICABLE


def test_condition_leaf():
    conf = conformance_from_json(
        {"type": "mandatory", "condition": {"op": "condition", "name": "Wi-Fi"}}
    )
    ctx_wifi = ConformanceContext(active_conditions=frozenset({"Wi-Fi"}))
    assert C.evaluate(conf, ctx_wifi).is_mandatory()
    assert C.evaluate(conf, CTX_NONE).decision == Decision.NOT_APPLICABLE


def test_compare_revision():
    conf = conformance_from_json(
        {"type": "mandatory", "condition": {
            "op": "compare", "cmp": "ge",
            "args": [{"op": "revision"}, {"op": "literal", "value": 2}]}}
    )
    assert C.evaluate(conf, ConformanceContext(cluster_revision=3)).is_mandatory()
    assert C.evaluate(conf, ConformanceContext(cluster_revision=1)).decision \
        == Decision.NOT_APPLICABLE


def test_compare_opaque_is_fail_closed():
    conf = conformance_from_json(
        {"type": "mandatory", "condition": {
            "op": "compare", "cmp": "eq",
            "args": [{"op": "opaque", "detail": "SomeAttr"}, {"op": "literal", "value": 1}]}}
    )
    # Unresolvable operand -> not mandatory (fail-closed).
    assert C.evaluate(conf, CTX_NONE, on_unknown=lambda p: None).decision \
        == Decision.NOT_APPLICABLE


def test_unsupported_is_fail_closed():
    conf = conformance_from_json(
        {"type": "mandatory", "condition": {"op": "unsupported", "detail": "status"}}
    )
    assert C.evaluate(conf, CTX_NONE, on_unknown=lambda p: None).decision \
        == Decision.NOT_APPLICABLE


def test_json_round_trip():
    nodes = [
        {"type": "mandatory"},
        {"type": "mandatory", "condition": {"op": "feature", "code": "LT", "bit": 0}},
        {"type": "optional", "choice": {"marker": "a", "more": True}},
        {"type": "otherwise", "items": [
            {"type": "mandatory",
             "condition": {"op": "and", "args": [
                 {"op": "feature", "code": "VIS", "bit": 0},
                 {"op": "not", "arg": {"op": "command", "name": "Foo", "id": "0x01"}},
             ]}},
            {"type": "optional"},
        ]},
        {"type": "mandatory", "condition": {"op": "condition", "name": "Wi-Fi"}},
        {"type": "mandatory", "condition": {
            "op": "compare", "cmp": "ge",
            "args": [{"op": "revision"}, {"op": "literal", "value": 2}]}},
        {"type": "optional", "condition": {"op": "unsupported", "detail": "status"}},
    ]
    for node in nodes:
        assert conformance_to_json(conformance_from_json(node)) == node
