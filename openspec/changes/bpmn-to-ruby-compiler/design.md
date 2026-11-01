# Design: Arquitectura del Compilador BPMN -> FlowSpec -> Ruby y Analizador Formal

## Context

El proyecto requiere transformar diagramas de procesos de negocio BPMN 2.0 (modelados en Camunda Modeler, como `realizarVisitaTecnica.bpmn` y `tecFailures.bpmn` en `process_models/`) en esqueletos ejecutables para una arquitectura **Ruby on Rails + Sidekiq**, pasando por un lenguaje intermedio de dominio específico (`FlowSpec`) y un motor de verificación formal basado en teoría de autómatas ($\varepsilon$-NFA, DFA, Expresiones Regulares).

Se toma como base de referencia el repositorio local de `SpiffWorkflow` (`v3.2.0`), pero bajo la restricción clave de que **no se administrarán instancias de flujo persistentes**. En su lugar, el sistema operará como un compilador estático y simulador *stateless* expuesto mediante **FastAPI** bajo la siguiente estructura de directorios:

```text
backend/
└── app/
    ├── features/
    │   ├── processes/
    │   │   ├── bpmn_importer/
    │   │   ├── intermediate_model/
    │   │   └── services/
    │   ├── formal_analysis/
    │   │   ├── regular_expressions/
    │   │   ├── nfa/
    │   │   ├── dfa/
    │   │   └── services/
    │   ├── flowspec/
    │   │   ├── lexer/
    │   │   ├── parser/
    │   │   ├── ast/
    │   │   └── semantic_analysis/
    │   └── code_generation/
    │       └── ruby/
    │           ├── templates/
    │           └── generator.py
    └── main.py
```

## Goals / Non-Goals

**Goals:**
- Reutilizar y refactorizar la validación XSD y extracción XPath de `SpiffWorkflow/bpmn/parser/` y `SpiffWorkflow/camunda/parser/` dentro de `features/processes/bpmn_importer/` produciendo un `intermediate_model` limpio sin dependencias del motor de ejecución de Spiff.
- Soportar en Fase 1 un archivo `.bpmn` por petición con: `startEvent`, `endEvent`, `userTask`, `serviceTask` (conectores HTTP y clases delegadas), `scriptTask`, `manualTask`, `callActivity`, `businessRuleTask` (como *stub* preparado para DMN), `exclusiveGateway`, `parallelGateway` e `inclusiveGateway`.
- Implementar en **Python Vanilla** el análisis formal (`nfa`, `dfa`, `regular_expressions`) resolviendo el modelado de compuertas paralelas e inclusivas mediante estados compuestos con vectores de *flags* (entrelazamiento).
- Diseñar e implementar en **Python Vanilla** el compilador del DSL intermedio `FlowSpec` (`lexer`, `parser` LL(1), `ast`, `semantic_analysis`) y documentar formalmente su gramática EBNF.
- Generar plantillas Ruby on Rails + Sidekiq (`code_generation/ruby/`) en Python Vanilla y proveer un simulador *stateless* (*Dry-Run*).

**Non-Goals:**
- Persistir instancias de ejecución, tareas activas o historial en bases de datos.
- Soportar en esta primera fase el parseo y evaluación completa de archivos `.dmn` (se deja el *hook* arquitectónico en `BusinessRuleTask` para Fase 2).
- Soportar carga de múltiples archivos `.bpmn` arbitrarios en una sola petición (evitando grafos inconexos o recursión mutua entre procesos).

## Decisions

### 1. Frontera de Refactorización de `SpiffWorkflow`
- **Decisión**: Extraer únicamente la lógica de validación XSD (`BpmnValidator` + archivos `schema/BPMN20.xsd`) y las consultas XPath de `ProcessParser` (`_index_process_nodes`, extracción de `lanes`, `sequenceFlow`, `conditionExpression`) junto con el parseo de extensiones `camunda:*` (`formData`, `formRef`, `connector`, `inputOutput`, `in`/`out`, `decisionRef`).
- **Racional**: En `SpiffWorkflow`, `TaskParser` instancia subclases de `TaskSpec` que inyectan nodos sintéticos de control (`BoundaryEventSplit`, `StartEventJoin`, nodos `[child]`) acoplados a `TaskState`. Reemplazar esa salida por dataclasses inmutables en `intermediate_model/` reduce la complejidad en un 80% y prepara el grafo directamente para el autómata y el emisor `FlowSpec`.

### 2. Separación Teórica según la Jerarquía de Chomsky
- **Decisión**: Dividir el análisis del proceso en dos planos formales complementarios:
  1. **Nivel Tipo 3 (Lenguajes Regulares) en `features/formal_analysis/` y `flowspec/lexer/`**:
     - Las trazas de ejecución del diagrama BPMN (secuencias de tareas desde `StartEvent` hasta `EndEvent`) constituyen un lenguaje regular sobre el alfabeto de actividades $\Sigma$, siempre que `callActivity` se trate como transición atómica sin recursión y los bloques paralelos sean finitos.
     - El escaneo léxico de `FlowSpec` (`lexer/`) reconoce tokens mediante expresiones regulares Tipo 3.
  2. **Nivel Tipo 2 (Gramática Libre de Contexto - CFG) en `flowspec/parser/`**:
     - El código textual `FlowSpec` posee bloques anidados `{ ... }` y expresiones aritmético-lógicas con paréntesis balanceados `((a + b) < c)`, lo cual requiere una gramática Tipo 2 analizada mediante un *Recursive Descent Parser* LL(1).
  3. **Restricciones Sensibles al Contexto en `flowspec/semantic_analysis/`**:
     - La verificación de que toda transición `-> Destino` apunte a un nodo declarado y la inferencia/chequeo de tipos de variables (`boolean`, `long`, `string`) se resuelven recorriendo el `AST` con una Tabla de Símbolos.

### 3. Modelado de `ParallelGateway` e `InclusiveGateway` en un Autómata Finito
- **Decisión**: Representar los bloques paralelos (`AND-Split` $\rightarrow$ `AND-Join`) e inclusivos (`OR-Split` $\rightarrow$ `OR-Join`) en el $\varepsilon$-NFA mediante **Semántica de Entrelazamiento (*Interleaving*) con Estados de Vector de Flags**:
  - Dado un `parallelGateway` que divide el flujo en $k$ ramas $(R_1, R_2, \dots, R_k)$:
    - El estado de entrada al bloque paralelo inicializa un vector de *flags* $(0, 0, \dots, 0)$.
    - Ejecutar las actividades de la rama $R_i$ actualiza la componente $i$-ésima del estado a $1$.
    - El nodo `AND-Join` solo tiene una transición $\varepsilon$ de salida desde el estado donde el vector de *flags* es $(1, 1, \dots, 1)$.
  - Para un `inclusiveGateway` (`OR-Split` con $k$ ramas), el estado en el split selecciona no-determinísticamente el subconjunto activo $S \subseteq \{1, \dots, k\}$ ($S \neq \emptyset$) como máscara objetivo, y el `OR-Join` se dispara cuando el vector de *flags* completados iguala la máscara $S$.
- **Beneficio clave**: Permite que los algoritmos estándar de alcanzabilidad sobre el DFA detecten automáticamente *deadlocks* estructurales (por ejemplo, si un `exclusiveGateway` se conecta por error a un `parallelGateway` de unión, el estado $(1, 1)$ jamás es alcanzado). Se establece un límite de seguridad de $k \le 5$ ramas concurrentes por compuerta para evitar explosión exponencial de estados ($2^k$).

### 4. Diseño Gramatical (EBNF) de `FlowSpec` en Python Vanilla
- **Decisión**: Implementar el compilador de `FlowSpec` en Python estándar sin generadores externos (sin ANTLR/Lark/PLY), usando la siguiente gramática EBNF base:

```ebnf
program         ::= "process" IDENTIFIER STRING "{" process_body "}" ;
process_body    ::= { lane_decl | node_decl } ;
lane_decl       ::= "lane" STRING "{" { node_decl } "}" ;

node_decl       ::= start_decl
                  | end_decl
                  | task_decl
                  | gateway_decl ;

start_decl      ::= "start" IDENTIFIER [ STRING ] [ "->" IDENTIFIER ] ";" ;
end_decl        ::= "end" IDENTIFIER [ STRING ] ";" ;

task_decl       ::= task_kind IDENTIFIER [ STRING ] "{" { task_attr } [ transition_stmt ] "}" ;
task_kind       ::= "user_task" | "service_task" | "script_task" | "manual_task"
                  | "business_rule_task" | "call_activity" ;

task_attr       ::= form_field_decl
                  | form_ref_decl
                  | http_conn_decl
                  | class_decl
                  | rule_ref_decl
                  | call_ref_decl
                  | script_decl
                  | io_map_decl ;

form_field_decl ::= "form_field" IDENTIFIER ":" TYPE_NAME [ STRING ] ";" ;
form_ref_decl   ::= "form_ref" STRING ";" ;
class_decl      ::= "delegate_class" STRING ";" ;
rule_ref_decl   ::= "decision_ref" STRING "->" IDENTIFIER ";" ;
call_ref_decl   ::= "called_element" STRING ";" ;
script_decl     ::= "script" STRING ";" ;
io_map_decl     ::= ( "input" | "output" ) IDENTIFIER "<-" expr ";" ;

http_conn_decl  ::= "http_connector" "{"
                      "method" ":" STRING ";"
                      "url" ":" STRING ";"
                      [ "headers" ":" map_literal ";" ]
                      [ "payload" ":" map_literal ";" ]
                      [ "output" ":" IDENTIFIER "<-" IDENTIFIER ";" ]
                    "}" ;

gateway_decl    ::= gateway_kind IDENTIFIER [ STRING ] "{" { branch_stmt } "}" ;
gateway_kind    ::= "exclusive_gateway" | "parallel_gateway" | "inclusive_gateway" ;
branch_stmt     ::= "when" "(" expr ")" "->" IDENTIFIER ";"
                  | "default" "->" IDENTIFIER ";"
                  | "branch" "->" IDENTIFIER ";"
                  | "join" "->" IDENTIFIER ";" ;

transition_stmt ::= "->" IDENTIFIER ";" ;

expr            ::= logical_or ;
logical_or      ::= logical_and { ( "||" | "or" ) logical_and } ;
logical_and     ::= equality { ( "&&" | "and" ) equality } ;
equality        ::= comparison { ( "==" | "!=" ) comparison } ;
comparison      ::= term { ( "<" | "<=" | ">" | ">=" ) term } ;
term            ::= factor { ( "+" | "-" ) factor } ;
factor          ::= unary { ( "*" | "/" ) unary } ;
unary           ::= ( "!" | "not" | "-" ) unary | primary ;
primary         ::= IDENTIFIER | NUMBER | STRING | BOOLEAN | "(" expr ")" ;
```

### 5. Generación de Plantillas Ruby on Rails + Sidekiq en Python Vanilla
- **Decisión**: `features/code_generation/ruby/generator.py` utilizará plantillas parametrizadas en `templates/` renderizadas con un motor ligero en Python vanilla para producir un paquete coherente de archivos Rails:
  - `app/workflows/<process_snake>_workflow.rb`: Clase orquestadora con tabla de despacho de nodos, evaluación de condiciones traducidas a sintaxis Ruby y registro de auditoría de pasos.
  - `app/forms/<task_snake>_form.rb`: Clases con `include ActiveModel::Model` y validaciones automáticas según los `<camunda:formField>` (`boolean`, `long` $\rightarrow$ `numericality: { only_integer: true }`, `string`).
  - `app/jobs/<task_snake>_http_job.rb`: Sidekiq Job con llamada `Net::HTTP` preconfigurada (método, URL, headers y serialización JSON del payload con las variables del contexto).
  - `app/services/decisions/<decision_snake>_service.rb`: Servicio *stub* para `businessRuleTask` con contrato de entrada/salida listo para ser reemplazado cuando se implemente el soporte DMN.
  - `spec/workflows/<process_snake>_workflow_spec.rb`: Casos de prueba `RSpec` generados a partir de las rutas válidas encontradas en el análisis formal.

## Risks / Trade-offs

- **[Explosión de estados en compuertas paralelas/inclusivas con muchas ramas]** $\rightarrow$ **Mitigación**: Acotar el producto cartesiano de *flags* a un máximo configurable (ej. $k \le 6$ ramas simultáneas por compuerta) y reportar una advertencia si se supera.
- **[Expresiones arbitrarias en `conditionExpression` de Camunda]** $\rightarrow$ **Mitigación**: Soportar el subconjunto estándar de expresiones relacionales, aritméticas y booleanas JUEL (`${...}`) que aparece en los modelos reales (`==`, `!=`, `<`, `<=`, `>`, `>=`, `+`, `-`, `*`, `/`, `&&`, `||`, `!`) y reportar errores léxicos/sintácticos claros si un diagrama incluye código Java nativo no soportado.
- **[Ciclos legítimos vs. Ciclos infinitos en análisis formal]** $\rightarrow$ **Mitigación**: Distinguir en el DFA entre un **ciclo con salida** (como el bucle de reintento de pago en `tecFailures.bpmn`, que tiene una transición hacia `Event_1q1goyy` cuando el pago está completo, reportado como `VALID_LOOP`) y un **ciclo trampa sin salida** (ningún nodo del componente fuertemente conexo tiene camino hacia un `EndEvent`, reportado como `INFINITE_LOOP_TRAP`).

