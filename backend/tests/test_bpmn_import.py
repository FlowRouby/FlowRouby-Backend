"""BPMN importer tests: IR contents, diagnostics and the Camunda compatibility layer.

Fixtures are small inline BPMN documents so each test shows exactly what is being imported.
"""

from __future__ import annotations

import io
import os
import sys
from typing import List, Optional

import pytest
from fastapi import HTTPException, UploadFile

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.features.flowspec.ast import camunda_extensions as camunda
from app.features.formal_analysis.services.analysis_service import FormalAnalysisService
from app.features.processes.bpmn_importer import BpmnImporter
from app.features.processes.intermediate_model import (
    DiagnosticCode,
    GatewayDirection,
    ImportResult,
    NodeType,
    Severity,
    SupportLevel,
    UnsupportedNode,
)
from app.features.processes.services.process_service import ProcessImportService
from app.features.processes.router import compile_bpmn_process, simulate_bpmn_process

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
CAMUNDA_NS = "http://camunda.org/schema/1.0/bpmn"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"


def definitions(body: str, extra_ns: str = "") -> str:
    """Wraps elements in a prefixed ``bpmn:definitions`` document."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" xmlns:xsi="{XSI_NS}" '
        f'xmlns:camunda="{CAMUNDA_NS}" {extra_ns} id="Defs">\n{body}\n</bpmn:definitions>'
    )


def process(body: str, process_id: str = "P") -> str:
    return f'<bpmn:process id="{process_id}" name="Proc {process_id}" isExecutable="true">\n{body}\n</bpmn:process>'


def flow(flow_id: str, source: str, target: str, inner: str = "") -> str:
    return f'<bpmn:sequenceFlow id="{flow_id}" sourceRef="{source}" targetRef="{target}">{inner}</bpmn:sequenceFlow>'


SEQUENTIAL = definitions(
    process(
        """
        <bpmn:startEvent id="Start" name="Begin"/>
        <bpmn:task id="Task_A" name="Register request"/>
        <bpmn:endEvent id="End" name="Done"/>
        """
        + flow("f1", "Start", "Task_A")
        + flow("f2", "Task_A", "End")
    )
)

XOR_PROCESS = definitions(
    process(
        """
        <bpmn:startEvent id="Start"/>
        <bpmn:exclusiveGateway id="Gw" name="Approved?" default="f_no"/>
        <bpmn:userTask id="Task_Yes" name="Ship"/>
        <bpmn:userTask id="Task_No" name="Reject"/>
        <bpmn:endEvent id="End_Yes"/>
        <bpmn:endEvent id="End_No"/>
        """
        + flow("f0", "Start", "Gw")
        + flow(
            "f_yes",
            "Gw",
            "Task_Yes",
            '<bpmn:conditionExpression xsi:type="bpmn:tFormalExpression" language="juel">${approved == true}</bpmn:conditionExpression>',
        )
        + flow("f_no", "Gw", "Task_No")
        + flow("f3", "Task_Yes", "End_Yes")
        + flow("f4", "Task_No", "End_No")
    )
)


def imported(xml: str) -> ImportResult:
    return BpmnImporter().import_xml(xml)


def codes(result: ImportResult, severity: Optional[Severity] = None) -> List[str]:
    return [d.code.value for d in result.diagnostics if severity is None or d.severity is severity]


def one_process(xml: str):
    result = imported(xml)
    assert not result.has_errors, [d.to_dict() for d in result.errors]
    assert result.process is not None
    return result.process




def test_sequential_process_keeps_ids_names_and_connections() -> None:
    result = imported(SEQUENTIAL)
    graph = result.process

    assert result.analysis_supported is True
    assert result.diagnostics == []
    assert graph.process_id == "P" and graph.name == "Proc P" and graph.is_executable is True
    assert list(graph.nodes) == ["Start", "Task_A", "End"]
    assert [n.name for n in graph.nodes.values()] == ["Begin", "Register request", "Done"]
    assert [n.node_type for n in graph.nodes.values()] == [NodeType.START_EVENT, NodeType.TASK, NodeType.END_EVENT]
    assert [n.bpmn_type for n in graph.nodes.values()] == ["startEvent", "task", "endEvent"]
    assert (graph.edges["f1"].source_ref, graph.edges["f1"].target_ref) == ("Start", "Task_A")
    assert (graph.edges["f2"].source_ref, graph.edges["f2"].target_ref) == ("Task_A", "End")
    assert graph.nodes["Task_A"].incoming_flows == ["f1"] and graph.nodes["Task_A"].outgoing_flows == ["f2"]


def test_missing_name_stays_none_instead_of_defaulting_to_the_id() -> None:
    graph = one_process(XOR_PROCESS)
    assert graph.nodes["Start"].name is None
    assert graph.nodes["Gw"].name == "Approved?"


def test_two_tasks_keep_their_order_and_distinct_types() -> None:
    graph = one_process(
        definitions(
            process(
                """
                <bpmn:startEvent id="S"/><bpmn:userTask id="U" name="Fill form"/>
                <bpmn:serviceTask id="V" name="Call API"/><bpmn:endEvent id="E"/>
                """
                + flow("a", "S", "U")
                + flow("b", "U", "V")
                + flow("c", "V", "E")
            )
        )
    )
    assert [e.target_ref for e in graph.get_outgoing_edges("U")] == ["V"]
    assert graph.nodes["U"].node_type is NodeType.USER_TASK
    assert graph.nodes["V"].node_type is NodeType.SERVICE_TASK


def test_xor_gateway_keeps_raw_conditions_and_default_flow() -> None:
    graph = one_process(XOR_PROCESS)
    gateway = graph.nodes["Gw"]

    assert gateway.node_type is NodeType.EXCLUSIVE_GATEWAY
    assert gateway.direction is GatewayDirection.DIVERGING
    assert gateway.default_flow_id == "f_no"
    yes_flow = graph.edges["f_yes"]
    assert yes_flow.condition.text == "${approved == true}"
    assert yes_flow.condition.language == "juel"
    assert yes_flow.condition.xsi_type == "bpmn:tFormalExpression"
    assert yes_flow.is_default is False
    assert graph.edges["f_no"].is_default is True and graph.edges["f_no"].condition is None
    assert len(graph.end_nodes) == 2


def test_unconditional_branch_is_not_silently_promoted_to_default() -> None:
    xml = definitions(
        process(
            """
            <bpmn:startEvent id="S"/><bpmn:exclusiveGateway id="G"/>
            <bpmn:task id="A"/><bpmn:task id="B"/><bpmn:endEvent id="E"/>
            """
            + flow("f0", "S", "G")
            + flow("f1", "G", "A", "<bpmn:conditionExpression>${x}</bpmn:conditionExpression>")
            + flow("f2", "G", "B")
            + flow("f3", "A", "E")
            + flow("f4", "B", "E")
        )
    )
    result = imported(xml)
    assert result.process.edges["f2"].is_default is False
    warning = [d for d in result.diagnostics if d.code is DiagnosticCode.XOR_FLOW_WITHOUT_CONDITION_OR_DEFAULT]
    assert [(d.element_id, d.severity, d.blocks_analysis) for d in warning] == [("f2", Severity.WARNING, False)]


def test_loop_is_imported_and_analyzed_as_a_valid_loop() -> None:
    xml = definitions(
        process(
            """
            <bpmn:startEvent id="S"/><bpmn:task id="Try" name="Try payment"/>
            <bpmn:exclusiveGateway id="Ok" default="retry"/><bpmn:endEvent id="E"/>
            """
            + flow("f0", "S", "Try")
            + flow("f1", "Try", "Ok")
            + flow("done", "Ok", "E", "<bpmn:conditionExpression>${paid}</bpmn:conditionExpression>")
            + flow("retry", "Ok", "Try")
        )
    )
    result = imported(xml)
    graph = result.process
    assert [e.id for e in graph.get_incoming_edges("Try")] == ["f0", "retry"]
    assert graph.edges["retry"].source_ref == "Ok" and graph.edges["retry"].target_ref == "Try"
    report = FormalAnalysisService().analyze(graph)
    assert report.valid_loops and not report.infinite_loops


def test_parallel_gateways_are_supported_and_directions_are_derived() -> None:
    xml = definitions(
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
    result = imported(xml)
    graph = result.process
    assert result.analysis_supported is True
    assert graph.nodes["Split"].node_type is NodeType.PARALLEL_GATEWAY
    assert graph.nodes["Split"].direction is GatewayDirection.DIVERGING
    assert graph.nodes["Join"].direction is GatewayDirection.CONVERGING
    assert len(FormalAnalysisService().analyze(graph).nfa_summary["flag_regions"]) == 1


def test_standard_script_and_call_activity_data_stay_in_the_ir() -> None:
    xml = definitions(
        process(
            """
            <bpmn:startEvent id="S"/>
            <bpmn:scriptTask id="Sc" scriptFormat="javascript"><bpmn:script>var a = 1;</bpmn:script></bpmn:scriptTask>
            <bpmn:callActivity id="Ca" calledElement="otherProcess"/><bpmn:endEvent id="E"/>
            """
            + flow("f1", "S", "Sc")
            + flow("f2", "Sc", "Ca")
            + flow("f3", "Ca", "E")
        )
    )
    result = imported(xml)
    graph = result.process
    assert (graph.nodes["Sc"].script_format, graph.nodes["Sc"].script) == ("javascript", "var a = 1;")
    assert graph.nodes["Ca"].called_element == "otherProcess"
    assert graph.nodes["Ca"].support is SupportLevel.PRESERVED
    preserved = [d for d in result.diagnostics if d.code is DiagnosticCode.PRESERVED_NOT_ANALYZABLE]
    assert [(d.element_id, d.blocks_analysis) for d in preserved] == [("Ca", False)]


def test_lanes_including_child_lane_sets_are_preserved() -> None:
    xml = definitions(
        process(
            """
            <bpmn:laneSet id="LS"><bpmn:lane id="L1" name="Ops">
              <bpmn:flowNodeRef>S</bpmn:flowNodeRef><bpmn:flowNodeRef>T</bpmn:flowNodeRef>
              <bpmn:childLaneSet id="CLS"><bpmn:lane id="L1a" name="Night shift"><bpmn:flowNodeRef>T</bpmn:flowNodeRef></bpmn:lane></bpmn:childLaneSet>
            </bpmn:lane></bpmn:laneSet>
            <bpmn:startEvent id="S"/><bpmn:task id="T"/><bpmn:endEvent id="E"/>
            """
            + flow("f1", "S", "T")
            + flow("f2", "T", "E")
        )
    )
    graph = one_process(xml)
    assert [lane.id for lane in graph.lanes] == ["L1", "L1a"]
    assert graph.lane_sets[0].lanes[0].child_lane_set.lanes[0].name == "Night shift"
    assert graph.lane_of("T").id == "L1a" and graph.lane_of("S").id == "L1" and graph.lane_of("E") is None




def test_default_namespace_and_custom_prefix_import_the_same_process() -> None:
    body = '<startEvent id="S"/><task id="T" name="Work"/><endEvent id="E"/>' + "".join(
        [
            '<sequenceFlow id="f1" sourceRef="S" targetRef="T"/>',
            '<sequenceFlow id="f2" sourceRef="T" targetRef="E"/>',
        ]
    )
    default_ns = f'<definitions xmlns="{BPMN_NS}" id="D"><process id="P">{body}</process></definitions>'
    custom = f'<b:definitions xmlns:b="{BPMN_NS}" id="D"><b:process id="P">' + body.replace("<", "<b:").replace(
        "<b:/", "</b:"
    ) + "</b:process></b:definitions>"

    for xml in (default_ns, custom):
        graph = one_process(xml)
        assert list(graph.nodes) == ["S", "T", "E"]
        assert graph.nodes["T"].name == "Work"
        assert [(e.id, e.source_ref, e.target_ref) for e in graph.edges.values()] == [
            ("f1", "S", "T"),
            ("f2", "T", "E"),
        ]


def test_root_in_another_namespace_is_not_bpmn() -> None:
    result = imported('<definitions xmlns="urn:not-bpmn" id="D"><process id="P"/></definitions>')
    assert codes(result, Severity.ERROR) == ["NOT_BPMN"] and result.document is None
    assert codes(imported("<html><body/></html>")) == ["NOT_BPMN"]




def test_unsupported_element_is_reported_and_kept_without_breaking_the_graph() -> None:
    xml = definitions(
        process(
            """
            <bpmn:startEvent id="S"/>
            <bpmn:intermediateCatchEvent id="Wait" name="Wait 2 days"><bpmn:timerEventDefinition/></bpmn:intermediateCatchEvent>
            <bpmn:endEvent id="E"/>
            """
            + flow("f1", "S", "Wait")
            + flow("f2", "Wait", "E")
        )
    )
    result = imported(xml)
    node = result.process.nodes["Wait"]

    assert isinstance(node, UnsupportedNode)
    assert (node.node_type, node.support, node.bpmn_type, node.name) == (
        NodeType.UNSUPPORTED,
        SupportLevel.UNSUPPORTED,
        "intermediateCatchEvent",
        "Wait 2 days",
    )
    assert node.source.children[0].local_name == "timerEventDefinition"
    assert node.incoming_flows == ["f1"] and node.outgoing_flows == ["f2"]
    unsupported = [d for d in result.diagnostics if d.code is DiagnosticCode.UNSUPPORTED_ELEMENT]
    assert [(d.element_id, d.element_type, d.severity, d.blocks_analysis) for d in unsupported] == [
        ("Wait", "intermediateCatchEvent", Severity.WARNING, True)
    ]
    assert result.analysis_supported is False and result.document is not None


def test_unrecognized_content_is_preserved_and_reported_as_info() -> None:
    xml = definitions(
        process(
            """
            <bpmn:startEvent id="S"/><bpmn:task id="T"><bpmn:ioSpecification id="io"/></bpmn:task>
            <bpmn:endEvent id="E"/><bpmn:textAnnotation id="Note"><bpmn:text>remember</bpmn:text></bpmn:textAnnotation>
            """
            + flow("f1", "S", "T")
            + flow("f2", "T", "E")
        ),
        extra_ns='xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"',
    ).replace("</bpmn:definitions>", '<bpmndi:BPMNDiagram id="Diagram"/></bpmn:definitions>')
    result = imported(xml)
    graph = result.process

    assert [e.local_name for e in graph.nodes["T"].unrecognized] == ["ioSpecification"]
    assert [e.local_name for e in graph.unrecognized] == ["textAnnotation"]
    ignored = {d.element_id: d.severity for d in result.diagnostics if d.code is DiagnosticCode.IGNORED_ELEMENT}
    assert ignored == {"io": Severity.INFO, "Note": Severity.INFO, "Diagram": Severity.INFO}
    assert result.analysis_supported is True


def test_loop_characteristics_block_analysis_but_keep_the_task() -> None:
    xml = definitions(
        process(
            """
            <bpmn:startEvent id="S"/>
            <bpmn:task id="T"><bpmn:multiInstanceLoopCharacteristics/></bpmn:task><bpmn:endEvent id="E"/>
            """
            + flow("f1", "S", "T")
            + flow("f2", "T", "E")
        )
    )
    result = imported(xml)
    assert result.process.nodes["T"].support is SupportLevel.PRESERVED
    assert result.analysis_supported is False
    assert [(d.element_id, d.blocks_analysis) for d in result.diagnostics if d.element_type == "multiInstanceLoopCharacteristics"] == [("T", True)]




def test_extensions_are_keyed_by_namespace_uri_not_by_prefix() -> None:
    xml = (
        '<?xml version="1.0"?>'
        f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" xmlns:cam="{CAMUNDA_NS}" xmlns:v="urn:vendor" id="D">'
        '<bpmn:process id="P"><bpmn:startEvent id="S" v:flag="on"/>'
        '<bpmn:userTask id="U" cam:formKey="k1"><bpmn:extensionElements>'
        '<cam:formData><cam:formField id="visita" type="boolean" label=" Done? "/></cam:formData>'
        '<v:custom level="3">payload<v:inner/></v:custom>'
        "</bpmn:extensionElements></bpmn:userTask>"
        '<bpmn:endEvent id="E"/>'
        '<bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="U"/><bpmn:sequenceFlow id="f2" sourceRef="U" targetRef="E"/>'
        "</bpmn:process></bpmn:definitions>"
    )
    graph = one_process(xml)
    task = graph.nodes["U"]

    assert task.extensions.attributes == {f"{{{CAMUNDA_NS}}}formKey": "k1"}
    assert graph.nodes["S"].extensions.attributes == {"{urn:vendor}flag": "on"}
    custom = task.extensions.find("urn:vendor", "custom")
    assert custom.attributes == {"level": "3"} and custom.text == "payload"
    assert [c.local_name for c in custom.children] == ["inner"]
    assert camunda.form_ref(task.extensions) == "k1"
    fields = camunda.form_fields(task.extensions)
    assert [(f.id, f.field_type, f.label) for f in fields] == [("visita", "boolean", "Done?")]


def test_camunda_adapter_reads_connector_mappings_and_parameters() -> None:
    xml = definitions(
        process(
            """
            <bpmn:startEvent id="S"/>
            <bpmn:serviceTask id="Svc" camunda:class="com.acme.Delegate"><bpmn:extensionElements>
              <camunda:inputOutput><camunda:inputParameter name="a">${b}</camunda:inputParameter></camunda:inputOutput>
              <camunda:connector><camunda:connectorId>http-connector</camunda:connectorId><camunda:inputOutput>
                <camunda:inputParameter name="method">post</camunda:inputParameter>
                <camunda:inputParameter name="url">http://localhost/x</camunda:inputParameter>
                <camunda:inputParameter name="headers"><camunda:map><camunda:entry key="X-Id">7</camunda:entry></camunda:map></camunda:inputParameter>
                <camunda:inputParameter name="payload">{"id": "${TicketId}"}</camunda:inputParameter>
                <camunda:outputParameter name="Resp">${response}</camunda:outputParameter>
              </camunda:inputOutput></camunda:connector>
            </bpmn:extensionElements></bpmn:serviceTask>
            <bpmn:callActivity id="Ca" calledElement="x"><bpmn:extensionElements>
              <camunda:in source="x" target="y"/><camunda:out variables="all"/><camunda:out sourceExpression="${z}" target="w"/>
            </bpmn:extensionElements></bpmn:callActivity>
            <bpmn:endEvent id="E"/>
            """
            + flow("f1", "S", "Svc")
            + flow("f2", "Svc", "Ca")
            + flow("f3", "Ca", "E")
        )
    )
    graph = one_process(xml)
    service, call = graph.nodes["Svc"], graph.nodes["Ca"]

    assert camunda.delegate_class(service.extensions) == "com.acme.Delegate"
    assert camunda.input_output_parameters(service.extensions) == ({"a": "b"}, {})
    connector = camunda.http_connector(service.extensions)
    assert (connector.method, connector.url, connector.headers) == ("POST", "http://localhost/x", {"X-Id": "7"})
    assert connector.payload_variables == {"TicketId": "TicketId"}
    assert connector.output_parameters == {"Resp": "response"}
    in_maps, out_maps = camunda.call_activity_mappings(call.extensions)
    assert [(m.source, m.target) for m in in_maps] == [("x", "y")]
    assert [(m.source, m.target, m.all_variables, m.is_expression) for m in out_maps] == [
        ("all", "all", True, False),
        ("z", "w", False, True),
    ]




def test_malformed_xml_is_reported_as_an_error() -> None:
    result = imported("<bpmn:definitions><bpmn:process>")
    assert codes(result) == ["XML_MALFORMED"] and result.document is None and result.has_errors


def test_dtd_and_entity_declarations_are_rejected() -> None:
    xxe = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY secret SYSTEM "file:///etc/passwd">]>'
        f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" id="&secret;"/>'
    )
    result = imported(xxe)
    assert codes(result) == ["XML_MALFORMED"] and result.document is None
    assert "DTD" in result.diagnostics[0].message


def test_dangling_references_are_all_reported_with_the_offending_element() -> None:
    xml = definitions(
        process(
            """
            <bpmn:laneSet id="LS"><bpmn:lane id="L1"><bpmn:flowNodeRef>Ghost</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>
            <bpmn:startEvent id="S"/><bpmn:endEvent id="E"/>
            """
            + flow("f1", "S", "Missing_Target")
            + flow("f2", "Missing_Source", "E")
        )
    )
    result = imported(xml)
    errors = [(d.code.value, d.element_id, d.element_type) for d in result.errors]
    assert errors == [
        ("INVALID_REFERENCE", "f1", "sequenceFlow"),
        ("INVALID_REFERENCE", "f2", "sequenceFlow"),
        ("INVALID_REFERENCE", "L1", "lane"),
    ]
    assert "Missing_Target" in result.errors[0].message and result.document is None


def test_flow_without_source_or_target_attribute_is_an_error() -> None:
    xml = definitions(
        process('<bpmn:startEvent id="S"/><bpmn:endEvent id="E"/><bpmn:sequenceFlow id="f1" sourceRef="S"/>')
    )
    result = imported(xml)
    assert [(d.code.value, d.element_id) for d in result.errors] == [("MISSING_REF_ATTRIBUTE", "f1")]


def test_missing_ids_are_errors() -> None:
    result = imported(definitions(process('<bpmn:startEvent id="S"/><bpmn:task name="No id"/><bpmn:endEvent id="E"/>')))
    assert [(d.code.value, d.element_type) for d in result.errors] == [("MISSING_ID", "task")]


def test_duplicate_ids_are_reported_even_across_element_kinds() -> None:
    xml = definitions(
        process(
            """
            <bpmn:startEvent id="S"/><bpmn:task id="T"/><bpmn:task id="T"/><bpmn:endEvent id="E"/>
            """
            + flow("S", "S", "T")
            + flow("f2", "T", "E")
        )
    )
    result = imported(xml)
    assert [(d.code.value, d.element_id, d.element_type) for d in result.errors] == [
        ("DUPLICATE_ID", "T", "task"),
        ("DUPLICATE_ID", "S", "sequenceFlow"),
    ]
    assert result.document is None


def test_empty_diagrams_are_reported() -> None:
    assert [d.code.value for d in imported(definitions("")).errors] == ["NO_PROCESS"]
    empty_process = imported(definitions(process("")))
    assert [d.code.value for d in empty_process.errors] == ["NO_START_EVENT", "NO_END_EVENT"]
    assert empty_process.document is None


@pytest.mark.parametrize(
    ("missing", "body"),
    [
        ("NO_START_EVENT", '<bpmn:task id="T"/><bpmn:endEvent id="E"/>' + flow("f", "T", "E")),
        ("NO_END_EVENT", '<bpmn:startEvent id="S"/><bpmn:task id="T"/>' + flow("f", "S", "T")),
    ],
)
def test_missing_start_or_end_is_a_flowrouby_profile_import_error(missing: str, body: str) -> None:
    result = imported(definitions(process(body)))
    assert [d.code.value for d in result.errors] == [missing]
    assert "FlowRouby" in result.errors[0].message and "not a general BPMN rule" in result.errors[0].message
    assert result.document is None


def test_multiple_start_events_import_but_block_analysis() -> None:
    xml = definitions(
        process(
            """
            <bpmn:startEvent id="S1"/><bpmn:startEvent id="S2"/><bpmn:task id="T"/><bpmn:endEvent id="E"/>
            """
            + flow("f1", "S1", "T")
            + flow("f2", "S2", "T")
            + flow("f3", "T", "E")
        )
    )
    result = imported(xml)
    assert result.document is not None and not result.has_errors
    assert [n.id for n in result.process.start_nodes] == ["S1", "S2"]
    assert [(d.code.value, d.severity, d.blocks_analysis) for d in result.analysis_blockers] == [
        ("MULTIPLE_START_EVENTS", Severity.WARNING, True)
    ]
    assert result.analysis_supported is False


def test_multiple_end_events_are_allowed_and_do_not_block_analysis() -> None:
    result = imported(XOR_PROCESS)
    assert [n.id for n in result.process.end_nodes] == ["End_Yes", "End_No"]
    assert result.analysis_blockers == [] and result.analysis_supported is True


def test_multiple_processes_are_all_imported_and_block_analysis() -> None:
    xml = definitions(
        process('<bpmn:startEvent id="S1"/><bpmn:endEvent id="E1"/>' + flow("a", "S1", "E1"), "P1")
        + process('<bpmn:startEvent id="S2"/><bpmn:endEvent id="E2"/>' + flow("b", "S2", "E2"), "P2")
    )
    result = imported(xml)
    assert [p.process_id for p in result.document.processes] == ["P1", "P2"]
    assert result.process is None
    assert [(d.code.value, d.blocks_analysis) for d in result.analysis_blockers] == [("MULTIPLE_PROCESSES", True)]


def test_structural_warnings_do_not_block_analysis() -> None:
    xml = definitions(
        process(
            """
            <bpmn:startEvent id="S"/><bpmn:task id="T"/><bpmn:task id="Orphan"/>
            <bpmn:parallelGateway id="DeadEnd"/><bpmn:endEvent id="E"/>
            """
            + flow("f1", "S", "T")
            + flow("f2", "T", "E")
            + flow("f3", "T", "DeadEnd")
        )
    )
    result = imported(xml)
    found = sorted((d.code.value, d.element_id) for d in result.diagnostics)
    assert found == [("DISCONNECTED_NODE", "Orphan"), ("GATEWAY_WITHOUT_OUTGOING", "DeadEnd")]
    assert all(d.severity is Severity.WARNING and not d.blocks_analysis for d in result.diagnostics)




def test_service_rejects_wrong_file_count_and_extension() -> None:
    service = ProcessImportService()
    two_files = service.import_single_bpmn(SEQUENTIAL, filename="a.bpmn", file_count=2)
    wrong_ext = service.import_single_bpmn(SEQUENTIAL, filename="a.txt", file_count=1)
    for result in (two_files, wrong_ext):
        assert [d.code.value for d in result.errors] == ["INVALID_UPLOAD"] and result.document is None
    assert service.import_single_bpmn(SEQUENTIAL, filename="A.BPMN").document is not None


CAMUNDA_PIPELINE_BPMN = definitions(
    process(
        """
        <bpmn:laneSet id="LS"><bpmn:lane id="L1" name="Technician">
          <bpmn:flowNodeRef>Start</bpmn:flowNodeRef><bpmn:flowNodeRef>Visit</bpmn:flowNodeRef>
        </bpmn:lane></bpmn:laneSet>
        <bpmn:startEvent id="Start" name="Start"/>
        <bpmn:userTask id="Visit" name="Visit customer"><bpmn:extensionElements>
          <camunda:formData><camunda:formField id="visita" label="Visit done" type="boolean"/></camunda:formData>
        </bpmn:extensionElements></bpmn:userTask>
        <bpmn:exclusiveGateway id="Gw" name="Visited?"/>
        <bpmn:serviceTask id="Update" name="Update ticket"><bpmn:extensionElements><camunda:connector>
          <camunda:connectorId>http-connector</camunda:connectorId><camunda:inputOutput>
            <camunda:inputParameter name="method">POST</camunda:inputParameter>
            <camunda:inputParameter name="url">http://localhost:9095/tickets</camunda:inputParameter>
            <camunda:inputParameter name="payload">{"TicketId": "${TicketId}"}</camunda:inputParameter>
            <camunda:outputParameter name="Reply">${response}</camunda:outputParameter>
          </camunda:inputOutput></camunda:connector></bpmn:extensionElements></bpmn:serviceTask>
        <bpmn:endEvent id="Done"/><bpmn:endEvent id="Skipped"/>
        """
        + flow("f1", "Start", "Visit")
        + flow("f2", "Visit", "Gw")
        + flow("f3", "Gw", "Update", "<bpmn:conditionExpression>${visita == true}</bpmn:conditionExpression>")
        + flow("f4", "Gw", "Skipped")
        + flow("f5", "Update", "Done")
    )
)


def _upload(xml: str) -> UploadFile:
    return UploadFile(filename="process.bpmn", file=io.BytesIO(xml.encode("utf-8")))


def test_compile_pipeline_still_generates_flowspec_and_ruby_from_camunda_extensions() -> None:
    data = compile_bpmn_process(file=_upload(CAMUNDA_PIPELINE_BPMN))

    code = data["flowspec"]["code"]
    assert 'lane "Technician"' in code
    assert 'ask boolean visita labeled "Visit done"' in code
    assert "http call" in code and 'url "http://localhost:9095/tickets"' in code
    assert '"TicketId" from TicketId' in code
    assert "if visita is true go to task_2" in code
    assert "otherwise go to end_1" in code
    assert data["metadata"]["lanes"] == ["Technician"]
    assert data["validation"]["valid"] is True
    assert [d["code"] for d in data["validation"]["diagnostics"]] == ["XOR_FLOW_WITHOUT_CONDITION_OR_DEFAULT"]
    assert "app/jobs/update_ticket_http_job.rb" in data["generated_ruby"]["files"]


def test_simulation_runs_on_the_imported_process() -> None:
    sim = simulate_bpmn_process(file=_upload(CAMUNDA_PIPELINE_BPMN), flowspec_code=None, input_data='{"visita": false}')
    assert sim["simulation"]["completed"] is True
    assert sim["simulation"]["visited_nodes"][-1] == "end_1"


WITH_TIMER = definitions(
    process(
        """
        <bpmn:startEvent id="S"/><bpmn:intermediateCatchEvent id="Wait"><bpmn:timerEventDefinition/></bpmn:intermediateCatchEvent>
        <bpmn:endEvent id="E"/>
        """
        + flow("f1", "S", "Wait")
        + flow("f2", "Wait", "E")
    )
)
NO_START = definitions(process('<bpmn:task id="T"/><bpmn:endEvent id="E"/>' + flow("f", "T", "E")))


@pytest.mark.parametrize(
    ("xml", "expected_codes"),
    [(WITH_TIMER, ["UNSUPPORTED_ELEMENT"]), (NO_START, ["NO_START_EVENT"])],
)
def test_compile_refuses_to_analyze_a_process_that_was_not_fully_understood(
    xml: str, expected_codes: List[str]
) -> None:
    with pytest.raises(HTTPException) as caught:
        compile_bpmn_process(file=_upload(xml))
    assert caught.value.status_code == 422
    assert [d["code"] for d in caught.value.detail["diagnostics"]] == expected_codes




def numbered_document(*process_lines: str) -> str:
    """A prefixed document whose process children start on line 4 (one element per line)."""
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" id="Defs">',
            '  <bpmn:process id="P">',
            *process_lines,
            "  </bpmn:process>",
            "</bpmn:definitions>",
        ]
    )


def test_dangling_reference_diagnostic_points_at_the_sequence_flow_line() -> None:
    result = imported(
        numbered_document(
            '    <bpmn:startEvent id="S"/>',
            '    <bpmn:endEvent id="E"/>',
            '    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Ghost"/>',
        )
    )
    assert [(d.code.value, d.element_id, d.line) for d in result.errors] == [("INVALID_REFERENCE", "f1", 6)]
    assert result.errors[0].to_dict()["line"] == 6 and result.errors[0].to_dict()["elementId"] == "f1"


def test_unsupported_element_diagnostic_points_at_its_start_tag_line() -> None:
    result = imported(
        numbered_document(
            '    <bpmn:startEvent id="S"/>',
            "",
            '    <bpmn:subProcess id="Sub" name="Nested">',
            '      <bpmn:task id="Inner"/>',
            "    </bpmn:subProcess>",
            '    <bpmn:endEvent id="E"/>',
            '    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub"/>',
            '    <bpmn:sequenceFlow id="f2" sourceRef="Sub" targetRef="E"/>',
        )
    )
    unsupported = [d for d in result.diagnostics if d.code is DiagnosticCode.UNSUPPORTED_ELEMENT]
    assert [(d.element_id, d.line) for d in unsupported] == [("Sub", 6)]
    assert result.process.nodes["Sub"].source_line == 6
    assert result.process.edges["f2"].source_line == 11


def test_malformed_xml_diagnostic_uses_the_parse_error_line() -> None:
    result = imported("<definitions>\n<process>\n</definitions>")
    assert [(d.code.value, d.line) for d in result.diagnostics] == [("XML_MALFORMED", 3)]


def test_dtd_rejection_reports_the_line_of_the_declaration() -> None:
    result = imported('<?xml version="1.0"?>\n<!DOCTYPE d [<!ENTITY x "y">]>\n<d/>')
    assert [(d.code.value, d.line) for d in result.diagnostics] == [("XML_MALFORMED", 2)]


def test_duplicate_id_diagnostic_points_at_the_second_occurrence() -> None:
    result = imported(
        numbered_document(
            '    <bpmn:startEvent id="S"/>',
            '    <bpmn:task id="T"/>',
            '    <bpmn:task id="T"/>',
            '    <bpmn:endEvent id="E"/>',
        )
    )
    assert [(d.code.value, d.element_id, d.line) for d in result.errors] == [("DUPLICATE_ID", "T", 6)]


def test_profile_and_structure_diagnostics_carry_lines_too() -> None:
    no_end = imported(numbered_document('    <bpmn:startEvent id="S"/>'))
    assert [(d.code.value, d.line) for d in no_end.errors] == [("NO_END_EVENT", 3)]

    two_starts = imported(
        numbered_document(
            '    <bpmn:startEvent id="S1"/>',
            '    <bpmn:startEvent id="S2"/>',
            '    <bpmn:endEvent id="E"/>',
            '    <bpmn:sequenceFlow id="f1" sourceRef="S1" targetRef="E"/>',
            '    <bpmn:sequenceFlow id="f2" sourceRef="S2" targetRef="E"/>',
        )
    )
    assert [(d.code.value, d.line) for d in two_starts.analysis_blockers] == [("MULTIPLE_START_EVENTS", 5)]


def test_unnamed_gateway_in_a_deadlock_is_described_by_its_id() -> None:
    deadlock_xml = definitions(
        process(
            """
            <bpmn:startEvent id="Start_1"/><bpmn:exclusiveGateway id="XOR_Split" default="f2"/>
            <bpmn:userTask id="Task_A"/><bpmn:userTask id="Task_B"/>
            <bpmn:parallelGateway id="AND_Join"/><bpmn:endEvent id="End_1"/>
            """
            + flow("f1", "Start_1", "XOR_Split")
            + flow("f2", "XOR_Split", "Task_A")
            + flow("f3", "XOR_Split", "Task_B", "<bpmn:conditionExpression>${x == 1}</bpmn:conditionExpression>")
            + flow("f4", "Task_A", "AND_Join")
            + flow("f5", "Task_B", "AND_Join")
            + flow("f6", "AND_Join", "End_1")
        )
    )
    graph = one_process(deadlock_xml)
    assert graph.nodes["AND_Join"].name is None

    deadlocks = [d for d in FormalAnalysisService().analyze(graph).deadlocks if d["type"] == "GATEWAY_DEADLOCK"]
    assert [d["node_id"] for d in deadlocks] == ["AND_Join"]
    assert "'AND_Join' (AND_Join)" in deadlocks[0]["message"]
    assert "None" not in deadlocks[0]["message"]
