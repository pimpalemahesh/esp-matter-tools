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
"""The consumer-neutral service facade (driving port for CLI / UI / MCP)."""

import re

import pytest

pytest.importorskip("esp_matter_datamodel")
from pics_tool import service

_ECL = {"spec_version": "1.6", "transport": ["wifi_2g"], "role": "commissionee",
        "endpoints": [{"device_types": ["Extended Color Light"]}]}


def test_discovery():
    assert "1.6" in service.list_versions()
    assert "Extended Color Light" in service.list_device_types("1.6")
    assert "esp_matter" in service.list_targets()


def test_selection_questions_are_human_decisions_only():
    out = service.selection_questions(_ECL)
    assert set(out) == {"summary", "questions"}
    assert out["questions"], "expected optional questions for ECL"
    for q in out["questions"]:
        assert set(q) >= {"id", "tab", "endpoint", "cluster", "code", "question",
                          "suggested", "why", "conformance"}
        assert q["id"] == f"{q['tab']}|{q['code']}"
        assert q["suggested"] in ("yes", "no")
    assert out["summary"]["spec_version"] == "1.6"
    assert out["summary"]["counts"]["to_decide"] == len(out["questions"])


def test_answering_a_question_is_reflected_on_recall():
    out = service.selection_questions(_ECL)
    feat = next(q for q in out["questions"] if re.search(r"\.S\.F[0-9a-f]{2}$", q["code"]))
    selected = {feat["tab"]: [feat["code"]]}          # the human answers YES
    out2 = service.selection_questions(_ECL, selected)
    same = next(q for q in out2["questions"] if q["code"] == feat["code"])
    assert same["suggested"] == "yes"                 # the claim is reflected
    # enabling a feature never drops questions (it may reveal sub-items)
    assert len(out2["questions"]) >= len(out["questions"])


def test_generate_returns_pics_code_and_clean_check():
    gen = service.generate(_ECL)
    assert set(gen) >= {"target", "pics_files", "code", "problems"}
    assert gen["pics_files"] and all(t.strip() for t in gen["pics_files"].values())
    assert "node::create" in gen["code"]["snippet"]
    assert isinstance(gen["problems"], list)
    assert [p for p in gen["problems"] if p.get("severity") != "warning"] == []


def test_generate_threads_optional_answers_into_code():
    # a Color Control feature turned on shows up in the generated code
    q = service.selection_questions(_ECL)["questions"]
    cc = next(x for x in q if x["code"].startswith("CC.S.F"))
    gen = service.generate(_ECL, {cc["tab"]: [cc["code"]]})
    assert "color_control_cluster_1" in gen["code"]["snippet"]


def test_generate_rejects_unknown_target():
    with pytest.raises(ValueError, match="unknown target"):
        service.generate(_ECL, {}, target="nope")
