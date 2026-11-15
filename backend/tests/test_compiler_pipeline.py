"""Comprehensive test suite for the BPMN -> FlowSpec -> Formal Automata -> Ruby on Rails Compiler."""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys

import pytest
from fastapi import UploadFile

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
from app.features.processes.router import compile_bpmn_process, simulate_bpmn_process
from app.main import app

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

    user_task = graph.nodes["Activity_1aczp5w"]
    assert user_task.node_type.value == "user_task"
    user_form_fields = camunda.form_fields(user_task.extensions)
    assert len(user_form_fields) == 1
    assert user_form_fields[0].id == "visita"
    assert user_form_fields[0].field_type == "boolean"

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

    call_node = graph.nodes["Activity_193y6v1"]
    assert call_node.node_type.value == "call_activity"
    assert call_node.called_element == "realizarVisitaTecnica"

    brule_node = graph.nodes["Activity_1ll5x9g"]
    assert brule_node.node_type.value == "business_rule_task"
    assert camunda.decision_ref(brule_node.extensions) == "clasificarPresupuesto"
    assert camunda.result_variable(brule_node.extensions) == "valor"

    formal_service = FormalAnalysisService()
    report = formal_service.analyze(graph)

    assert report.is_valid_workflow is True
    assert len(report.unreachable_nodes) == 0
    assert len(report.deadlocks) == 0
    assert len(report.infinite_loops) == 0
    assert len(report.valid_loops) >= 1
    assert len(report.nfa_summary["flag_regions"]) == 1
    flag_region = report.nfa_summary["flag_regions"][0]
    assert flag_region["split_id"] == "Gateway_1b3ega7"
    assert flag_region["join_id"] == "Gateway_0423gd3"
    assert flag_region["target_masks"] == ["11"]

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

    invalid_flowspec = (
        'process "Test Type Error" as testProc\n'
        '  start "Start" as Start_1\n'
        '    next is Task_1\n'
        '  user task "Form Task" as Task_1\n'
        '    ask boolean visita labeled "Visita realizada"\n'
        '    next is Gw_1\n'
        '  decision "Check" as Gw_1\n'
        '    if visita < 100 go to End_1\n'
        '    otherwise go to End_Ghost\n'
        '  end "End" as End_1\n'
    )
    ast = parser.parse(invalid_flowspec)
    sem = analyzer.analyze(ast)

    assert sem.valid is False
    error_types = {e["type"] for e in sem.errors}
    assert "TYPE_MISMATCH" in error_types
    assert "UNDECLARED_NODE_REFERENCE" in error_types


def test_flowspec_strict_indentation_errors() -> None:
    parser = FlowSpecParser()

    tab_indented = (
        'process "Tab Error" as tabProc\n'
        '\tstart "Start" as Start_1\n'
    )
    with pytest.raises(FlowSpecLexicalError):
        parser.parse(tab_indented)

    inconsistent_dedent = (
        'process "Dedent Error" as dedentProc\n'
        '  user task "Task" as Task_1\n'
        '    ask boolean ok labeled "OK"\n'
        '   next is End_1\n'
        '  end "End" as End_1\n'
    )
    with pytest.raises(FlowSpecLexicalError):
        parser.parse(inconsistent_dedent)


def test_fastapi_endpoints_compile_and_simulate() -> None:
    with open(VISITA_BPMN_PATH, "rb") as f:
        visita_bytes = f.read()

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
    assert "app/forms/validar_visita_form.rb" in data["generated_ruby"]["files"]
    assert "app/jobs/actualizar_estado_del_ticket_de_visita_en_fsm_http_job.rb" in data["generated_ruby"]["files"]
    workflow_rb = data["generated_ruby"]["files"]["app/workflows/realizar_visita_tecnica_workflow.rb"]
    assert "when :task_1" in workflow_rb
    assert "def execute_task1" in workflow_rb
    assert "Activity_1aczp5w" not in workflow_rb
    assert "Activity_1aczp5w" not in data["flowspec"]["code"]

    upload_sim_false = UploadFile(filename="realizarVisitaTecnica.bpmn", file=io.BytesIO(visita_bytes))
    sim_resp_false = simulate_bpmn_process(
        file=upload_sim_false,
        flowspec_code=None,
        input_data=json.dumps({"visita": False}),
    )
    sim_false_data = sim_resp_false["simulation"]
    assert sim_false_data["completed"] is True
    assert sim_false_data["accepted_by_dfa"] is True
    assert sim_false_data["visited_nodes"][-1] == "end_1"

    upload_sim_true = UploadFile(filename="realizarVisitaTecnica.bpmn", file=io.BytesIO(visita_bytes))
    sim_resp_true = simulate_bpmn_process(
        file=upload_sim_true,
        flowspec_code=None,
        input_data=json.dumps({"visita": True, "TicketIdVisita": "TCK-999"}),
    )
    sim_true_data = sim_resp_true["simulation"]
    assert sim_true_data["completed"] is True
    assert sim_true_data["accepted_by_dfa"] is True
    assert sim_true_data["visited_nodes"][-1] == "end_2"
    assert len(sim_true_data["http_requests_simulated"]) == 1
    assert sim_true_data["http_requests_simulated"][0]["payload"] == {"TicketIdVisita": "TCK-999"}

    http_job_rb = data["generated_ruby"]["files"]["app/jobs/actualizar_estado_del_ticket_de_visita_en_fsm_http_job.rb"]
    assert 'ENV.fetch("ACTUALIZAR_ESTADO_DEL_TICKET_DE_VISITA_EN_FSM_HTTP_JOB_URL"' in http_job_rb
    assert "http.open_timeout = OPEN_TIMEOUT" in http_job_rb
    assert "http.read_timeout = READ_TIMEOUT" in http_job_rb
    assert "sidekiq_options queue: :default, retry: 3" in http_job_rb
    assert "Jobs::ActualizarEstadoDelTicketDeVisitaEnFsmHttpJob.perform_async" in workflow_rb
    assert "@enqueued_jobs <<" in workflow_rb
    assert 'ENV.fetch("REDIS_URL"' in data["generated_ruby"]["files"]["config/initializers/sidekiq.rb"]
    assert ".env.example" in data["generated_ruby"]["files"]


def test_http_service_task_with_downstream_dependency_stays_synchronous() -> None:
    flowspec = (
        'process "HTTP Dependent" as httpDep\n'
        '  start "Inicio" as start_1\n'
        '    next is task_1\n'
        '  service task "Consultar API" as task_1\n'
        '    http call\n'
        '      method "GET"\n'
        '      url "http://localhost:9095/status"\n'
        '      save response as api_status\n'
        '    next is decision_1\n'
        '  decision "Validar estado" as decision_1\n'
        '    if api_status is "OK" go to end_1\n'
        '    otherwise go to end_2\n'
        '  end "Aceptado" as end_1\n'
        '  end "Rechazado" as end_2\n'
    )
    parser = FlowSpecParser()
    analyzer = FlowSpecSemanticAnalyzer()
    generator = RubyCodeGenerator()

    ast = parser.parse(flowspec)
    sem = analyzer.analyze(ast)
    assert sem.valid is True

    ruby_out = generator.generate(ast=ast, variable_symbols=sem.variable_symbols)
    assert "Jobs::ConsultarApiHttpJob.new.perform(@context)" in ruby_out.workflow_code
    assert "perform_async" not in ruby_out.workflow_code

