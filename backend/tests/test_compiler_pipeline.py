"""Comprehensive test suite for the BPMN -> FlowSpec -> Formal Automata -> Ruby on Rails Compiler."""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys

import pytest
from fastapi import UploadFile

# Add backend directory to sys.path
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.features.code_generation.ruby.generator import RubyCodeGenerator
from app.features.flowspec.ast.emitter import FlowSpecEmitter
from app.features.flowspec.lexer.lexer import FlowSpecLexer, FlowSpecLexicalError
from app.features.flowspec.parser.parser import FlowSpecParser, FlowSpecSyntaxError
from app.features.flowspec.semantic_analysis.analyzer import FlowSpecSemanticAnalyzer
from app.features.flowspec.semantic_analysis.simulator import FlowSpecSimulator
from app.features.formal_analysis.services.analysis_service import FormalAnalysisService
from app.features.flowspec.ast import camunda_extensions as camunda
from app.features.processes.bpmn_importer import BpmnImporter
from app.main import app, compile_bpmn_process, compile_flowspec_direct, simulate_bpmn_process

PROCESS_MODELS_DIR = os.path.abspath(os.path.join(BACKEND_DIR, "..", "process_models"))
VISITA_BPMN_PATH = os.path.join(PROCESS_MODELS_DIR, "realizarVisitaTecnica.bpmn")
TEC_FAILURES_BPMN_PATH = os.path.join(PROCESS_MODELS_DIR, "tecFailures.bpmn")


def test_import_realizar_visita_tecnica_bpmn() -> None:
    importer = BpmnImporter()
    graph = importer.import_file(VISITA_BPMN_PATH).process

    assert graph.process_id == "realizarVisitaTecnica"
    assert graph.name == "Realizar Visita Técnica"
    assert graph.participant_name == "Tecnico"
    assert len(graph.start_nodes) == 1
    assert len(graph.end_nodes) == 2

    # Check UserTask with Camunda formData (visita: boolean)
    user_task = graph.nodes["Activity_1aczp5w"]
    assert user_task.node_type.value == "user_task"
    user_form_fields = camunda.form_fields(user_task.extensions)
    assert len(user_form_fields) == 1
    assert user_form_fields[0].id == "visita"
    assert user_form_fields[0].field_type == "boolean"

    # Check ServiceTask with HTTP Connector
    srv_task = graph.nodes["Activity_0lw92ym"]
    assert srv_task.node_type.value == "service_task"
    connector = camunda.http_connector(srv_task.extensions)
    assert connector is not None
    assert connector.method == "POST"
    assert connector.url == "http://localhost:9095/tickets/actualizar"
    assert "TicketIdVisita" in connector.payload_variables
    assert connector.output_parameters.get("RespuestaFSM") == "response"


def test_import_and_formal_analysis_tec_failures_bpmn() -> None:
    importer = BpmnImporter()
    graph = importer.import_file(TEC_FAILURES_BPMN_PATH).process

    assert graph.process_id == "tecFailures"
    assert len(graph.lanes) == 3

    # Verify CallActivity and BusinessRuleTask stub extraction
    call_node = graph.nodes["Activity_193y6v1"]
    assert call_node.node_type.value == "call_activity"
    assert call_node.called_element == "realizarVisitaTecnica"

    brule_node = graph.nodes["Activity_1ll5x9g"]
    assert brule_node.node_type.value == "business_rule_task"
    assert camunda.decision_ref(brule_node.extensions) == "clasificarPresupuesto"
    assert camunda.result_variable(brule_node.extensions) == "valor"

    # Run Formal Analysis (NFA with flag vectors -> DFA -> Regex)
    formal_service = FormalAnalysisService()
    report = formal_service.analyze(graph)

    assert report.is_valid_workflow is True
    assert len(report.unreachable_nodes) == 0
    assert len(report.deadlocks) == 0
    assert len(report.infinite_loops) == 0
    # tecFailures has a valid payment retry loop and a parallel gateway block
    assert len(report.valid_loops) >= 1
    assert len(report.nfa_summary["flag_regions"]) == 1
    flag_region = report.nfa_summary["flag_regions"][0]
    assert flag_region["split_id"] == "Gateway_1b3ega7"
    assert flag_region["join_id"] == "Gateway_0423gd3"
    assert flag_region["target_masks"] == ["11"]

    # Both interleavings of parallel tasks (Activity_1b7qy8d and Activity_066js8m) must be accepted by the DFA
    trace_order_1 = [
        "StartEvent_1",
        "Activity_1bsi5nb",
        "Activity_0lw92ym",
        "Activity_193y6v1",
        "Activity_1ll5x9g",
        "Activity_1b7qy8d",
        "Activity_066js8m",
        "Activity_10hruzy",
        "Activity_1fx2x6z",
        "Activity_0uxesqs",
        "Event_1q1goyy",
    ]
    trace_order_2 = [
        "StartEvent_1",
        "Activity_1bsi5nb",
        "Activity_0lw92ym",
        "Activity_193y6v1",
        "Activity_1ll5x9g",
        "Activity_066js8m",
        "Activity_1b7qy8d",
        "Activity_10hruzy",
        "Activity_1fx2x6z",
        "Activity_0uxesqs",
        "Event_1q1goyy",
    ]
    assert report.dfa.accepts(trace_order_1) is True
    assert report.dfa.accepts(trace_order_2) is True


def test_formal_analysis_detects_xor_to_and_deadlock_and_unreachable() -> None:
    deadlock_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Def_Deadlock">
      <bpmn:process id="deadlockProc" isExecutable="true">
        <bpmn:startEvent id="Start_1" />
        <bpmn:exclusiveGateway id="XOR_Split" default="f2" />
        <bpmn:userTask id="Task_A" />
        <bpmn:userTask id="Task_B" />
        <bpmn:userTask id="Task_Orphan" />
        <bpmn:parallelGateway id="AND_Join" />
        <bpmn:endEvent id="End_1" />
        <bpmn:sequenceFlow id="f1" sourceRef="Start_1" targetRef="XOR_Split" />
        <bpmn:sequenceFlow id="f2" sourceRef="XOR_Split" targetRef="Task_A" />
        <bpmn:sequenceFlow id="f3" sourceRef="XOR_Split" targetRef="Task_B">
          <bpmn:conditionExpression>${x == 1}</bpmn:conditionExpression>
        </bpmn:sequenceFlow>
        <bpmn:sequenceFlow id="f4" sourceRef="Task_A" targetRef="AND_Join" />
        <bpmn:sequenceFlow id="f5" sourceRef="Task_B" targetRef="AND_Join" />
        <bpmn:sequenceFlow id="f6" sourceRef="AND_Join" targetRef="End_1" />
      </bpmn:process>
    </bpmn:definitions>
    """
    graph = BpmnImporter().import_xml(deadlock_xml).process
    report = FormalAnalysisService().analyze(graph)

    assert report.is_valid_workflow is False
    assert "Task_Orphan" in report.unreachable_nodes
    assert any(d["type"] == "GATEWAY_DEADLOCK" for d in report.deadlocks)


def test_flowspec_compiler_and_type_checking() -> None:
    parser = FlowSpecParser()
    analyzer = FlowSpecSemanticAnalyzer()

    invalid_flowspec = """
    process testProc "Test Type Error" {
      start Start_1 -> Task_1;
      user_task Task_1 "Form Task" {
        form_field visita: boolean "Visita realizada";
        -> Gw_1;
      }
      exclusive_gateway Gw_1 "Check" {
        when (visita < 100) -> End_1;
        default -> End_Ghost;
      }
      end End_1;
    }
    """
    ast = parser.parse(invalid_flowspec)
    sem = analyzer.analyze(ast)

    assert sem.valid is False
    error_types = {e["type"] for e in sem.errors}
    assert "TYPE_MISMATCH" in error_types
    assert "UNDECLARED_NODE_REFERENCE" in error_types


def test_fastapi_endpoints_compile_and_simulate() -> None:
    with open(VISITA_BPMN_PATH, "rb") as f:
        visita_bytes = f.read()

    # 1. Test POST /api/v1/processes/compile with realizarVisitaTecnica.bpmn
    upload_compile = UploadFile(filename="realizarVisitaTecnica.bpmn", file=io.BytesIO(visita_bytes))
    data = compile_bpmn_process(file=upload_compile)
    assert data["metadata"]["process_id"] == "realizarVisitaTecnica"
    assert data["validation"]["valid"] is True
    assert "intermediate_model" not in data
    assert "ast" not in data["flowspec"]
    assert "code" in data["flowspec"]
    assert "symbol_table" in data["flowspec"]
    assert "data_contract" in data
    assert "state_subsets" in data["formal_analysis"]["dfa"]
    assert set(data["generated_ruby"].keys()) == {"framework", "files"}
    assert "app/workflows/realizar_visita_tecnica_workflow.rb" in data["generated_ruby"]["files"]
    assert "app/jobs/activity_0lw92ym_http_job.rb" in data["generated_ruby"]["files"]

    # 2. Test POST /api/v1/processes/simulate (when visita == false -> Falla no atendida)
    upload_sim_false = UploadFile(filename="realizarVisitaTecnica.bpmn", file=io.BytesIO(visita_bytes))
    sim_resp_false = simulate_bpmn_process(
        file=upload_sim_false,
        flowspec_code=None,
        input_data=json.dumps({"visita": False}),
    )
    sim_false_data = sim_resp_false["simulation"]
    assert sim_false_data["completed"] is True
    assert sim_false_data["accepted_by_dfa"] is True
    assert sim_false_data["visited_nodes"][-1] == "Event_1ggqko4"

    # 3. Test POST /api/v1/processes/simulate (when visita == true -> HTTP Connector -> Reporte creado)
    upload_sim_true = UploadFile(filename="realizarVisitaTecnica.bpmn", file=io.BytesIO(visita_bytes))
    sim_resp_true = simulate_bpmn_process(
        file=upload_sim_true,
        flowspec_code=None,
        input_data=json.dumps({"visita": True, "TicketIdVisita": "TCK-999"}),
    )
    sim_true_data = sim_resp_true["simulation"]
    assert sim_true_data["completed"] is True
    assert sim_true_data["accepted_by_dfa"] is True
    assert sim_true_data["visited_nodes"][-1] == "Event_1swqw02"
    assert len(sim_true_data["http_requests_simulated"]) == 1
    assert sim_true_data["http_requests_simulated"][0]["payload"] == {"TicketIdVisita": "TCK-999"}

