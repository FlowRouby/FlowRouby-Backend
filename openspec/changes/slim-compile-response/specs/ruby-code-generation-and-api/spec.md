## MODIFIED Requirements

### Requirement: Exposición de Endpoints REST en FastAPI
El archivo `backend/app/main.py` SHALL exponer una API REST con FastAPI que integre el pipeline completo de importación, análisis formal, compilación `FlowSpec`, generación Ruby y simulación con un contrato JSON libre de duplicidades.

#### Scenario: Compilación desde archivo BPMN o código FlowSpec con respuesta optimizada
- **WHEN** se realiza una petición `POST /api/v1/processes/compile` enviando un archivo `.bpmn` (o `POST /api/v1/flowspec/compile` enviando código `FlowSpec`)
- **THEN** la API responde con un JSON que contiene:
  1. `metadata`: Información general del proceso.
  2. `validation`: Estado de validez y advertencias/errores.
  3. `data_contract`: Presente únicamente en la raíz del JSON (`required_inputs`, `produced_outputs`, `sample_payload`), sin duplicarse dentro de `flowspec`.
  4. `formal_analysis` (en compilación BPMN): Incluye `dfa` (conservando `state_subsets`), `regular_expression`, `flag_regions`, `acyclic_paths` y `diagnostics`.
  5. `flowspec`: Contiene `chomsky_classification`, `code` (única representación serializada del grafo, omitiendo `intermediate_model` y `flowspec.ast`) y `symbol_table`.
  6. `generated_ruby`: Contiene únicamente `framework` y el diccionario unificado `files` (`{ruta_archivo: codigo_ruby}`), sin duplicar los archivos en sub-objetos por categoría.

#### Scenario: Simulación de flujo mediante endpoint dedicado
- **WHEN** se realiza una petición `POST /api/v1/processes/simulate` con el archivo `.bpmn` (o código `FlowSpec`) y el objeto `input_data`
- **THEN** la API ejecuta la simulación sin estado y retorna la traza de ejecución (`visited_nodes`, `step_logs`, `http_requests_simulated`, `final_context`) y si la traza fue aceptada por el DFA del proceso

