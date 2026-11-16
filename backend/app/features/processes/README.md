# BPMN import and Intermediate Model (IR)

```
XML text -> xml_loader (defusedxml) -> parser (IR) -> validator (diagnostics) -> ImportResult
```

* `bpmn_importer/` - `BpmnImporter.import_xml(...)` / `import_file(...)` return an `ImportResult`.
  The importer knows nothing about HTTP, FlowSpec, Ruby, automata or persistence.
* `intermediate_model/` - vendor-neutral IR (`ProcessGraph`, nodes, `SequenceFlowEdge`, `Lane`,
  `Extensions`) and the `Diagnostic` / `ImportResult` types.
* `services/` - `ProcessImportService` applies the upload rules (one `.bpmn`/`.xml` file) and
  delegates to the importer.

## IR in short

* BPMN ids and names are never rewritten (`name` is `None` when the XML has none). `compile` and
  `simulate` work on a copy whose nodes use sequential symbols (`start_1`, `task_1`, ...), built by
  `intermediate_model/id_normalizer.symbolize_node_ids`, and return the symbol -> BPMN id map as
  `bpmn_node_ids`.
* Every node keeps its original tag in `bpmn_type`, plus a normalized `node_type` and a
  `support` level (`analyzable`, `preserved`, `unsupported`).
* Sequence flows keep `source_ref`, `target_ref`, the raw `Condition` (text, `language`,
  `xsi:type`) and `is_default` (derived from the source node's `default` attribute).
* Lanes and lane sets (including `childLaneSet`), participants, documentation, script task
  `scriptFormat`/`script` and call activity `calledElement` are standard BPMN and live in the IR.
* Vendor data lives in `extensions` of each element: foreign-namespace attributes and the
  children of `<extensionElements>`, as a generic tree identified by **namespace URI**
  (never by XML prefix).
* BPMN children the importer does not interpret (event definitions, loop characteristics,
  text annotations, ...) are kept in `unrecognized` as the same generic tree.
* Unsupported flow nodes become `UnsupportedNode` (with the full original element in `source`)
  so sequence flows stay consistent.
* BPMNDI layout data is not imported; keep the original XML to preserve it.
* Processes, nodes, flows, lanes and participants keep `source_line`, the line of their start tag in
  the imported XML (also used by diagnostics).

## Supported subset

| Level | Elements |
| --- | --- |
| Analyzable | `startEvent`, `endEvent`, `task`, `userTask`, `serviceTask`, `manualTask`, `scriptTask`, `sendTask`, `receiveTask`, `businessRuleTask`, `exclusiveGateway`, `parallelGateway`, `sequenceFlow` |
| Imported and valid for code generation, outside the initial analysis profile (provisional analysis) | `callActivity`, `inclusiveGateway` |
| Unsupported (kept as opaque nodes) | `intermediateCatchEvent`, `intermediateThrowEvent`, `boundaryEvent`, `subProcess`, `adHocSubProcess`, `transaction`, `eventBasedGateway`, `complexGateway` |

## Diagnostics

A `Diagnostic` has `severity` (`error`/`warning`/`info`), `code`, `message`, `elementId`,
`elementType`, `processId`, `blocksAnalysis` and `line` (line of the element's start tag in the
imported XML, when known; for `XML_MALFORMED` it is the parser's error line). All problems are
collected, not just the first.
When any error exists, `ImportResult.document` is `None`.

| Code | Severity | Meaning |
| --- | --- | --- |
| `INVALID_UPLOAD` | error | Request rule: the file extension must be `.bpmn` or `.xml` |
| `XML_MALFORMED` | error | Not well-formed XML, or it declares a DTD/entities |
| `NOT_BPMN` | error | Root is not `<definitions>` in the BPMN 2.0 model namespace |
| `NO_PROCESS` | error | No `<process>` in the document |
| `MISSING_ID`, `DUPLICATE_ID` | error | Required id absent, or an id used twice in the document |
| `MISSING_REF_ATTRIBUTE` | error | `sequenceFlow` without `sourceRef`/`targetRef` |
| `INVALID_REFERENCE` | error | Flow, lane, default flow or participant points to something that does not exist |
| `NO_START_EVENT`, `NO_END_EVENT` | error | **FlowRouby profile rule** (not a general BPMN rule) |
| `MULTIPLE_START_EVENTS` | warning, blocks analysis | **FlowRouby profile rule**: imported, analysis blocked until a formal representation exists. Several end events are allowed |
| `MULTIPLE_PROCESSES` | warning, blocks analysis | All processes are imported; analysis works on one |
| `UNSUPPORTED_ELEMENT` | warning | Element kept but not interpreted; blocks analysis when it changes behavior |
| `PRESERVED_NOT_ANALYZABLE` | warning, does not block analysis | `callActivity` / `inclusiveGateway`: imported and valid for code generation, but outside FlowRouby's initial formal-analysis profile, so analysis results involving them are provisional. This describes a profile decision, not missing code: the current NFA builder models a call activity as an atomic symbol and inclusive split/join pairs through flag regions |
| `DISCONNECTED_NODE`, `GATEWAY_WITHOUT_OUTGOING`, `XOR_FLOW_WITHOUT_CONDITION_OR_DEFAULT` | warning | Structural hints; analysis still runs and reports the consequences |
| `IGNORED_ELEMENT` | info | Preserved as unrecognized content (or, for BPMNDI, not imported) |

## Camunda compatibility adapter (temporary)

`flowspec/ast/camunda_extensions.py` interprets Camunda data from `extensions` so the FlowSpec
emitter keeps working without the IR carrying proprietary fields. Namespace
`http://camunda.org/schema/1.0/bpmn`:

* attributes: `formRef`/`formKey`, `class`, `decisionRef`, `resultVariable`
* elements: `formData/formField` (id, type, label), `inputOutput` parameters, `connector`
  (method, url, headers, payload, output parameters), `in` / `out` mappings

Preserved in the IR but not read by the emitter: `formRefBinding`, form field defaults,
`connectorId`, `mapDecisionResult`.

Minimal emitter adjustments: it applies FlowSpec conventions the IR no longer carries
(`task`/`sendTask`/`receiveTask` use the `service_task` keyword, `name`/`id` fallbacks, JUEL `${}`
removal from conditions, and the implicit default branch of a gateway with a single
unconditional flow). `main.py` stops the compile and simulate pipelines with HTTP 422 and the
relevant diagnostics when the import has errors or analysis is blocked.

## Import-only endpoint

`POST /api/v1/processes/import` (`router.py`, response built by `import_response.py`) imports a
single `.bpmn`/`.xml` file through `ProcessImportService` and returns the IR as camelCase JSON. It
runs no formal analysis, FlowSpec emission, semantic analysis, code generation or persistence.

* Import errors answer `422` with `{"detail": {"message", "diagnostics": [errors]}}`, like `compile`.
* Otherwise it answers `200` with `{"supported", "diagnostics", "document"}`, even when warnings
  exist or analysis is blocked, so the frontend can still display the diagram. `supported` means
  "formal analysis can run on this import" (no diagnostic has `blocksAnalysis: true`); it does not
  mean "the diagram is valid BPMN".
* `document` lists every process with its nodes (including unsupported ones, by BPMN id), sequence
  flows, lane sets and the generic namespace-keyed `extensions`. Extension attribute names are data
  from the XML and are returned unchanged.
