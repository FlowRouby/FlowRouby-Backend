"""Tests for POST /api/v1/processes/import (import only: no analysis, no code generation)."""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.main import app

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
CAMUNDA_NS = "http://camunda.org/schema/1.0/bpmn"
IMPORT_URL = "/api/v1/processes/import"

client = TestClient(app)


def definitions(*lines: str) -> str:
    """A prefixed document with one element per line (line 1 is the XML declaration)."""
    return "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" xmlns:camunda="{CAMUNDA_NS}" id="Defs">',
            *lines,
            "</bpmn:definitions>",
        ]
    )


def post_import(xml: str, filename: str = "diagram.bpmn", field: str = "file"):
    return client.post(IMPORT_URL, files={field: (filename, xml.encode("utf-8"), "application/xml")})


def by_id(items: List[Dict[str, Any]], item_id: str) -> Dict[str, Any]:
    return next(item for item in items if item["id"] == item_id)


SEQUENTIAL = definitions(
    '  <bpmn:process id="P" name="Demo" isExecutable="true">',  # line 3
    '    <bpmn:startEvent id="Start" name="Begin"/>',  # 4
    '    <bpmn:task id="Task_A" name="Register request"/>',  # 5
    '    <bpmn:endEvent id="End" name="Done"/>',  # 6
    '    <bpmn:sequenceFlow id="f1" sourceRef="Start" targetRef="Task_A"/>',  # 7
    '    <bpmn:sequenceFlow id="f2" sourceRef="Task_A" targetRef="End"/>',  # 8
    "  </bpmn:process>",
)


def test_clean_sequential_process_is_imported_with_ids_names_and_flow_refs() -> None:
    response = post_import(SEQUENTIAL)
    body = response.json()

    assert response.status_code == 200
    assert set(body) == {"supported", "diagnostics", "document"}  # nothing was analyzed or generated
    assert body["supported"] is True and body["diagnostics"] == []
    document = body["document"]
    assert (document["definitionsId"], len(document["processes"])) == ("Defs", 1)
    process = document["processes"][0]
    assert (process["id"], process["name"], process["isExecutable"], process["sourceLine"]) == ("P", "Demo", True, 3)
    assert [(n["id"], n["name"], n["bpmnType"], n["nodeType"], n["support"]) for n in process["nodes"]] == [
        ("Start", "Begin", "startEvent", "start_event", "analyzable"),
        ("Task_A", "Register request", "task", "task", "analyzable"),
        ("End", "Done", "endEvent", "end_event", "analyzable"),
    ]
    task = by_id(process["nodes"], "Task_A")
    assert (task["incoming"], task["outgoing"], task["sourceLine"]) == (["f1"], ["f2"], 5)
    assert [(f["id"], f["sourceRef"], f["targetRef"], f["condition"], f["isDefault"], f["sourceLine"]) for f in process["sequenceFlows"]] == [
        ("f1", "Start", "Task_A", None, False, 7),
        ("f2", "Task_A", "End", None, False, 8),
    ]


def test_xor_gateway_keeps_raw_condition_and_default_flow() -> None:
    xml = definitions(
        '  <bpmn:process id="P">',
        '    <bpmn:startEvent id="S"/>',
        '    <bpmn:exclusiveGateway id="Gw" name="Approved?" default="f_no"/>',
        '    <bpmn:endEvent id="Yes"/><bpmn:endEvent id="No"/>',
        '    <bpmn:sequenceFlow id="f0" sourceRef="S" targetRef="Gw"/>',
        f'    <bpmn:sequenceFlow id="f_yes" sourceRef="Gw" targetRef="Yes"><bpmn:conditionExpression xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="bpmn:tFormalExpression" language="juel">${{approved == true}}</bpmn:conditionExpression></bpmn:sequenceFlow>',
        '    <bpmn:sequenceFlow id="f_no" sourceRef="Gw" targetRef="No"/>',
        "  </bpmn:process>",
    )
    body = post_import(xml).json()
    process = body["document"]["processes"][0]
    gateway = by_id(process["nodes"], "Gw")
    yes_flow, no_flow = by_id(process["sequenceFlows"], "f_yes"), by_id(process["sequenceFlows"], "f_no")

    assert body["supported"] is True
    assert (gateway["nodeType"], gateway["defaultFlowId"], gateway["outgoing"]) == (
        "exclusive_gateway",
        "f_no",
        ["f_yes", "f_no"],
    )
    assert yes_flow["condition"] == {"text": "${approved == true}", "language": "juel", "xsiType": "bpmn:tFormalExpression"}
    assert (yes_flow["isDefault"], no_flow["isDefault"], no_flow["condition"]) == (False, True, None)


def test_subprocess_is_imported_but_analysis_is_not_supported() -> None:
    xml = definitions(
        '  <bpmn:process id="P">',  # 3
        '    <bpmn:startEvent id="S"/>',  # 4
        '    <bpmn:subProcess id="Sub" name="Nested">',  # 5
        '      <bpmn:task id="Inner"/>',  # 6
        "    </bpmn:subProcess>",  # 7
        '    <bpmn:endEvent id="E"/>',  # 8
        '    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub"/>',
        '    <bpmn:sequenceFlow id="f2" sourceRef="Sub" targetRef="E"/>',
        "  </bpmn:process>",
    )
    response = post_import(xml)
    body = response.json()

    assert response.status_code == 200 and body["supported"] is False
    assert [(d["code"], d["elementId"], d["elementType"], d["blocksAnalysis"], d["line"]) for d in body["diagnostics"]] == [
        ("UNSUPPORTED_ELEMENT", "Sub", "subProcess", True, 5)
    ]
    sub = by_id(body["document"]["processes"][0]["nodes"], "Sub")
    assert (sub["bpmnType"], sub["nodeType"], sub["support"], sub["name"]) == ("subProcess", "unsupported", "unsupported", "Nested")
    assert (sub["incoming"], sub["outgoing"]) == (["f1"], ["f2"])
    assert [c["localName"] for c in sub["source"]["children"]] == ["task"]  # nested content is not lost
    assert sub["source"]["children"][0]["attributes"] == {"id": "Inner"}


def test_call_activity_is_supported_with_a_non_blocking_warning() -> None:
    xml = definitions(
        '  <bpmn:process id="P">',
        '    <bpmn:startEvent id="S"/><bpmn:callActivity id="Call" calledElement="otherProcess"/><bpmn:endEvent id="E"/>',
        '    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Call"/>',
        '    <bpmn:sequenceFlow id="f2" sourceRef="Call" targetRef="E"/>',
        "  </bpmn:process>",
    )
    body = post_import(xml).json()

    assert body["supported"] is True
    assert [(d["severity"], d["code"], d["elementId"], d["blocksAnalysis"]) for d in body["diagnostics"]] == [
        ("warning", "PRESERVED_NOT_ANALYZABLE", "Call", False)
    ]
    call = by_id(body["document"]["processes"][0]["nodes"], "Call")
    assert (call["nodeType"], call["support"], call["calledElement"]) == ("call_activity", "preserved", "otherProcess")


def test_script_task_standard_fields_and_info_diagnostics_are_returned() -> None:
    xml = definitions(
        '  <bpmn:process id="P">',
        '    <bpmn:startEvent id="S"/>',
        '    <bpmn:scriptTask id="Sc" scriptFormat="javascript"><bpmn:script>var a = 1;</bpmn:script></bpmn:scriptTask>',
        '    <bpmn:endEvent id="E"/>',
        '    <bpmn:textAnnotation id="Note"><bpmn:text>remember</bpmn:text></bpmn:textAnnotation>',
        '    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sc"/>',
        '    <bpmn:sequenceFlow id="f2" sourceRef="Sc" targetRef="E"/>',
        "  </bpmn:process>",
    )
    body = post_import(xml).json()
    process = body["document"]["processes"][0]

    script = by_id(process["nodes"], "Sc")
    assert (script["scriptFormat"], script["script"]) == ("javascript", "var a = 1;")
    assert [(d["severity"], d["code"], d["elementId"]) for d in body["diagnostics"]] == [("info", "IGNORED_ELEMENT", "Note")]
    assert [e["localName"] for e in process["unrecognized"]] == ["textAnnotation"]
    assert body["supported"] is True


def test_lanes_and_participant_are_returned() -> None:
    xml = definitions(
        f'  <bpmn:collaboration id="C"><bpmn:participant id="Part" name="Technician" processRef="P"/></bpmn:collaboration>',
        '  <bpmn:process id="P">',
        '    <bpmn:laneSet id="LS"><bpmn:lane id="L1" name="Ops"><bpmn:flowNodeRef>S</bpmn:flowNodeRef><bpmn:flowNodeRef>E</bpmn:flowNodeRef></bpmn:lane></bpmn:laneSet>',
        '    <bpmn:startEvent id="S"/><bpmn:endEvent id="E"/>',
        '    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="E"/>',
        "  </bpmn:process>",
    )
    process = post_import(xml).json()["document"]["processes"][0]

    assert process["participant"] == {"id": "Part", "name": "Technician", "processRef": "P", "sourceLine": 3}
    lane = process["laneSets"][0]["lanes"][0]
    assert (lane["id"], lane["name"], lane["flowNodeRefs"], lane["childLaneSet"]) == ("L1", "Ops", ["S", "E"], None)


def test_camunda_extensions_are_preserved_under_their_namespace_uri() -> None:
    xml = definitions(
        '  <bpmn:process id="P">',
        '    <bpmn:startEvent id="S"/>',
        '    <bpmn:userTask id="U" camunda:formKey="form1"><bpmn:extensionElements>'
        '<camunda:formData><camunda:formField id="visita" type="boolean" label="Visit done"/></camunda:formData>'
        "</bpmn:extensionElements></bpmn:userTask>",
        '    <bpmn:endEvent id="E"/>',
        '    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="U"/>',
        '    <bpmn:sequenceFlow id="f2" sourceRef="U" targetRef="E"/>',
        "  </bpmn:process>",
    )
    task = by_id(post_import(xml).json()["document"]["processes"][0]["nodes"], "U")

    assert task["extensions"]["attributes"] == {f"{{{CAMUNDA_NS}}}formKey": "form1"}
    form_data = task["extensions"]["elements"][0]
    assert (form_data["namespaceUri"], form_data["localName"]) == (CAMUNDA_NS, "formData")
    form_field = form_data["children"][0]
    assert (form_field["namespaceUri"], form_field["localName"]) == (CAMUNDA_NS, "formField")
    assert form_field["attributes"] == {"id": "visita", "type": "boolean", "label": "Visit done"}


def test_prefixed_and_default_namespace_documents_are_identical() -> None:
    body = ['<{p}startEvent id="S"/>', '<{p}task id="T" name="Work"/>', '<{p}endEvent id="E"/>',
            '<{p}sequenceFlow id="f1" sourceRef="S" targetRef="T"/>', '<{p}sequenceFlow id="f2" sourceRef="T" targetRef="E"/>']
    prefixed = "\n".join(
        [f'<bpmn:definitions xmlns:bpmn="{BPMN_NS}" id="D">', '<bpmn:process id="P">']
        + [line.format(p="bpmn:") for line in body]
        + ["</bpmn:process>", "</bpmn:definitions>"]
    )
    default = "\n".join(
        [f'<definitions xmlns="{BPMN_NS}" id="D">', '<process id="P">']
        + [line.format(p="") for line in body]
        + ["</process>", "</definitions>"]
    )
    prefixed_body, default_body = post_import(prefixed).json(), post_import(default).json()

    assert prefixed_body == default_body
    assert [n["id"] for n in prefixed_body["document"]["processes"][0]["nodes"]] == ["S", "T", "E"]


def test_multiple_processes_are_all_returned_and_analysis_is_not_supported() -> None:
    xml = definitions(
        '  <bpmn:process id="P1"><bpmn:startEvent id="S1"/><bpmn:endEvent id="E1"/><bpmn:sequenceFlow id="a" sourceRef="S1" targetRef="E1"/></bpmn:process>',
        '  <bpmn:process id="P2"><bpmn:startEvent id="S2"/><bpmn:endEvent id="E2"/><bpmn:sequenceFlow id="b" sourceRef="S2" targetRef="E2"/></bpmn:process>',
    )
    response = post_import(xml)
    body = response.json()

    assert response.status_code == 200 and body["supported"] is False
    assert [p["id"] for p in body["document"]["processes"]] == ["P1", "P2"]
    assert [(d["code"], d["blocksAnalysis"]) for d in body["diagnostics"]] == [("MULTIPLE_PROCESSES", True)]


def test_multiple_start_events_import_with_a_blocking_diagnostic() -> None:
    xml = definitions(
        '  <bpmn:process id="P">',
        '    <bpmn:startEvent id="S1"/><bpmn:startEvent id="S2"/><bpmn:endEvent id="E"/>',
        '    <bpmn:sequenceFlow id="a" sourceRef="S1" targetRef="E"/><bpmn:sequenceFlow id="b" sourceRef="S2" targetRef="E"/>',
        "  </bpmn:process>",
    )
    body = post_import(xml).json()
    assert body["supported"] is False
    assert [(d["code"], d["blocksAnalysis"]) for d in body["diagnostics"]] == [("MULTIPLE_START_EVENTS", True)]
    assert [n["id"] for n in body["document"]["processes"][0]["nodes"]] == ["S1", "S2", "E"]


# --- errors -------------------------------------------------------------------------------------


def test_malformed_xml_answers_422_with_the_error_line() -> None:
    response = post_import("<definitions>\n<process>\n</definitions>")
    detail = response.json()["detail"]

    assert response.status_code == 422
    assert detail["message"] == "The BPMN document could not be imported."
    assert [(d["severity"], d["code"], d["line"]) for d in detail["diagnostics"]] == [("error", "XML_MALFORMED", 3)]


def test_missing_end_event_answers_422() -> None:
    xml = definitions(
        '  <bpmn:process id="P">',
        '    <bpmn:startEvent id="S"/><bpmn:task id="T"/>',
        '    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="T"/>',
        "  </bpmn:process>",
    )
    response = post_import(xml)
    detail = response.json()["detail"]

    assert response.status_code == 422
    assert [(d["code"], d["processId"], d["blocksAnalysis"]) for d in detail["diagnostics"]] == [("NO_END_EVENT", "P", False)]


def test_all_error_diagnostics_are_returned_not_just_the_first() -> None:
    xml = definitions(
        '  <bpmn:process id="P">',
        '    <bpmn:startEvent id="S"/><bpmn:endEvent id="E"/>',
        '    <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Ghost"/>',
        '    <bpmn:sequenceFlow id="f2" sourceRef="Phantom" targetRef="E"/>',
        "  </bpmn:process>",
    )
    detail = post_import(xml).json()["detail"]
    assert [(d["code"], d["elementId"]) for d in detail["diagnostics"]] == [
        ("INVALID_REFERENCE", "f1"),
        ("INVALID_REFERENCE", "f2"),
    ]


def test_wrong_extension_answers_422_invalid_upload() -> None:
    response = post_import(SEQUENTIAL, filename="diagram.txt")
    detail = response.json()["detail"]

    assert response.status_code == 422
    assert detail["message"] == "The BPMN document could not be imported."
    assert [(d["code"], d["elementId"], d["line"]) for d in detail["diagnostics"]] == [("INVALID_UPLOAD", None, None)]


def test_missing_file_field_answers_the_fastapi_validation_error() -> None:
    response = post_import(SEQUENTIAL, field="files")
    detail = response.json()["detail"]
    assert response.status_code == 422 and isinstance(detail, list) and detail[0]["loc"] == ["body", "file"]


# --- existing endpoints keep their behavior ---------------------------------------------------------


def test_compile_still_runs_the_full_pipeline_and_still_refuses_blocked_diagrams() -> None:
    ok = client.post("/api/v1/processes/compile", files={"file": ("p.bpmn", SEQUENTIAL.encode(), "application/xml")})
    assert ok.status_code == 200
    assert ok.json()["metadata"]["process_id"] == "P" and "formal_analysis" in ok.json()

    blocked_xml = definitions(
        '  <bpmn:process id="P"><bpmn:startEvent id="S"/><bpmn:subProcess id="Sub"/><bpmn:endEvent id="E"/>',
        '  <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="Sub"/><bpmn:sequenceFlow id="f2" sourceRef="Sub" targetRef="E"/></bpmn:process>',
    )
    blocked = client.post("/api/v1/processes/compile", files={"file": ("p.bpmn", blocked_xml.encode(), "application/xml")})
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["message"] == "The BPMN document was imported but cannot be analyzed yet."
    assert [d["code"] for d in blocked.json()["detail"]["diagnostics"]] == ["UNSUPPORTED_ELEMENT"]

    imported_only = post_import(blocked_xml)  # the same document is importable (and displayable) here
    assert imported_only.status_code == 200 and imported_only.json()["supported"] is False


def test_simulate_still_refuses_blocked_diagrams_with_its_own_message() -> None:
    blocked_xml = definitions(
        '  <bpmn:process id="P"><bpmn:startEvent id="S"/><bpmn:intermediateCatchEvent id="W"/><bpmn:endEvent id="E"/>',
        '  <bpmn:sequenceFlow id="f1" sourceRef="S" targetRef="W"/><bpmn:sequenceFlow id="f2" sourceRef="W" targetRef="E"/></bpmn:process>',
    )
    response = client.post(
        "/api/v1/processes/simulate", files={"file": ("p.bpmn", blocked_xml.encode(), "application/xml")}, data={"input_data": "{}"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["message"] == "The BPMN document was imported but cannot be analyzed yet."


def test_openapi_lists_the_import_route_next_to_the_existing_ones() -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/v1/processes/import", "/api/v1/processes/compile", "/api/v1/processes/simulate"} <= set(paths)
