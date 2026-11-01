## ADDED Requirements

### Requirement: Generación de plantillas para Ruby on Rails y Sidekiq en Python Vanilla
El módulo `code_generation/ruby/` SHALL transformar el AST validado de `FlowSpec` en un conjunto estructurado de artefactos de código Ruby orientados a Ruby on Rails y Sidekiq sin depender de motores de plantillas externos.

#### Scenario: Generación de Orquestador de Workflow, Form Objects y Sidekiq HTTP Services
- **WHEN** el generador Ruby procesa un AST que contiene `user_task` (con `formData`), `service_task` (con `http-connector` o `camunda:class`), `business_rule_task` (mock) y `call_activity`
- **THEN** genera:
  1. La clase orquestadora `app/workflows/<process_name>_workflow.rb` con la lógica de control de flujo y manejo de contexto.
  2. Clases `FormObject` con `ActiveModel::Model` y `ActiveModel::Validations` para cada `user_task`.
  3. Workers/Servicios Sidekiq (`app/jobs/` y `app/services/`) con cliente `Net::HTTP` preconfigurado (URL, método, headers, payload JSON interpolado y asignación de respuesta) para cada `service_task` con conector HTTP.
  4. Un servicio *stub* (`<DecisionRef>DecisionService`) para cada `business_rule_task`, dejando un punto de extensión limpio para cuando se incorpore soporte DMN.
  5. Una plantilla de pruebas `spec/workflows/<process_name>_workflow_spec.rb` en `RSpec` cubriendo las rutas identificadas.

### Requirement: Simulación de Flujos Sin Estado (Stateless Dry-Run)
El sistema SHALL permitir simular la ejecución completa de un flujo a partir de su representación intermedia y un payload JSON de entrada (con valores de variables y formularios), sin crear ni persistir instancias en base de datos.

#### Scenario: Simulación exitosa de flujo con bifurcaciones, llamadas HTTP mockeadas y bucles
- **WHEN** el usuario envía un payload de prueba (ej. `{"visita": true, "TicketIdVisita": "TCK-101"}`) al simulador
- **THEN** el simulador evalúa las expresiones condicionales paso a paso, simula los conectores HTTP y `businessRuleTask` con respuestas mock configurables, controla un límite máximo de iteraciones para bucles y retorna la lista ordenada de nodos visitados, las decisiones tomadas en cada compuerta y el estado final del contexto de datos

### Requirement: Exposición de Endpoints REST en FastAPI
El archivo `backend/app/main.py` SHALL exponer una API REST con FastAPI que integre el pipeline completo de importación, análisis formal, compilación `FlowSpec`, generación Ruby y simulación.

#### Scenario: Compilación desde archivo BPMN o código FlowSpec
- **WHEN** se realiza una petición `POST /api/v1/processes/compile` enviando un archivo `.bpmn` (o `POST /api/v1/flowspec/compile` enviando código `FlowSpec`)
- **THEN** la API responde con un JSON que contiene: `metadata`, `validation` (errores/warnings), `formal_analysis` (DFA, expresión regular, diagnóstico de deadlocks/nodos muertos/ciclos), `flowspec_code`, `data_contract` (inputs, outputs y `sample_payload`), y `generated_ruby` (archivos Ruby para Rails/Sidekiq y RSpec)

#### Scenario: Simulación de flujo mediante endpoint dedicado
- **WHEN** se realiza una petición `POST /api/v1/processes/simulate` con el archivo `.bpmn` (o código `FlowSpec`) y el objeto `input_data`
- **THEN** la API ejecuta la simulación sin estado y retorna la traza de ejecución (`visited_nodes`, `step_logs`, `http_requests_simulated`, `final_context`) y si la traza fue aceptada por el DFA del proceso

