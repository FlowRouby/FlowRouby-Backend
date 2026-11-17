# Feature: ruby-generator-modules

**Branch:** `refactor/ruby-generator-modules` (from `main` @ `549249f`)
**Objective:** Split `backend/app/features/code_generation/ruby/generator.py` (544 lines, one class with five responsibilities) into focused modules so the code-generation stage reads as a compiler back end, and drop code that is provably unnecessary.
**Problem / why:** The file mixes naming helpers, expression translation, node/gateway translation, artifact builders and the fixed Rails scaffold. It works; the goal is readability for the course defense.
**Hard constraint (user):** nothing may break. The generated Ruby must stay byte-for-byte identical. No change to the `/compile` response or to any other endpoint.
**Out of scope:** changing the content of the generated Ruby; the automaton; the frontend; push / PR (user decides).

## Resolved settings
- TDD: enabled for the session. For a behavior-preserving refactor the RED/GREEN cycle is replaced by a characterization (golden) test committed on the untouched generator first; it must pass before and after.
- Runner: `../.venv/Scripts/python -W ignore -m pytest -q`, run from `backend/`.
- RDD (native review): off (global) -> no native review.
- Delivery strategy: `single-pr`. No PR without an explicit user request.
- Known environmental failures on base: `tests/test_compiler_pipeline.py::test_import_realizar_visita_tecnica_bpmn`, `::test_import_and_formal_analysis_tec_failures_bpmn`, `::test_fastapi_endpoints_compile_and_simulate`. Baseline: 149 passed, 3 failed.

## Target layout (`code_generation/ruby/`)
- `naming.py` — snake_case / PascalCase helpers
- `expression_transpiler.py` — AST expressions to Ruby
- `workflow_builder.py` — node and gateway translation
- `artifacts.py` — form objects, HTTP jobs, RSpec file
- `scaffold.py` — fixed Rails project files
- `generator.py` — orchestration and `RubyGenerationOutput` only
Public imports from `code_generation.ruby` (`RubyCodeGenerator`, `RubyExpressionTranspiler`, `RubyGenerationOutput`) stay valid.

## Tasks
- [x] T1 Golden test: fixtures under `backend/tests/fixtures/ruby_generation/` covering every node kind the generator handles, plus a snapshot of the generated files produced by the untouched generator — route: delegated (writer trigger: 2+ non-trivial files)
- [x] T2 Split `generator.py` into the target layout; remove unnecessary code only when the golden test and the full suite stay green — route: delegated

## Acceptance criteria
Golden test green before and after; full suite = baseline failures only; one Conventional Commit per task, no AI attribution, no push.

## Progress / evidence
- T1: 12 BPMN fixtures + golden JSON snapshots (`tests/test_ruby_generation_golden.py`, regenerate with `UPDATE_RUBY_GOLDEN=1`); golden test 14 passed on the untouched generator; full suite 163 passed, 3 failed (the 3 known environmental failures). Commit: 23b1452
- T2: generator.py split into naming, expression_transpiler, workflow_builder, artifacts, scaffold, generator; golden test 14 passed (snapshots untouched); full suite 163 passed, 3 failed (the 3 known environmental failures). Commit: the `refactor(codegen)` commit that contains this line
