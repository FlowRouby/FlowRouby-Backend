# Tasks: Limpieza del Response JSON de Compilación (`slim-compile-response`)

## 1. Refactorización de Serializadores de Respuesta

- [x] 1.1 Actualizar `RubyGenerationOutput.to_dict()` en `backend/app/features/code_generation/ruby/generator.py` para retornar únicamente `framework` y `files`.
- [x] 1.2 Actualizar `SemanticAnalysisResult.to_dict()` en `backend/app/features/flowspec/semantic_analysis/analyzer.py` para exponer `symbol_table` sin duplicar `data_contract`.
- [x] 1.3 Actualizar `compile_bpmn_process` y `compile_flowspec_direct` en `backend/app/main.py` para omitir `intermediate_model` y `flowspec.ast`, dejar `data_contract` solo en la raíz y mantener `formal_analysis.dfa.state_subsets` intacto.

## 2. Actualización de Pruebas

- [x] 2.1 Actualizar y ejecutar `backend/tests/test_compiler_pipeline.py` validando la nueva estructura limpia del JSON de respuesta.

