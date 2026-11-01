# Proposal: Simplificación y Limpieza del Payload de Respuesta en `/compile`

## Why

El JSON retornado actualmente por los endpoints de compilación (`POST /api/v1/processes/compile` y `POST /api/v1/flowspec/compile`) contiene información duplicada y estructuras internas de paso que incrementan innecesariamente el tamaño del payload y dificultan su consumo:
1. En `generated_ruby` se envían todos los archivos dos veces (primero agrupados por tipo en `workflow_orchestrator`, `form_objects`, `sidekiq_jobs`, `service_stubs`, `decision_stubs`, `rspec_suite` y luego repetidos dentro del mapa `files`).
2. El grafo del proceso se serializa por triplicado en la misma respuesta (`intermediate_model`, `flowspec.ast` y `flowspec.code`).
3. El bloque `data_contract` se envía tanto en la raíz del JSON como anidado dentro de `flowspec.semantic_analysis.data_contract`.

Reducir el response eliminando estas redundancias —manteniendo intacto `formal_analysis.dfa.state_subsets` para su análisis posterior— hará que la API sea más limpia, ligera y predecible.

## What Changes

- **Simplificación de `generated_ruby`**:
  - `RubyGenerationOutput.to_dict()` (o la respuesta de compilación) retornará únicamente `framework` y el diccionario consolidado `files` (`{ruta_relativa_rails: codigo_ruby}`), eliminando las llaves duplicadas por categoría en el payload JSON.
- **Unificación de la representación del grafo en `flowspec.code`**:
  - Se elimina la llave raíz `intermediate_model` del JSON de respuesta de `POST /api/v1/processes/compile`.
  - Se elimina `flowspec.ast` del JSON de respuesta en ambos endpoints de compilación, conservando `flowspec.code` como la representación canónica del flujo intermedio junto con `symbol_table`.
- **Desduplicación de `data_contract`**:
  - Se conserva `data_contract` exclusivamente en el nivel raíz del JSON de respuesta y se omite su duplicado dentro de `flowspec.semantic_analysis`.
- **Preservación de `formal_analysis.dfa.state_subsets`**:
  - No se modifica `formal_analysis.dfa.state_subsets`, manteniéndolo disponible en el reporte formal para inspección y análisis.

## Capabilities

### New Capabilities
- *(Ninguna capacidad nueva; se refina el contrato de respuesta de la capacidad existente).*

### Modified Capabilities
- `ruby-code-generation-and-api`: Se actualiza el formato del payload JSON de respuesta de los endpoints de compilación (`/api/v1/processes/compile` y `/api/v1/flowspec/compile`) para eliminar duplicidades en `generated_ruby`, representación del grafo y `data_contract`.

## Impact

- **`backend/app/features/code_generation/ruby/generator.py`**: `RubyGenerationOutput.to_dict()` pasa a exponer `framework` y `files`.
- **`backend/app/features/flowspec/semantic_analysis/analyzer.py`**: `SemanticAnalysisResult.to_dict()` permite serializar la tabla de símbolos y estado de validación sin duplicar `data_contract`.
- **`backend/app/main.py`**: Se ajustan las respuestas de `POST /api/v1/processes/compile` y `POST /api/v1/flowspec/compile`.
- **`backend/tests/test_compiler_pipeline.py`**: Se actualizan las aserciones sobre la estructura del JSON de compilación.

