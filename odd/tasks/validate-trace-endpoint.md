# Feature: validate-trace-endpoint

**Branch:** `feat/validate-trace-endpoint` (from `main` @ `c43a67d`)
**Objective:** `POST /api/v1/processes/validate-trace` decides whether a user-written trace belongs to the language of the DFA inferred from an uploaded BPMN model (membership problem), returning the step-by-step walk.
**Problem / why:** `/simulate` answers "which path does the engine take for these variables"; nothing answers "is this path one of the model's possible executions".
**Out of scope:** any change to the behavior or responses of `/import`, `/compile`, `/simulate`; frontend repo; persistence (stateless); push / PR (user decides).

## Resolved settings
- TDD: enabled (source: plan accepted by the user in session, 2026-11-16). RED -> GREEN -> REFACTOR.
- Runner: `../.venv/Scripts/python -W ignore -m pytest -q`, run from `backend/`.
- RDD (native review): off (decided by global) -> no native review.
- Delivery strategy: `single-pr`. Forecast ~490 authored lines (about 260 are tests). No PR is opened without an explicit user request.
- Known environmental failures on base (`main`): `tests/test_compiler_pipeline.py::test_import_realizar_visita_tecnica_bpmn`, `::test_import_and_formal_analysis_tec_failures_bpmn`, `::test_fastapi_endpoints_compile_and_simulate` (missing git-ignored `../process_models/*.bpmn`). Baseline: 72 passed, 3 failed.

## Verified facts (exploration)
- The DFA is built per request by `FormalAnalysisService.analyze(graph)` (`nfa_builder.py` -> `dfa_builder.py`); `/simulate` already obtains it as `formal_service.analyze(graph).dfa`.
- Gateways are never DFA symbols (epsilon transitions only). Alphabet = `start_N`, `task_N`, `end_N`. Confirmed with real `/compile` calls on sequential, XOR, XOR loop, AND, OR and AND-with-nested-XOR diagrams.
- `simulation.visited_nodes` includes gateways and repeats joins; the DFA trace is the internal `activity_trace_for_dfa`. Gateway step logs are the ones carrying `selected_targets`.
- An AND split whose branch contains another gateway is not a structured region: the DFA language is empty (regex `∅`) although `/simulate` reaches the end event.
- `bpmn_node_ids` is already documented in `docs/api-contract-bpmn-import.md` section 2.1.

## Accepted decisions
- Request: multipart `file` plus exactly one of `trace` (symbols) or `bpmn_trace` (original BPMN ids), each a JSON array of strings. Both, neither, or not a JSON array of strings -> 422 `{"detail": {"message": "..."}}`. Empty array is valid input.
- `DFA.walk(trace)` returns the detailed walk; `DFA.accepts()` delegates to it with an unchanged result.
- Validation logic lives in its own class (user request): `TraceValidationService` in `backend/app/features/formal_analysis/services/trace_validation_service.py`. The router only parses the form, delegates and shapes the response.
- Left-to-right evaluation, first failure wins.
- `final_state` is the state where the walk stopped; it is the start state (`D0`) when nothing was consumed, so it is never null in practice (deviation from the original spec, accepted).
- Unknown id in `bpmn_trace`: `validation.trace` keeps the raw id at that position; result `UNKNOWN_SYMBOL`.
- Each step carries `via_gateways`: gateway symbols crossed to reach that node (drawing aid computed on the graph, not part of the automaton). Ambiguous gateway-only paths return every gateway on them, sorted.

## Response shape (200)
```
{ "process_id", "bpmn_node_ids",
  "validation": { "accepted", "trace", "steps": [{ "index", "symbol", "from_state", "to_state", "via_gateways" }],
                  "consumed", "final_state", "rejected_at", "rejection_reason", "expected_symbols" } }
```
`rejection_reason`: `UNKNOWN_SYMBOL` (not in the DFA alphabet; `rejected_at` = index), `NO_TRANSITION` (in alphabet, no transition from current state; `rejected_at` = index), `NOT_ACCEPTING_STATE` (whole trace consumed, state not accepting; `rejected_at` = null). `expected_symbols` sorted, may be empty. A rejected trace is HTTP 200.

## Tasks
- [x] T1 `DFA.walk()` + `accepts()` delegating to it; unit tests incl. old-vs-new `accepts` equivalence — route: delegated (writer trigger: feature touches 2+ non-trivial files)
- [x] T2 `TraceValidationService` (walk + bpmn id translation + `via_gateways`) with unit tests — route: delegated
- [x] T3 Endpoint `POST /validate-trace` in `router.py` + endpoint tests (accepted, three rejection reasons, empty trace, trace/bpmn_trace equivalence, both fields, neither, invalid JSON, non-analyzable 422, missing file, simulate-route-accepted, OpenAPI, CORS) — route: delegated
- [x] T4 Contract `docs/api-contract-bpmn-import.md`: endpoint row, response shape with an example captured from the real API, `rejection_reason` table, alphabet note, limitations — route: delegated

## Acceptance criteria
Endpoint visible in `/openapi.json`; `/import`, `/compile`, `/simulate` responses unchanged; CORS still works for `http://localhost:4200`; full suite = baseline failures only; one Conventional Commit per task, no AI attribution, no push.

## Progress / evidence
(commits and check results are recorded here per task)
- T1 done. RED: `tests/test_dfa_walk.py` 9 failed / 1 passed (`DFA` has no attribute `walk`). GREEN: 10 passed. Full suite: 82 passed, 3 failed (known environmental failures only). Commit: ba7e45b.
- T2 done. RED: `tests/test_trace_validation_service.py` collection error (module `trace_validation_service` missing). First GREEN run: 15 passed, 2 failed because two of my `via_gateways` expectations were wrong (parallel branch B only crosses the split; an ambiguous chain returns both gateways); tests corrected to the documented semantics, then 17 passed. Full suite: 100 passed, 3 failed (known environmental failures only). Commit: 7e65d8f.
- T3 done. RED: `tests/test_validate_trace_endpoint.py` 31 failed / 1 passed (route absent; the passing one was the CORS preflight answered by the middleware). GREEN: 32 passed, including simulate-derived traces accepted for sequential, XOR (both branches) and parallel. Full suite: 132 passed, 3 failed (known environmental failures only). Commit: c77c375.
- T4 done. Contract section 1.2 added with real TestClient output (accepted and rejected XOR examples), rejection_reason table, notes and limitation; section 1 table row and section 2.4 row added. Docs only, no RED/GREEN applicable. Full suite: 132 passed, 3 failed (known environmental failures only). Commit hash: reported by the writer.
