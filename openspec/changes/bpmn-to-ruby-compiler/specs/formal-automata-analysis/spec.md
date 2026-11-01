## ADDED Requirements

### Requirement: Construcción de Autómata Finito No Determinista con transiciones épsilon (e-NFA)
El módulo `formal_analysis` SHALL transformar el `intermediate_model` en un $\varepsilon$-NFA en Python vanilla, donde las tareas y eventos representan símbolos del alfabeto $\Sigma$ y el flujo de control representa las transiciones entre estados.

#### Scenario: Secuencia lineal y bifurcación exclusiva (XOR)
- **WHEN** el modelo intermedio contiene secuencias de tareas y compuertas `exclusiveGateway` (incluyendo bucles de retorno como reintentos de pago)
- **THEN** el constructor de `nfa/` genera estados y transiciones $\varepsilon$ para las ramas alternativas y ciclos, reconociendo un Lenguaje Regular (Tipo 3 en la Jerarquía de Chomsky)

#### Scenario: Modelado de ParallelGateway (AND-Split / AND-Join) mediante vectores de flags
- **WHEN** el modelo intermedio contiene un bloque `parallelGateway` de división (*split*) con $k$ ramas que convergen en un `parallelGateway` de unión (*join*)
- **THEN** el constructor de `nfa/` modela el paralelismo mediante semántica de entrelazamiento (*interleaving*) usando estados compuestos con vectores de *flags* booleanos $(f_1, f_2, \dots, f_k) \in \{0,1\}^k$, habilitando la transición $\varepsilon$ de salida del *AND-Join* únicamente desde el estado $(1, 1, \dots, 1)$ donde todas las ramas han finalizado

#### Scenario: Modelado de InclusiveGateway (OR-Split / OR-Join) mediante subconjuntos activos
- **WHEN** el modelo intermedio contiene un `inclusiveGateway` con $k$ ramas condicionales
- **THEN** el constructor de `nfa/` genera las transiciones no deterministas para los $2^k - 1$ subconjuntos no vacíos de ramas activables y sincroniza en el *OR-Join* el vector de *flags* correspondiente al subconjunto activado

### Requirement: Determinización a DFA y síntesis de Expresión Regular
El módulo `formal_analysis` SHALL convertir el $\varepsilon$-NFA en un Autómata Finito Determinista (`dfa/`) mediante el algoritmo de construcción de subconjuntos ($\varepsilon\text{-closure}$) y obtener la Expresión Regular equivalente (`regular_expressions/`) mediante eliminación de estados.

#### Scenario: Generación de DFA y Expresión Regular del proceso
- **WHEN** se analiza un proceso BPMN válido
- **THEN** el servicio retorna la tabla de transiciones del DFA (estados, alfabeto, estado inicial, estados de aceptación) y la expresión regular que describe todas las secuencias válidas de actividades de inicio a fin

### Requirement: Detección de anomalías estructurales (Nodos Muertos, Deadlocks y Ciclos Infinitos)
El módulo `formal_analysis` SHALL analizar el grafo de estados del DFA para reportar errores y advertencias formales de diseño en el flujo.

#### Scenario: Detección de nodos inalcanzables (Dead Nodes)
- **WHEN** una tarea o subgrafo no tiene camino desde el estado inicial del autómata
- **THEN** el analizador reporta el nodo como `UNREACHABLE_NODE`

#### Scenario: Detección de bloqueo en sincronización (Deadlock XOR -> AND)
- **WHEN** una compuerta exclusiva (`exclusiveGateway`) bifurca caminos que luego intentan sincronizarse en una compuerta paralela (`parallelGateway` *AND-Join*)
- **THEN** el estado de completitud $(1, 1, \dots, 1)$ del *AND-Join* nunca se alcanza en esa ruta y el analizador reporta un `GATEWAY_DEADLOCK`

#### Scenario: Detección de ciclos infinitos sin salida (Livelock / Trap State)
- **WHEN** existe un ciclo de estados alcanzable desde el inicio desde el cual no existe ningún camino hacia un estado de aceptación (`EndEvent`)
- **THEN** el analizador reporta un `INFINITE_LOOP_TRAP` indicando los nodos involucrados en el bucle cerrado

