# Tasks: Implementación del Compilador BPMN -> FlowSpec -> Ruby y API

## 1. Estructura Base del Proyecto y Modelos Intermedios (`features/processes/`)

- [x] 1.1 Crear la estructura de paquetes Python en `backend/app/` (`features/processes/`, `features/formal_analysis/`, `features/flowspec/`, `features/code_generation/ruby/`) y configurar dependencias en `backend/pyproject.toml` o `requirements.txt` (`fastapi`, `uvicorn`, `pydantic`, `python-multipart`, `lxml`, `pytest`).
- [x] 1.2 Implementar `features/processes/intermediate_model/` definiendo las estructuras de datos (`ProcessGraph`, `LaneModel`, `FlowNode`, `UserTaskNode`, `ServiceTaskNode`, `ScriptTaskNode`, `ManualTaskNode`, `BusinessRuleTaskNode`, `CallActivityNode`, `GatewayNode`, `SequenceFlowEdge`, `FormFieldSpec`, `HttpConnectorSpec`).
- [x] 1.3 Implementar `features/processes/bpmn_importer/` refactorizando la validación XSD y el parseo XML/XPath de `SpiffWorkflow` (`BpmnValidator`, `ProcessParser`, `CamundaParser`) para extraer nodos, carriles, condiciones JUEL `${...}` y extensiones `camunda:*` (`formData`, `formRef`, `http-connector`, `camunda:class`, `in`/`out`, `decisionRef`) hacia `ProcessGraph`.
- [x] 1.4 Implementar `features/processes/services/process_service.py` para coordinar la validación de un único archivo `.bpmn` por petición y el preprocesamiento del grafo.

## 2. Análisis Formal con Autómatas y Expresiones Regulares (`features/formal_analysis/`)

- [x] 2.1 Implementar `features/formal_analysis/nfa/` en Python vanilla para transformar un `ProcessGraph` en un $\varepsilon$-NFA, incluyendo el modelado de `parallelGateway` e `inclusiveGateway` mediante estados compuestos con vectores de *flags* de completitud.
- [x] 2.2 Implementar `features/formal_analysis/dfa/` en Python vanilla con el algoritmo de construcción de subconjuntos ($\varepsilon\text{-closure}$ y `move`) para determinizar el $\varepsilon$-NFA en un DFA completo.
- [x] 2.3 Implementar `features/formal_analysis/regular_expressions/` en Python vanilla mediante el algoritmo de eliminación de estados para sintetizar la Expresión Regular (Tipo 3) de las trazas del proceso y enumerar las rutas acíclicas principales.
- [x] 2.4 Implementar `features/formal_analysis/services/analysis_service.py` para detectar nodos inalcanzables (`UNREACHABLE_NODE`), bloqueos en compuertas (`GATEWAY_DEADLOCK`), ciclos válidos vs. ciclos infinitos sin salida (`INFINITE_LOOP_TRAP`) y simular secuencias de símbolos sobre el DFA.

## 3. Compilador del Lenguaje Intermedio `FlowSpec` (`features/flowspec/`)

- [x] 3.1 Implementar el emisor `ProcessGraph -> FlowSpec DSL` y los nodos del Árbol de Sintaxis Abstracta en `features/flowspec/ast/` (`ProcessAST`, `LaneAST`, `NodeAST`, `GatewayAST`, `BinaryExprAST`, `UnaryExprAST`, `LiteralAST`, `IdentifierAST`).
- [x] 3.2 Implementar `features/flowspec/lexer/` en Python vanilla usando expresiones regulares para tokenizar declaraciones `FlowSpec` y expresiones condicionales con rastreo de línea y columna.
- [x] 3.3 Implementar `features/flowspec/parser/` en Python vanilla mediante un analizador sintáctico descendente recursivo LL(1) que valide la gramática libre de contexto (Tipo 2) de `FlowSpec` y construya el `ProcessAST`.
- [x] 3.4 Implementar `features/flowspec/semantic_analysis/` con Tabla de Símbolos, validación de destinos de transición, chequeo de tipos en expresiones condicionales, inferencia del contrato de datos (`required_inputs`, `produced_outputs`, `sample_payload`) e intérprete *stateless* para simulación (*Dry-Run*).
- [x] 3.5 Redactar la documentación formal de referencia del lenguaje `FlowSpec` (gramática EBNF, tipos de datos, ejemplos de declaración de tareas y compuertas) en `docs/flowspec_reference.md`.

## 4. Generador de Código Ruby on Rails + Sidekiq (`features/code_generation/ruby/`)

- [x] 4.1 Crear las plantillas base en `features/code_generation/ruby/templates/` para: clase orquestadora de Workflow Rails, `FormObject` (`ActiveModel::Validations`), `Sidekiq` HTTP Connector Job (`Net::HTTP`), servicio *stub* de `BusinessRuleTask` (preparado para futura expansión a DMN) y archivo de pruebas `RSpec`.
- [x] 4.2 Implementar `features/code_generation/ruby/generator.py` en Python vanilla incluyendo el transpilador de expresiones `AST -> Ruby` y la generación de código completo a partir del `ProcessAST` validado y de las rutas del análisis formal.

## 5. API REST en FastAPI y Pruebas de Integración (`backend/app/main.py`)

- [x] 5.1 Implementar `backend/app/main.py` con los endpoints `POST /api/v1/processes/compile` (carga de `.bpmn`), `POST /api/v1/flowspec/compile` (compilación directa de código `FlowSpec`) y `POST /api/v1/processes/simulate` (simulación *stateless* con payload JSON).
- [x] 5.2 Crear pruebas unitarias y de integración verificando el pipeline completo (Importer $\rightarrow$ NFA/DFA/RegEx $\rightarrow$ FlowSpec Lexer/Parser/AST/Semántica $\rightarrow$ Generación Ruby Rails/Sidekiq $\rightarrow$ Simulación) utilizando los modelos reales `process_models/realizarVisitaTecnica.bpmn` y `process_models/tecFailures.bpmn`.

