# Proposal: Compilador, Analizador Formal y Generador Ruby desde BPMN (FlowSpec Pipeline)

## Why

El desarrollo de aplicaciones empresariales basadas en procesos de negocio suele requerir motores pesados que administran instancias persistentes en bases de datos (como Camunda Platform o el runtime completo de SpiffWorkflow). Sin embargo, en escenarios donde se busca generar código nativo mantenible (específicamente sobre una arquitectura **Ruby on Rails + Sidekiq**) y verificar formalmente la correctitud del diseño antes de pasar a producción, se necesita un enfoque de **compilación, verificación formal y simulación sin estado (*stateless*)**.

Adicionalmente, desde una perspectiva académica y de ingeniería de compiladores, traducir un archivo XML BPMN directamente a código destino oculta las fases formales de validación léxica, sintáctica, semántica y de teoría de autómatas. Introducir un **Lenguaje Específico de Dominio (DSL) intermedio llamado `FlowSpec`** junto con un módulo de **Análisis Formal basado en Autómatas Finitos ($\varepsilon$-NFA, DFA y Expresiones Regulares)** permite:
1. Verificar matemáticamente propiedades del flujo (alcanzabilidad, ausencia de *deadlocks* en compuertas paralelas, nodos muertos y ciclos infinitos) tratando las trazas del proceso como un **Lenguaje Regular (Tipo 3 en la Jerarquía de Chomsky)**.
2. Desacoplar el origen visual (BPMN 2.0 / Camunda Modeler) del código destino mediante una **Gramática Libre de Contexto (Tipo 2 en la Jerarquía de Chomsky)** compilada en Python puro (*vanilla*).
3. Generar esqueletos ejecutables e idiomáticos para **Ruby on Rails / Sidekiq** (incluyendo clientes HTTP para conectores Camunda, validaciones de formularios de usuario y *stubs* preparados para una futura expansión a tablas de decisión **DMN**).

## What Changes

Se implementará la aplicación `backend/` basada en **FastAPI** siguiendo una arquitectura modular por *features* (`processes`, `formal_analysis`, `flowspec`, `code_generation`):

- **Refactorización focalizada del parser de `SpiffWorkflow` (`features/processes/bpmn_importer/` e `intermediate_model/`)**:
  - Se extrae y adapta la lógica de validación XSD y parseo XML/XPath de `SpiffWorkflow/bpmn/parser` y `SpiffWorkflow/camunda/parser`, descartando por completo el motor de ejecución de instancias (`Workflow`, `Task`, `TaskState`, serializadores de estado y migraciones).
  - Soporte para **un (1) archivo `.bpmn` por petición** con los elementos: `startEvent`, `endEvent`, `userTask` (con `camunda:formData` y `camunda:formRef`), `serviceTask` (con `camunda:connector` HTTP y `camunda:class`), `scriptTask`, `manualTask`, `callActivity` (tratado como invocación externa atómica con mapeo de variables) y `businessRuleTask` (modelado como *mock/stub* extensible a DMN en una fase posterior).
  - Soporte para compuertas `exclusiveGateway`, `parallelGateway` e `inclusiveGateway`, además de carriles (`lanes`).
- **Módulo de Análisis Formal (`features/formal_analysis/`) en Python Vanilla**:
  - Transformación del `intermediate_model` a un **$\varepsilon$-NFA** (`nfa/`), modelando el paralelismo (`parallelGateway` e `inclusiveGateway`) mediante semántica de entrelazamiento (*interleaving*) y estados compuestos por vectores de *flags* de completitud de rama.
  - Determinización por construcción de subconjuntos hacia un **DFA** (`dfa/`) y conversión a **Expresión Regular** (`regular_expressions/`) por eliminación de estados.
  - Detección estática de nodos inalcanzables (*dead nodes*), bloqueos mutuos (*deadlocks* por ej. `XOR-Split` conectado a `AND-Join`), ciclos sin salida (*livelocks* / bucles infinitos) y simulación de trazas sobre el DFA.
- **Compilador del Lenguaje Intermedio `FlowSpec` (`features/flowspec/`) en Python Vanilla**:
  - Diseño y documentación formal (EBNF) del DSL `FlowSpec`, capaz de generarse automáticamente desde el `intermediate_model` o recibirse directamente en la API.
  - Implementación en Python puro de: `lexer/` (analizador léxico Tipo 3 basado en expresiones regulares), `parser/` (analizador sintáctico descendente recursivo LL(1) Tipo 2 para bloques y expresiones JUEL/condicionales como `${visita == false}` o `${valorPagado < valorTotal}`), `ast/` (nodos inmutables del Árbol de Sintaxis Abstracta) y `semantic_analysis/` (Tabla de Símbolos, verificación de declaración y tipos de variables, resolución de referencias de transición y validación de compuertas).
- **Generador de Código Ruby on Rails / Sidekiq (`features/code_generation/ruby/`) en Python Vanilla**:
  - Generación de plantillas Ruby a partir del AST validado: Orquestador del Workflow (`app/workflows/`), *Form Objects* con `ActiveModel::Validations` para `userTask`, *Sidekiq Jobs / Service Objects* con llamadas `Net::HTTP` preconfiguradas para `serviceTask` con `http-connector`, *stubs* para `businessRuleTask` (preparados para DMN) y pruebas unitarias en `RSpec` por cada camino del proceso.
- **API REST y Simulador Sin Estado (`backend/app/main.py` y `services/`)**:
  - Endpoints en FastAPI para compilar/validar desde `.bpmn` o código `FlowSpec`, y para simular ejecuciones completas (*Dry-Run*) recibiendo un JSON con los datos de entrada y formularios sin persistir instancias en base de datos.

## Capabilities

### New Capabilities
- `bpmn-importer-and-ir`: Importación, validación XSD y extracción de metadatos BPMN 2.0 / Camunda (un diagrama por petición) hacia el modelo intermedio de grafo (`intermediate_model`), con soporte de extensión (*hook*) para `businessRuleTask` / DMN.
- `formal-automata-analysis`: Construcción de $\varepsilon$-NFA (con vectores de *flags* para compuertas paralelas e inclusivas), determinización a DFA, síntesis de Expresiones Regulares, diagnóstico de anomalías estructurales (nodos muertos, *deadlocks*, ciclos infinitos) y validación formal de trazas.
- `flowspec-compiler`: Emisión del DSL `FlowSpec`, especificación gramatical EBNF y pipeline de compilación en Python vanilla (`lexer`, `parser` LL(1), `ast` y `semantic_analysis` con Tabla de Símbolos).
- `ruby-code-generation-and-api`: Generación de plantillas para Ruby on Rails + Sidekiq, simulador de flujo *stateless* con datos de prueba y exposición de endpoints HTTP mediante FastAPI.

### Modified Capabilities
- *(Ninguna capacidad existente se modifica; se crea la arquitectura base en `backend/app/`).*

## Impact

- **Nuevos directorios y código**: Creación de `backend/app/` con los módulos `features/processes/`, `features/formal_analysis/`, `features/flowspec/`, `features/code_generation/ruby/` y `main.py`, además de la documentación oficial del lenguaje `FlowSpec` en `docs/flowspec_reference.md`.
- **Relación con `SpiffWorkflow/`**: Se toma `SpiffWorkflow/bpmn/parser/` y `SpiffWorkflow/camunda/parser/` como referencia arquitectónica para extraer un parser limpio en `bpmn_importer/`, manteniendo únicamente `lxml` y `fastapi`/`pydantic` como dependencias de infraestructura, mientras que todo el núcleo algorítmico (`formal_analysis`, `flowspec`, `code_generation`) se implementa en Python estándar (*vanilla*).
- **Modelos de prueba**: Compatible directamente con los diagramas Camunda existentes en el repositorio (`process_models/realizarVisitaTecnica.bpmn` y `process_models/tecFailures.bpmn`).

