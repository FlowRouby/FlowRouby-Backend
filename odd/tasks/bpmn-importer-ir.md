# Feature: bpmn-importer-ir

**Branch:** `feat/bpmn-importer-ir` (from `main`)
**Objective:** Reliable BPMN import and a vendor-neutral intermediate model (IR), with structured diagnostics and no silent information loss.
**Out of scope:** automata engine, FlowSpec lexer/parser, Ruby generator, MongoDB (only minimal compatibility adjustments, documented below).

## Resolved settings
- TDD: disabled (no project/session config; source: none found). Ordinary functional checks apply.
- Runner: `pytest` (backend/tests), run from `backend/` in a scratchpad venv.
- RDD (native review): off (global default) -> no native review.
- Delivery strategy: `ask-on-risk`. Forecast: ~1200 authored lines -> chain strategy to be asked before the first commit that crosses ~400 lines.

## Accepted decisions (Phase A/B)
- BPMN standard data stays in IR (Lane/LaneSet, scriptFormat/script, calledElement, gateway default). Vendor (Camunda) data goes to per-element `extensions`, keyed by namespace URI (attributes + generic element tree).
- Remove invented values: default script_format, `dmn_mode`, default-flow heuristic, name=id fallback, task/sendTask/receiveTask -> ServiceTask.
- Diagnostics: `Diagnostic(severity, code, message, element_id, element_type, process_id, blocks_analysis)`; `ImportResult(document|None, diagnostics)`; all errors accumulated.
- FlowRouby profile (NOT universal BPMN rules): missing startEvent = import error; missing endEvent = import error; multiple startEvent = import OK + analysis blocked by diagnostic; multiple endEvent = allowed.
- Unsupported elements are preserved as `UNSUPPORTED` nodes with warning; callActivity and inclusiveGateway imported but not analyzable.
- Parsing with `defusedxml`; drop `lxml` and the dead XSD path.
- Emitter keeps working through an adapter (`flowspec/ast/camunda_extensions.py`); IR must not regain proprietary fields.

## Tasks
- [x] T1 IR models: `models.py`, `extensions.py`, `diagnostics.py` (neutral, dataclasses) — route: delegated
- [x] T2 Importer: `xml_loader.py`, `parser.py`, `validator.py`, facade `importer.py`, `process_service.py`; remove dead code and `lxml` — route: delegated
- [x] T3 Compatibility: Camunda adapter + minimal emitter / nfa_builder / main.py adjustments — route: delegated
- [ ] T4 Tests: `tests/test_bpmn_import.py` (inline fixtures) and run the full suite — route: delegated
- [ ] T5 Final report (files, scope, diagnostics, results, limitations, impact)

## Acceptance criteria
IDs/names preserved, edges and conditions preserved, unsupported elements reported, structural errors detected, no silent loss, importer independent of FlowSpec/Ruby/MongoDB/automata, tests runnable.

## Progress / evidence
(commits and check results are recorded here per task)
- T1 (route: delegated): neutral IR (`models.py`, `extensions.py`, `diagnostics.py`). Check: package imports and smoke-constructs OK. Importer and consumers still use the old API until T2/T3, so the tree is intentionally not runnable between T1 and T3.
- T2 (route: delegated): `xml_loader.py` (defusedxml), `parser.py`, `validator.py`, `importer.py` facade, `process_service.py`; `lxml` replaced by `defusedxml`; vendor classes, XSD validator and unused namespace constants removed. Check: smoke import of an inline document (namespace-by-URI, extensions kept, unsupported node reported, NOT_BPMN/XML_MALFORMED errors). Consumers (emitter, main.py) are migrated in T3; full tests run in T4.
- T3 (route: delegated): `camunda_extensions.py` adapter, emitter and `main.py` migrated, `processes/README.md` added. Check: FlowSpec text emitted by the old (main) pipeline and the new pipeline is byte-identical on an inline Camunda sample (lanes, forms, connector, mappings, script, decision, gateway default heuristic, generic task); compile and simulate endpoints run on it. Full pytest run is part of T4.

## Next step
T4
