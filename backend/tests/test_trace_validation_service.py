"""Unit tests for TraceValidationService: id translation, DFA walk and gateway annotations."""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Tuple

import pytest

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.features.formal_analysis.dfa.dfa_builder import DFA
from app.features.formal_analysis.services.analysis_service import FormalAnalysisService
from app.features.formal_analysis.services.trace_validation_service import (
    TraceRequestError,
    TraceValidationService,
    parse_trace_request,
)
from app.features.processes.bpmn_importer import BpmnImporter
from app.features.processes.intermediate_model.id_normalizer import symbolize_node_ids
from app.features.processes.intermediate_model.models import ProcessGraph
from tests.test_bpmn_import import SEQUENTIAL, XOR_PROCESS, definitions, flow, process

service = TraceValidationService()

PARALLEL = definitions(
    process(
        """
        <bpmn:startEvent id="S"/><bpmn:parallelGateway id="Split"/>
        <bpmn:task id="A"/><bpmn:task id="B"/><bpmn:parallelGateway id="Join"/><bpmn:endEvent id="E"/>
        """
        + flow("f0", "S", "Split")
        + flow("f1", "Split", "A")
        + flow("f2", "Split", "B")
        + flow("f3", "A", "Join")
        + flow("f4", "B", "Join")
        + flow("f5", "Join", "E")
    )
)

# Two chained exclusive gateways between the task and the end events.
CHAINED_XOR = definitions(
    process(
        """
        <bpmn:startEvent id="S"/><bpmn:task id="T"/>
        <bpmn:exclusiveGateway id="G1"/><bpmn:exclusiveGateway id="G2"/>
        <bpmn:endEvent id="E1"/><bpmn:endEvent id="E2"/>
        """
        + flow("f0", "S", "T")
        + flow("f1", "T", "G1")
        + flow("f2", "G1", "G2")
        + flow("f3", "G1", "E1")
        + flow("f4", "G2", "E2")
    )
)

# Same chain, but E1 is reachable through G1 directly and through G1 -> G2: two gateway-only paths.
AMBIGUOUS_XOR = CHAINED_XOR.replace(
    "</bpmn:process>", flow("f5", "G2", "E1") + "</bpmn:process>"
)


def build(xml: str) -> Tuple[ProcessGraph, DFA, Dict[str, str]]:
    result = BpmnImporter().import_xml(xml)
    assert result.analysis_supported, [d.to_dict() for d in result.diagnostics]
    graph, bpmn_node_ids = symbolize_node_ids(result.process)
    return graph, FormalAnalysisService().analyze(graph).dfa, bpmn_node_ids


def via(validation: Dict[str, Any]) -> List[List[str]]:
    return [step["via_gateways"] for step in validation["steps"]]


def test_bpmn_trace_is_translated_through_the_inverse_node_map() -> None:
    mapping = {"start_1": "Start", "task_1": "Task_A", "end_1": "End"}

    assert service.translate_bpmn_trace(["Start", "Task_A", "End"], mapping) == ["start_1", "task_1", "end_1"]


def test_unknown_bpmn_id_stays_raw_at_its_position() -> None:
    mapping = {"start_1": "Start", "task_1": "Task_A"}

    assert service.translate_bpmn_trace(["Start", "Ghost", "Task_A"], mapping) == ["start_1", "Ghost", "task_1"]


def test_accepted_sequential_trace_has_no_gateways_on_its_steps() -> None:
    graph, dfa, _ = build(SEQUENTIAL)

    validation = service.validate(graph, dfa, ["start_1", "task_1", "end_1"])

    assert validation["accepted"] is True
    assert validation["trace"] == ["start_1", "task_1", "end_1"]
    assert validation["consumed"] == 3 and validation["rejected_at"] is None and validation["rejection_reason"] is None
    assert via(validation) == [[], [], []]
    assert list(validation) == [
        "accepted",
        "trace",
        "steps",
        "consumed",
        "final_state",
        "rejected_at",
        "rejection_reason",
        "expected_symbols",
    ]
    assert list(validation["steps"][0]) == ["index", "symbol", "from_state", "to_state", "via_gateways"]


def test_xor_branch_reports_the_decision_gateway_crossed() -> None:
    graph, dfa, _ = build(XOR_PROCESS)

    validation = service.validate(graph, dfa, ["start_1", "task_1", "end_1"])

    assert validation["accepted"] is True
    assert via(validation) == [[], ["decision_1"], []]


def test_mixed_xor_route_is_rejected_with_no_transition_and_expected_symbols() -> None:
    graph, dfa, _ = build(XOR_PROCESS)

    validation = service.validate(graph, dfa, ["start_1", "task_1", "end_2"])

    assert validation["accepted"] is False
    assert (validation["rejection_reason"], validation["rejected_at"], validation["consumed"]) == ("NO_TRANSITION", 2, 2)
    assert validation["expected_symbols"] == ["end_1"]
    assert via(validation) == [[], ["decision_1"]]


def test_gateway_symbol_in_the_trace_is_an_unknown_symbol() -> None:
    graph, dfa, _ = build(XOR_PROCESS)

    validation = service.validate(graph, dfa, ["start_1", "decision_1", "task_1", "end_1"])

    assert validation["rejection_reason"] == "UNKNOWN_SYMBOL" and validation["rejected_at"] == 1
    assert validation["trace"] == ["start_1", "decision_1", "task_1", "end_1"]
    assert via(validation) == [[]]


def test_parallel_split_and_join_are_reported_on_the_steps_around_them() -> None:
    graph, dfa, _ = build(PARALLEL)

    validation = service.validate(graph, dfa, ["start_1", "task_1", "task_2", "end_1"])

    assert validation["accepted"] is True
    assert via(validation) == [[], ["parallel_1"], ["parallel_1"], ["parallel_2"]]


def test_every_gateway_on_the_gateway_only_path_is_included_and_sorted() -> None:
    graph, dfa, _ = build(CHAINED_XOR)

    short = service.validate(graph, dfa, ["start_1", "task_1", "end_1"])
    assert short["accepted"] is True
    assert via(short) == [[], [], ["decision_1"]]

    longer = service.validate(graph, dfa, ["start_1", "task_1", "end_2"])
    assert longer["accepted"] is True
    assert via(longer) == [[], [], ["decision_1", "decision_2"]]


def test_ambiguous_gateway_paths_report_every_gateway_on_them() -> None:
    graph, dfa, _ = build(AMBIGUOUS_XOR)

    validation = service.validate(graph, dfa, ["start_1", "task_1", "end_1"])

    assert validation["accepted"] is True
    assert via(validation) == [[], [], ["decision_1", "decision_2"]]


def test_empty_trace_is_rejected_from_the_start_state() -> None:
    graph, dfa, _ = build(SEQUENTIAL)

    validation = service.validate(graph, dfa, [])

    assert validation["accepted"] is False and validation["trace"] == [] and validation["steps"] == []
    assert (validation["consumed"], validation["final_state"], validation["rejected_at"]) == (0, dfa.start_state, None)
    assert validation["rejection_reason"] == "NOT_ACCEPTING_STATE"
    assert validation["expected_symbols"] == ["start_1"]


def test_validate_bpmn_trace_expresses_the_trace_in_symbols() -> None:
    graph, dfa, mapping = build(XOR_PROCESS)

    validation = service.validate_bpmn_trace(graph, dfa, mapping, ["Start", "Task_Yes", "End_Yes"])
    assert validation["accepted"] is True and validation["trace"] == ["start_1", "task_1", "end_1"]

    unknown = service.validate_bpmn_trace(graph, dfa, mapping, ["Start", "Nope"])
    assert unknown["trace"] == ["start_1", "Nope"]
    assert (unknown["rejection_reason"], unknown["rejected_at"]) == ("UNKNOWN_SYMBOL", 1)

    gateway = service.validate_bpmn_trace(graph, dfa, mapping, ["Start", "Gw", "Task_Yes", "End_Yes"])
    assert (gateway["rejection_reason"], gateway["rejected_at"]) == ("UNKNOWN_SYMBOL", 1)
    assert gateway["trace"] == ["start_1", "decision_1", "task_1", "end_1"]


def test_parse_trace_request_accepts_exactly_one_json_array_of_strings() -> None:
    assert parse_trace_request('["a", "b"]', None) == (["a", "b"], False)
    assert parse_trace_request(None, '["X"]') == (["X"], True)
    assert parse_trace_request("[]", None) == ([], False)


@pytest.mark.parametrize(
    "trace, bpmn_trace",
    [
        (None, None),
        ('["a"]', '["b"]'),
        ("not json", None),
        (None, '{"a": 1}'),
        ('["a", 1]', None),
        ('"a"', None),
    ],
)
def test_parse_trace_request_rejects_invalid_input(trace: Any, bpmn_trace: Any) -> None:
    with pytest.raises(TraceRequestError) as error:
        parse_trace_request(trace, bpmn_trace)
    assert str(error.value)
