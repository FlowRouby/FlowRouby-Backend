# Diagramas BPMN de demostración

Cinco diagramas válidos para mostrar cada caso del análisis formal. Todos incluyen la sección `BPMNDI`, así que se pueden abrir en el editor (bpmn-js) y en Camunda Modeler.

Los resultados de esta página se obtuvieron llamando a la API real (`/import`, `/compile`, `/simulate`, `/validate-trace`). En todos los casos `/import` responde `supported: true` y `/compile` responde `is_valid_workflow: true`.

| Archivo | Qué muestra | Estados del DFA |
|---|---|---|
| `01-secuencial.bpmn` | Caso base: una sola ruta | D0 a D4, acepta D4 |
| `02-decision-xor.bpmn` | Decisión exclusiva con condición y flujo por defecto; dos eventos de fin | D0 a D6, acepta D5 y D6 |
| `03-bucle-correccion.bpmn` | Ciclo controlado (estrella de Kleene) | D0 a D4, acepta D3 |
| `04-paralelo-and.bpmn` | Ramas paralelas: se aceptan todos los órdenes de ejecución | D0 a D6, acepta D6 |
| `05-inclusivo-or.bpmn` | Compuerta inclusiva: una rama, la otra o ambas | D0 a D5, acepta D4 |

La API los expone en `GET /api/v1/processes/samples` (listado) y `GET /api/v1/processes/samples/{id}` (XML), con el nombre del archivo sin extensión como `id`.

Las compuertas aparecen en `bpmn_node_ids` pero no son símbolos del alfabeto. Las rutas de `/validate-trace` solo llevan inicio, tareas y fin.

## 01-secuencial.bpmn

- Expresión regular: `start_1 · task_1 · task_2 · end_1`
- Ruta aceptada: `["start_1","task_1","task_2","end_1"]`
- Ruta rechazada (`NOT_ACCEPTING_STATE`): `["start_1","task_1","task_2"]`
- Ruta rechazada (`NO_TRANSITION` en el índice 1): `["start_1","task_2"]`
- Las dos tareas de usuario llevan un formulario generado de Camunda (`camunda:formData`). `task_1` pide `nombre_solicitante` (string), `numero_documento` (string) y `monto_solicitado` (long); `task_2` pide `observaciones` (string) y `datos_correctos` (boolean).
- `/compile` devuelve esas cinco variables en `data_contract.required_inputs` y en `flowspec.symbol_table`, y genera `app/forms/mostrar_datos_del_formulario_form.rb` y `app/forms/enviar_observaciones_form.rb`. Los formularios no cambian el autómata.

## 02-decision-xor.bpmn

- Expresión regular: `(start_1 · task_1 · task_2 · end_1 | start_1 · task_1 · task_3 · end_2)`
- Símbolos: `task_1` evaluar, `task_2` notificar aprobación, `task_3` notificar rechazo, `end_1` aprobada, `end_2` rechazada.
- `/simulate` con `{"aprobada": true}` recorre `task_2` y termina en `end_1`. Con `{}` toma el flujo por defecto: `task_3` y `end_2`.
- `/validate-trace` acepta las dos rutas, sin importar los datos.
- Ruta rechazada (`NO_TRANSITION` en el índice 3, esperaba `end_1`): `["start_1","task_1","task_2","end_2"]`
- Ruta rechazada (`UNKNOWN_SYMBOL`), enviando la compuerta en `bpmn_trace`: `["Start_Solicitud","Task_Evaluar","Gateway_Aprobada"]`

## 03-bucle-correccion.bpmn

- Expresión regular: `(start_1 · task_1 · end_1 | start_1 · task_1 · task_2 · (task_1 · task_2)* · task_1 · end_1)`
- Símbolos: `task_1` revisar, `task_2` corregir.
- `/compile` informa un `VALID_LOOP` entre los estados D2 y D4.
- Rutas aceptadas: `["start_1","task_1","end_1"]` y `["start_1","task_1","task_2","task_1","task_2","task_1","end_1"]` (dos correcciones).
- Ruta rechazada (`NO_TRANSITION` en el índice 3): `["start_1","task_1","task_2","end_1"]`, porque después de corregir hay que volver a revisar.
- En `/simulate`, `{"requiere_correccion": true}` nunca cambia de valor, así que la simulación repite el ciclo hasta `MAX_STEPS_EXCEEDED`. Para mostrar el ciclo conviene `/validate-trace`.

## 04-paralelo-and.bpmn

- Expresión regular: `(start_1 · task_1 · task_2 | start_1 · task_2 · task_1) · task_3 · end_1`
- Símbolos: `task_1` generar factura, `task_2` empacar, `task_3` despachar.
- Rutas aceptadas: `["start_1","task_1","task_2","task_3","end_1"]` y `["start_1","task_2","task_1","task_3","end_1"]`.
- Ruta rechazada (`NO_TRANSITION` en el índice 2): `["start_1","task_1","task_3","end_1"]`, porque falta una de las ramas.
- `via_gateways` trae `parallel_1` en las tareas de las ramas y `parallel_2` en `task_3`.

## 05-inclusivo-or.bpmn

- Expresión regular: `((start_1 · task_1 · end_1 | start_1 · task_2 · end_1) | (start_1 · task_1 · task_2 | start_1 · task_2 · task_1) · end_1)`
- Símbolos: `task_1` enviar correo, `task_2` enviar SMS.
- `/import` devuelve dos advertencias `PRESERVED_NOT_ANALYZABLE` (una por compuerta inclusiva). No bloquean el análisis; sirven para mostrar un diagnóstico de tipo `warning`.
- `/simulate` con `{"usar_correo": true}` recorre solo el correo; con `{"usar_correo": true, "usar_sms": true}` recorre las dos ramas.
- `/simulate` con `{}` no activa ninguna rama y termina en `DEADLOCK_OR_NO_TRANSITION`, porque la compuerta no tiene flujo por defecto. Sirve para mostrar una simulación que no termina.
- Ruta rechazada (`NO_TRANSITION` en el índice 1): `["start_1","end_1"]`, porque se necesita al menos una rama.
