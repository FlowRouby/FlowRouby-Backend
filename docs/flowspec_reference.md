# Guía de Referencia del Lenguaje de Dominio Específico `FlowSpec`

`FlowSpec` es un **Lenguaje Controlado de Dominio Específico (CNL / DSL externo)** basado en indentación estricta por espacios, diseñado para representar procesos de negocio BPMN 2.0 (incluyendo extensiones de Camunda Modeler) de forma legible, declarativa y verificable formalmente antes de su compilación hacia **Ruby on Rails + Sidekiq**.

---

## 1. Clasificación y Reglas Léxicas

1. **Nivel Léxico (`flowspec/lexer/`) — Tipo 3 + Pila de Indentación (`INDENT` / `DEDENT`)**:
   - Los bloques se delimitan exclusivamente mediante **indentación estricta con espacios** y saltos de línea (`NEWLINE`), sin llaves `{ }`, puntos y coma `;`, dos puntos `:` ni flechas `->` / `<-`.
   - **Sin fallbacks**: el uso de tabulaciones (`\t`) o niveles de sangría inconsistentes al hacer `DEDENT` produce inmediatamente un `FlowSpecLexicalError`.
   - Operadores naturales: `is` (`==`), `is not` (`!=`), `and` (`&&`), `or` (`||`), `not` (`!`), además de `<`, `<=`, `>`, `>=`, `+`, `-`, `*`, `/`.
2. **Nivel Sintáctico (`flowspec/parser/`) — Tipo 2 (Gramática Libre de Contexto - CFG)**:
   - La jerarquía de bloques (`process` → `lane` → nodos → atributos / `http call` → `headers` / `payload`) y las expresiones recursivas con paréntesis se validan mediante un **Analizador Sintáctico Descendente Recursivo LL(1)**.
3. **Nivel Semántico (`flowspec/semantic_analysis/`) — Sensible al Contexto**:
   - Mediante una **Tabla de Símbolos**, el compilador verifica que cada transición (`next is <id>`, `if ... go to <id>`, `otherwise go to <id>`, `branch to <id>`) apunte a un nodo declarado, que no haya identificadores duplicados y que los tipos de datos (`boolean`, `long`/`number`, `string`) sean compatibles en todas las expresiones.

---

## 2. Gramática Formal (EBNF con Indentación)

```ebnf
program         = "process" name_and_id NEWLINE [ INDENT process_body DEDENT ] ;
name_and_id     = STRING "as" IDENTIFIER | IDENTIFIER ;
process_body    = { lane_decl | node_decl } ;
lane_decl       = "lane" STRING NEWLINE [ INDENT { node_decl } DEDENT ] ;

node_decl       = start_decl
                | end_decl
                | task_decl
                | gateway_decl ;

start_decl      = "start" name_and_id NEWLINE [ INDENT { task_attr } DEDENT ] ;
end_decl        = "end" name_and_id NEWLINE ;

task_decl       = task_kind name_and_id NEWLINE [ INDENT { task_attr } DEDENT ] ;
task_kind       = "user" "task"
                | "service" "task"
                | "script" "task"
                | "manual" "task"
                | "business" "rule"
                | "call" "activity" ;

task_attr       = "ask" IDENTIFIER IDENTIFIER [ "labeled" STRING ] NEWLINE
                | "use" "form" STRING NEWLINE
                | "delegate" STRING NEWLINE
                | "decide" STRING "into" IDENTIFIER NEWLINE
                | "call" STRING NEWLINE
                | "run" "script" STRING NEWLINE
                | "set" ( "input" | "output" ) IDENTIFIER "from" expr NEWLINE
                | http_call_decl
                | "next" "is" IDENTIFIER NEWLINE ;

http_call_decl  = "http" "call" NEWLINE INDENT { http_attr } DEDENT ;
http_attr       = "method" STRING NEWLINE
                | "url" STRING NEWLINE
                | "headers" NEWLINE INDENT { STRING "is" STRING NEWLINE } DEDENT
                | "payload" NEWLINE INDENT { STRING "from" expr NEWLINE } DEDENT
                | "save" IDENTIFIER "as" IDENTIFIER NEWLINE ;

gateway_decl    = gateway_kind name_and_id NEWLINE [ INDENT { branch_stmt } DEDENT ] ;
gateway_kind    = "decision"
                | "parallel" "split"
                | "inclusive" "split" ;

branch_stmt     = "if" expr "go" "to" IDENTIFIER NEWLINE
                | "otherwise" "go" "to" IDENTIFIER NEWLINE
                | "branch" "to" IDENTIFIER NEWLINE
                | "next" "is" IDENTIFIER NEWLINE ;

expr            = logical_or ;
logical_or      = logical_and { "or" logical_and } ;
logical_and     = equality { "and" equality } ;
equality        = comparison { ( "is" "not" | "is" ) comparison } ;
comparison      = term { ( "<" | "<=" | ">" | ">=" ) term } ;
term            = factor { ( "+" | "-" ) factor } ;
factor          = unary { ( "*" | "/" ) unary } ;
unary           = "not" unary | "-" unary | primary ;
primary         = IDENTIFIER | NUMBER | STRING | BOOLEAN | "(" expr ")" ;
```

---

## 3. Guía de Declaración de Elementos

### 3.1. Proceso, Carriles (`lane`) y Eventos (`start`, `end`)
```flowspec
process "Realizar Visita Técnica" as realizarVisitaTecnica
  lane "Tecnico"
    start "Visita agendada" as StartEvent_1
      next is Activity_1aczp5w
    end "Reporte de visita creado" as Event_1swqw02
```

### 3.2. Tareas de Usuario (`user task`)
Soporta tanto campos en línea (`ask`) como referencias a formularios (`use form`):
```flowspec
user task "Validar visita" as Activity_1aczp5w
  ask boolean visita labeled "¿la visita fue realizada?"
  next is Gateway_1s4ukmh

user task "Realizar reporte de visita técnica" as Activity_0n0dw98
  use form "reporteDeVisitaTecnica"
  next is Activity_0lw92ym
```

### 3.3. Tareas de Servicio (`service task`)
Soporta conectores HTTP (`http call`) y clases delegadas (`delegate`):
```flowspec
service task "Actualizar estado del Ticket de Visita en FSM" as Activity_0lw92ym
  http call
    method "POST"
    url "http://localhost:9095/tickets/actualizar"
    headers
      "Content-Type" is "application/json"
    payload
      "TicketIdVisita" from TicketIdVisita
    save response as RespuestaFSM
  next is Event_1swqw02

service task "Guardar Factura de Pago" as Activity_066js8m
  delegate "com.emsa.workflow.SaveReport"
  next is Gateway_0423gd3
```

### 3.4. Reglas de Negocio (`business rule`) y Subprocesos (`call activity`)
```flowspec
call activity "Realizar visita técnica" as Activity_193y6v1
  call "realizarVisitaTecnica"
  set input TicketIdVisita from TicketIdVisita
  set output cobroExtra from cobroExtra
  set output tipoSolucion from tipoSolucion
  next is Activity_1ll5x9g

business rule "Clasificar presupuesto" as Activity_1ll5x9g
  decide "clasificarPresupuesto" into valor
  set output valorTotal from valor + cobroExtra
  next is Gateway_1b3ega7
```

### 3.5. Compuertas (`decision`, `parallel split`, `inclusive split`)
```flowspec
decision "¿se realizó la visita?" as Gateway_1s4ukmh
  if visita is false go to Event_1ggqko4
  otherwise go to Activity_0n0dw98

parallel split "División Paralela" as Gateway_1b3ega7
  branch to Activity_1b7qy8d
  branch to Activity_066js8m
```
