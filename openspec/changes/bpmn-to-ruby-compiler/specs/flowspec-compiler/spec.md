## ADDED Requirements

### Requirement: Emisión y especificación formal del lenguaje de dominio específico FlowSpec
El módulo `flowspec` SHALL contar con un emisor que traduzca un `intermediate_model` a código textual `FlowSpec` y una especificación gramatical formal en notación EBNF documentada para que los usuarios puedan escribir o inspeccionar flujos directamente en `FlowSpec`.

#### Scenario: Traducción de modelo intermedio BPMN a texto DSL FlowSpec
- **WHEN** un archivo `.bpmn` es importado al `intermediate_model`
- **THEN** el emisor genera su representación textual equivalente en `FlowSpec` incluyendo declaraciones de `process`, `lane`, nodos (`start`, `end`, `user_task`, `service_task`, `script_task`, `manual_task`, `business_rule_task`, `call_activity`), compuertas (`exclusive_gateway`, `parallel_gateway`, `inclusive_gateway`), metadatos (`form_field`, `http_connector`) y transiciones condicionales

### Requirement: Analizador Léxico (Lexer Tipo 3) en Python Vanilla
El subpaquete `flowspec/lexer/` SHALL implementar en Python puro (sin librerías externas de parsing) un analizador léxico basado en expresiones regulares que convierta código `FlowSpec` en un flujo de tokens con posición de línea y columna.

#### Scenario: Tokenización de código FlowSpec y expresiones condicionales
- **WHEN** el lexer recibe un documento `FlowSpec` con bloques, identificadores, literales y operadores relacionales/lógicos (`==`, `!=`, `<`, `<=`, `>`, `>=`, `+`, `-`, `*`, `/`, `&&`, `||`, `!`, `->`)
- **THEN** produce la secuencia exacta de objetos `Token(type, value, line, column)` o lanza un `LexicalError` con coordenadas precisas si encuentra un carácter ilegal

### Requirement: Analizador Sintáctico (Parser LL(1) Tipo 2) y construcción de AST en Python Vanilla
El subpaquete `flowspec/parser/` SHALL implementar en Python puro un analizador sintáctico descendente recursivo que valide la Gramática Libre de Contexto (Tipo 2) de `FlowSpec` y construya los nodos del Árbol de Sintaxis Abstracta definidos en `flowspec/ast/`.

#### Scenario: Construcción de AST para estructura de proceso y expresiones anidadas
- **WHEN** el parser consume una lista válida de tokens de `FlowSpec` (incluyendo expresiones con precedencia de operadores y paréntesis anidados como `(valorPagado < (valor + cobroExtra))`)
- **THEN** construye un árbol `ProcessAST` completo y libre de ambigüedad

#### Scenario: Error sintáctico por llaves no balanceadas o transición malformada
- **WHEN** el código `FlowSpec` omite una llave de cierre `}` o una flecha de transición `->`
- **THEN** el parser lanza un `SyntaxError` detallando el token esperado, el token recibido, la línea y la columna

### Requirement: Análisis Semántico con Tabla de Símbolos
El subpaquete `flowspec/semantic_analysis/` SHALL recorrer el `AST` construyendo una Tabla de Símbolos para validar la integridad referencial de los nodos, la declaración previa de variables y la compatibilidad de tipos en las expresiones.

#### Scenario: Detección de transición hacia nodo inexistente
- **WHEN** una instrucción de transición `-> NodoDestino` referencia un identificador que no ha sido declarado en el proceso
- **THEN** el analizador semántico reporta un error `UNDECLARED_NODE_REFERENCE`

#### Scenario: Verificación de tipos e inferencia de contrato de datos
- **WHEN** una variable declarada como `boolean` en un `form_field` (ej. `visita: boolean`) se compara con un literal incompatible (ej. `visita < 100`)
- **THEN** el analizador semántico reporta un error `TYPE_MISMATCH` e infiere para las variables válidas el contrato de datos de entrada y salida (`data_contract`) del proceso

