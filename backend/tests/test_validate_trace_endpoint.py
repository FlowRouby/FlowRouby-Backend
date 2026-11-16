"""Tests for POST /api/v1/processes/validate-trace (membership of a trace in the model's DFA language)."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.main import app
from tests.test_bpmn_import import SEQUENTIAL, WITH_TIMER, XOR_PROCESS, definitions, flow, process
from tests.test_trace_validation_service import PARALLEL

VALIDATE_URL = "/api/v1/processes/validate-trace"
SIMULATE_URL = "/api/v1/processes/simulate"
FRONTEND_ORIGIN = "http://localhost:4200"

client = TestClient(app)

MULTIPLE_STARTS = definitions(
    process(
        """
        <bpmn:startEvent id="S1"/><bpmn:startEvent id="S2"/><bpmn:endEvent id="E"/>
        """
        + flow("a", "S1", "E")
        + flow("b", "S2", "E")
    )
)


def post_validate(xml: str, trace: Optional[List[str]] = None, bpmn_trace: Optional[List[str]] = None):
    data: Dict[str, str] = {}
    if trace is not None:
        data["trace"] = json.dumps(trace)
    if bpmn_trace is not None:
        data["bpmn_trace"] = json.dumps(bpmn_trace)
    return client.post(VALIDATE_URL, files={"file": ("p.bpmn", xml.encode("utf-8"), "application/xml")}, data=data)


def validation_of(response) -> Dict[str, Any]:
    assert response.status_code == 200, response.text
    return response.json()["validation"]


def test_accepted_trace_returns_the_walk_and_the_node_map() -> None:
    response = post_validate(SEQUENTIAL, trace=["start_1", "task_1", "end_1"])
    body = response.json()

    assert response.status_code == 200
    assert set(body) == {"process_id", "bpmn_node_ids", "validation"}
    assert body["process_id"] == "P"
    assert body["bpmn_node_ids"] == {"start_1": "Start", "task_1": "Task_A", "end_1": "End"}
    validation = body["validation"]
    assert validation["accepted"] is True
    assert validation["trace"] == ["start_1", "task_1", "end_1"]
    assert validation["consumed"] == 3 and validation["final_state"] == validation["steps"][-1]["to_state"]
    assert (validation["rejected_at"], validation["rejection_reason"], validation["expected_symbols"]) == (None, None, [])
    assert [(s["index"], s["symbol"]) for s in validation["steps"]] == [(0, "start_1"), (1, "task_1"), (2, "end_1")]
    assert all(set(s) == {"index", "symbol", "from_state", "to_state", "via_gateways"} for s in validation["steps"])


def test_unknown_symbol_is_rejected_at_its_position() -> None:
    validation = validation_of(post_validate(SEQUENTIAL, trace=["start_1", "ghost", "end_1"]))

    assert validation["accepted"] is False
    assert (validation["rejection_reason"], validation["rejected_at"], validation["consumed"]) == ("UNKNOWN_SYMBOL", 1, 1)
    assert validation["expected_symbols"] == ["task_1"]


def test_symbol_without_a_transition_is_no_transition() -> None:
    validation = validation_of(post_validate(SEQUENTIAL, trace=["start_1", "end_1"]))

    assert (validation["accepted"], validation["rejection_reason"], validation["rejected_at"]) == (False, "NO_TRANSITION", 1)
    assert validation["expected_symbols"] == ["task_1"]


def test_incomplete_trace_is_not_accepting_state() -> None:
    validation = validation_of(post_validate(SEQUENTIAL, trace=["start_1", "task_1"]))

    assert (validation["accepted"], validation["rejection_reason"], validation["rejected_at"]) == (False, "NOT_ACCEPTING_STATE", None)
    assert (validation["consumed"], validation["expected_symbols"]) == (2, ["end_1"])


def test_gateway_id_in_bpmn_trace_is_an_unknown_symbol() -> None:
    validation = validation_of(post_validate(XOR_PROCESS, bpmn_trace=["Start", "Gw", "Task_Yes", "End_Yes"]))

    assert (validation["rejection_reason"], validation["rejected_at"]) == ("UNKNOWN_SYMBOL", 1)
    assert validation["trace"] == ["start_1", "decision_1", "task_1", "end_1"]


def test_unknown_bpmn_id_keeps_its_raw_value_in_the_symbol_trace() -> None:
    validation = validation_of(post_validate(SEQUENTIAL, bpmn_trace=["Start", "Nope", "End"]))

    assert (validation["rejection_reason"], validation["rejected_at"]) == ("UNKNOWN_SYMBOL", 1)
    assert validation["trace"] == ["start_1", "Nope", "end_1"]


def test_empty_trace_is_a_valid_request_and_is_rejected() -> None:
    response = post_validate(SEQUENTIAL, trace=[])
    validation = validation_of(response)

    assert validation["accepted"] is False and validation["rejection_reason"] == "NOT_ACCEPTING_STATE"
    assert validation["consumed"] == 0 and validation["steps"] == [] and validation["rejected_at"] is None
    assert validation["expected_symbols"] == ["start_1"]

    empty_bpmn = validation_of(post_validate(SEQUENTIAL, bpmn_trace=[]))
    assert empty_bpmn == validation


def test_trace_and_bpmn_trace_give_the_same_validation() -> None:
    by_symbols = validation_of(post_validate(XOR_PROCESS, trace=["start_1", "task_2", "end_2"]))
    by_bpmn_ids = validation_of(post_validate(XOR_PROCESS, bpmn_trace=["Start", "Task_No", "End_No"]))

    assert by_symbols["accepted"] is True
    assert by_symbols == by_bpmn_ids


def test_both_xor_routes_are_accepted_and_a_mixed_route_is_not() -> None:
    yes_route = validation_of(post_validate(XOR_PROCESS, trace=["start_1", "task_1", "end_1"]))
    no_route = validation_of(post_validate(XOR_PROCESS, trace=["start_1", "task_2", "end_2"]))
    mixed = validation_of(post_validate(XOR_PROCESS, trace=["start_1", "task_1", "end_2"]))

    assert yes_route["accepted"] is True and no_route["accepted"] is True
    assert mixed["accepted"] is False
    assert (mixed["rejection_reason"], mixed["rejected_at"], mixed["expected_symbols"]) == ("NO_TRANSITION", 2, ["end_1"])


def test_steps_report_the_gateways_crossed_for_xor_and_parallel_diagrams() -> None:
    xor = validation_of(post_validate(XOR_PROCESS, trace=["start_1", "task_1", "end_1"]))
    assert [s["via_gateways"] for s in xor["steps"]] == [[], ["decision_1"], []]

    parallel = validation_of(post_validate(PARALLEL, trace=["start_1", "task_1", "task_2", "end_1"]))
    assert parallel["accepted"] is True
    assert [s["via_gateways"] for s in parallel["steps"]] == [[], ["parallel_1"], ["parallel_1"], ["parallel_2"]]


def test_both_trace_fields_answer_422() -> None:
    response = post_validate(SEQUENTIAL, trace=["start_1"], bpmn_trace=["Start"])

    assert response.status_code == 422
    assert "not both" in response.json()["detail"]["message"]


def test_neither_trace_field_answers_422() -> None:
    response = post_validate(SEQUENTIAL)

    assert response.status_code == 422
    assert "message" in response.json()["detail"]


@pytest.mark.parametrize("field", ["trace", "bpmn_trace"])
@pytest.mark.parametrize("raw", ["not json", '{"a": 1}', '["start_1", 2]', '"start_1"', "null"])
def test_malformed_trace_fields_answer_422_with_a_message(field: str, raw: str) -> None:
    response = client.post(
        VALIDATE_URL, files={"file": ("p.bpmn", SEQUENTIAL.encode("utf-8"), "application/xml")}, data={field: raw}
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"]["message"], str)


@pytest.mark.parametrize("xml", [WITH_TIMER, MULTIPLE_STARTS])
def test_non_analyzable_diagram_answers_422_with_blocking_diagnostics(xml: str) -> None:
    response = post_validate(xml, trace=["start_1"])
    detail = response.json()["detail"]

    assert response.status_code == 422
    assert detail["message"] == "The BPMN document was imported but cannot be analyzed yet."
    assert detail["diagnostics"] and all(d["blocksAnalysis"] is True for d in detail["diagnostics"])


def test_non_importable_document_answers_422_with_message_and_diagnostics() -> None:
    response = post_validate("<definitions>\n<process>\n</definitions>", trace=["start_1"])
    detail = response.json()["detail"]

    assert response.status_code == 422
    assert detail["message"] == "The BPMN document could not be imported."
    assert [d["code"] for d in detail["diagnostics"]] == ["XML_MALFORMED"]


def test_missing_file_answers_the_fastapi_validation_error() -> None:
    response = client.post(VALIDATE_URL, data={"trace": "[]"})
    detail = response.json()["detail"]

    assert response.status_code == 422 and isinstance(detail, list) and detail[0]["loc"] == ["body", "file"]


def dfa_trace_from_simulation(xml: str, input_data: Dict[str, Any]) -> List[str]:
    """The DFA trace of a simulation: its step logs without the gateway entries (the ones with selected_targets)."""
    response = client.post(
        SIMULATE_URL, files={"file": ("p.bpmn", xml.encode("utf-8"), "application/xml")}, data={"input_data": json.dumps(input_data)}
    )
    assert response.status_code == 200, response.text
    logs = response.json()["simulation"]["step_logs"]
    return [log["node_id"] for log in logs if "selected_targets" not in log]


@pytest.mark.parametrize(
    "xml, input_data",
    [
        (SEQUENTIAL, {}),
        (XOR_PROCESS, {"approved": True}),
        (XOR_PROCESS, {"approved": False}),
        (PARALLEL, {}),
    ],
    ids=["sequential", "xor-yes", "xor-no", "parallel"],
)
def test_a_simulated_path_is_accepted_by_validate_trace(xml: str, input_data: Dict[str, Any]) -> None:
    trace = dfa_trace_from_simulation(xml, input_data)

    assert trace
    assert validation_of(post_validate(xml, trace=trace))["accepted"] is True


def test_openapi_lists_the_validate_trace_route() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert VALIDATE_URL in paths and "post" in paths[VALIDATE_URL]


def test_preflight_for_validate_trace_is_allowed_from_the_frontend_origin() -> None:
    response = client.options(
        VALIDATE_URL, headers={"Origin": FRONTEND_ORIGIN, "Access-Control-Request-Method": "POST"}
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
