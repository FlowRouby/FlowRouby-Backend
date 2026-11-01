## ADDED Requirements

### Requirement: Validación e importación de un único archivo BPMN por petición
El sistema SHALL aceptar un único archivo `.bpmn` por petición, validarlo estructuralmente contra el esquema XML BPMN 2.0 (y extensiones `camunda`) utilizando la lógica refactorizada de `SpiffWorkflow`, y rechazar cargas múltiples o archivos XML malformados.

#### Scenario: Archivo BPMN válido de Camunda Modeler
- **WHEN** el usuario envía un archivo `.bpmn` válido (como `realizarVisitaTecnica.bpmn` o `tecFailures.bpmn`)
- **THEN** el importador valida el esquema XML sin errores y construye una instancia completa de `ProcessGraph` en `intermediate_model`

#### Scenario: Archivo XML inválido o sin nodo process ejecutable
- **WHEN** el usuario envía un archivo XML con etiquetas BPMN inválidas o sin ningún `<bpmn:process>`
- **THEN** el importador lanza un error de validación indicando la línea y descripción del problema estructural

### Requirement: Extracción de nodos de tareas y metadatos de Camunda
El importador SHALL extraer y representar en `intermediate_model` los nodos `startEvent`, `endEvent`, `userTask`, `serviceTask`, `scriptTask`, `manualTask`, `callActivity` y `businessRuleTask`, incluyendo sus metadatos de extensión `camunda:*`.

#### Scenario: Extracción de UserTask con campos de formulario Camunda
- **WHEN** un `<bpmn:userTask>` contiene `<camunda:formData>` con elementos `<camunda:formField id="..." type="..." label="..."/>` o el atributo `camunda:formRef`
- **THEN** el nodo correspondiente en `intermediate_model` almacena la lista tipada de campos de formulario (`boolean`, `long`, `string`, etc.) y/o la referencia `form_ref`

#### Scenario: Extracción de ServiceTask con conector HTTP o clase delegada
- **WHEN** un `<bpmn:serviceTask>` contiene `<camunda:connector>` (`http-connector` con `url`, `method`, `headers`, `payload`, `outputParameter`) o el atributo `camunda:class`
- **THEN** el nodo en `intermediate_model` almacena la especificación completa de la petición HTTP (incluyendo variables interpoladas `${...}`) o el nombre de la clase delegada

#### Scenario: Extracción de CallActivity como invocación atómica externa
- **WHEN** el proceso contiene un `<bpmn:callActivity calledElement="...">` con mapeos `<camunda:in>` y `<camunda:out>`
- **THEN** el `intermediate_model` registra el nodo como una invocación atómica al subproceso externo referenciado junto con su contrato de variables de entrada y salida, sin requerir que el archivo del subproceso se suba en la misma petición

#### Scenario: Extracción de BusinessRuleTask como stub extensible a DMN
- **WHEN** el proceso contiene un `<bpmn:businessRuleTask>` con `camunda:decisionRef`, `camunda:resultVariable` y `<camunda:outputParameter>`
- **THEN** el `intermediate_model` crea un nodo `BusinessRuleNode` en modo *mock/stub* conservando `decision_ref`, `result_variable` y expresiones de salida para permitir tanto la simulación como la futura conexión de un parser DMN sin alterar el modelo intermedio

### Requirement: Extracción de compuertas, flujos de secuencia y carriles
El importador SHALL soportar las compuertas `exclusiveGateway`, `parallelGateway` e `inclusiveGateway`, extrayendo los `sequenceFlow` con sus expresiones condicionales (`conditionExpression`), el flujo `default` y la pertenencia de cada nodo a su `lane` respectivo.

#### Scenario: Compuerta exclusiva con condición JUEL y flujo por defecto
- **WHEN** un `<bpmn:exclusiveGateway>` define el atributo `default="Flow_1"` y otro flujo saliente tiene `<bpmn:conditionExpression>${visita==false}</bpmn:conditionExpression>`
- **THEN** el `intermediate_model` limpia la envoltura `${...}`, asocia la expresión `visita==false` a la arista condicional y marca `Flow_1` como la arista `is_default=True`

