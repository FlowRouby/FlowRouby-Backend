    self.middleware_stack = self.build_middleware_stack()
                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\starlette\applications.py", line 75, in build_middleware_stack    
    if self.max_body_size is not None:
       ^^^^^^^^^^^^^^^^^^
AttributeError: 'FastAPI' object has no attribute 'max_body_size'        
INFO:     127.0.0.1:61696 - "GET /favicon.ico HTTP/1.1" 500 Internal Server Error
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\uvicorn\protocols\http\httptools_impl.py", line 409, in run_asgi  
    result = await app(  # type: ignore[func-returns-value]
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\uvicorn\middleware\proxy_headers.py", line 60, in __call__        
    return await self.app(scope, receive, send)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\fastapi\applications.py", line 1054, in __call__
    await super().__call__(scope, receive, send)
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\starlette\applications.py", line 95, in __call__
    self.middleware_stack = self.build_middleware_stack()
                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\starlette\applications.py", line 75, in build_middleware_stack    
    if self.max_body_size is not None:
       ^^^^^^^^^^^^^^^^^^
AttributeError: 'FastAPI' object has no attribute 'max_body_size'        
INFO:     127.0.0.1:60007 - "GET /docs HTTP/1.1" 500 Internal Server Error
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\uvicorn\protocols\http\httptools_impl.py", line 409, in run_asgi  
    result = await app(  # type: ignore[func-returns-value]
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\uvicorn\middleware\proxy_headers.py", line 60, in __call__        
    return await self.app(scope, receive, send)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\fastapi\applications.py", line 1054, in __call__
    await super().__call__(scope, receive, send)
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\starlette\applications.py", line 95, in __call__
    self.middleware_stack = self.build_middleware_stack()
                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\Lib\site-packages\starlette\applications.py", line 75, in build_middleware_stack    
    if self.max_body_size is not None:
       ^^^^^^^^^^^^^^^^^^
AttributeError: 'FastAPI' object has no attribute 'max_body_size'        
INFO:     127.0.0.1:51668 - "GET /favicon.ico HTTP/1.1" 500 Internal Server Error
# Guía de Referencia del Lenguaje de Dominio Específico `FlowSpec`

`FlowSpec` es el **Lenguaje Intermedio de Dominio Específico (DSL)** diseñado para representar procesos de negocio BPMN 2.0 (incluyendo extensiones de Camunda Modeler) de forma textual, declarativa y verificable formalmente antes de su compilación hacia **Ruby on Rails + Sidekiq**.

---

## 1. Clasificación en la Jerarquía de Chomsky

1. **Nivel Léxico (`flowspec/lexer/`) — Tipo 3 (Lenguaje Regular)**:
   Los tokens del lenguaje (palabras reservadas, identificadores, literales numéricos, booleanos, cadenas y operadores `->`, `<-`, `==`, `!=`, `<=`, `>=`, `&&`, `||`) son reconocidos mediante expresiones regulares.
2. **Nivel Sintáctico (`flowspec/parser/`) — Tipo 2 (Gramática Libre de Contexto - CFG)**:
   La estructura de bloques anidados (`process { lane { service_task { http_connector { ... } } } }`) y las expresiones con paréntesis recursivos (`when ((valorPagado + abono) < valorTotal)`) se validan mediante un **Analizador Sintáctico Descendente Recursivo LL(1)**.
3. **Nivel Semántico (`flowspec/semantic_analysis/`) — Sensible al Contexto**:
   Mediante una **Tabla de Símbolos**, el compilador verifica que cada transición `-> NodoDestino` exista, que no haya identificadores duplicados y que los tipos de datos (`boolean`, `long`/`number`, `string`) sean compatibles en todas las expresiones.

---

## 2. Gramática Formal (EBNF)

```ebnf
program         ::= "process" IDENTIFIER [ STRING ] "{" process_body "}" ;
process_body    ::= { lane_decl | node_decl } ;
lane_decl       ::= "lane" STRING "{" { node_decl } "}" ;

node_decl       ::= start_decl
                  | end_decl
                  | task_decl
                  | gateway_decl ;

start_decl      ::= "start" IDENTIFIER [ STRING ] ( [ "->" IDENTIFIER ] ";" | "{" { task_attr } "}" ) ;
end_decl        ::= "end" IDENTIFIER [ STRING ] ";" ;

task_decl       ::= task_kind IDENTIFIER [ STRING ] "{" { task_attr } "}" ;
task_kind       ::= "user_task"
                  | "service_task"
                  | "script_task"
                  | "manual_task"
                  | "business_rule_task"
                  | "call_activity" ;

task_attr       ::= "form_field" IDENTIFIER ":" IDENTIFIER [ STRING ] ";"
                  | "form_ref" STRING ";"
                  | "delegate_class" STRING ";"
                  | "decision_ref" STRING "->" IDENTIFIER ";"
                  | "called_element" STRING ";"
                  | "script" STRING ";"
                  | ( "input" | "output" ) IDENTIFIER "<-" expr ";"
                  | http_conn_decl
                  | "->" IDENTIFIER ";" ;

http_conn_decl  ::= "http_connector" "{"
                      { "method" ":" STRING ";"
                      | "url" ":" STRING ";"
                      | "headers" ":" "{" [ string_pair { "," string_pair } ] "}" ";"
                      | "payload" ":" "{" [ expr_pair { "," expr_pair } ] "}" ";"
                      | "output" ":" IDENTIFIER "<-" IDENTIFIER ";" }
                    "}" ;

string_pair     ::= STRING ":" STRING ;
expr_pair       ::= STRING ":" expr ;

gateway_decl    ::= gateway_kind IDENTIFIER [ STRING ] "{" { branch_stmt } "}" ;
gateway_kind    ::= "exclusive_gateway" | "parallel_gateway" | "inclusive_gateway" ;

branch_stmt     ::= "when" "(" expr ")" "->" IDENTIFIER ";"
                  | "default" "->" IDENTIFIER ";"
                  | "branch" "->" IDENTIFIER ";"
                  | "->" IDENTIFIER ";" ;

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

---

## 3. Guía de Declaración de Elementos

### 3.1. Proceso, Carriles (`lane`) y Eventos (`start`, `end`)
```flowspec
process realizarVisitaTecnica "Realizar Visita Técnica" {
  lane "Tecnico" {
    start StartEvent_1 "Visita agendada" -> Activity_1aczp5w;
    ...
    end Event_1swqw02 "Reporte de visita creado";
  }
}
```

### 3.2. Tareas de Usuario (`user_task`)
Soporta tanto campos en línea (`form_field`) como referencias a formularios (`form_ref`):
```flowspec
user_task Activity_1aczp5w "Validar visita" {
  form_field visita: boolean "¿la visita fue realizada?";
  -> Gateway_1s4ukmh;
}

user_task Activity_0n0dw98 "Realizar reporte de visita técnica" {
  form_ref "reporteDeVisitaTecnica";
  -> Activity_0lw92ym;
}
```

### 3.3. Tareas de Servicio (`service_task`)
Soporta conectores HTTP (`http_connector`) y clases delegadas (`delegate_class`):
```flowspec
service_task Activity_0lw92ym "Actualizar estado del Ticket de Visita en FSM" {
  http_connector {
    method: "POST";
    url: "http://localhost:9095/tickets/actualizar";
    headers: { "Content-Type": "application/json" };
    payload: { "TicketIdVisita": TicketIdVisita };
    output: RespuestaFSM <- response;
  }
  -> Event_1swqw02;
}

service_task Activity_066js8m "Guardar Factura de Pago" {
  delegate_class "com.emsa.workflow.SaveReport";
  -> Gateway_0423gd3;
}
```

### 3.4. Reglas de Negocio (`business_rule_task`) y Subprocesos (`call_activity`)
```flowspec
call_activity Activity_193y6v1 "Realizar visita técnica" {
  called_element "realizarVisitaTecnica";
  input TicketIdVisita <- TicketIdVisita;
  output cobroExtra <- cobroExtra;
  output tipoSolucion <- tipoSolucion;
  -> Activity_1ll5x9g;
}

business_rule_task Activity_1ll5x9g "Clasificar presupuesto" {
  decision_ref "clasificarPresupuesto" -> valor;
  output valorTotal <- valor + cobroExtra;
  -> Gateway_1b3ega7;
}
```

### 3.5. Compuertas (`exclusive_gateway`, `parallel_gateway`, `inclusive_gateway`)
```flowspec
exclusive_gateway Gateway_1s4ukmh "¿se realizó la visita?" {
  when (visita == false) -> Event_1ggqko4;
  default -> Activity_0n0dw98;
}

parallel_gateway Gateway_1b3ega7 "División Paralela" {
  branch -> Activity_1b7qy8d;
  branch -> Activity_066js8m;
}
```

