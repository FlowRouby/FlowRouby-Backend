# Diagramas BPMN de demostración

Siete diagramas válidos. Los cinco primeros muestran cada caso del análisis formal por separado; los dos últimos son procesos más grandes que combinan varios casos. Todos incluyen la sección `BPMNDI`, así que se pueden abrir en el editor (bpmn-js) y en Camunda Modeler.

Los resultados de esta página se obtuvieron llamando a la API real (`/import`, `/compile`, `/simulate`, `/validate-trace`). En todos los casos `/import` responde `supported: true` y `/compile` responde `is_valid_workflow: true`.

| Archivo | Qué muestra | Estados del DFA |
|---|---|---|
| `01-secuencial.bpmn` | Caso base: una sola ruta | D0 a D4, acepta D4 |
| `02-decision-xor.bpmn` | Decisión exclusiva con condición y flujo por defecto; dos eventos de fin | D0 a D6, acepta D5 y D6 |
| `03-bucle-correccion.bpmn` | Ciclo controlado (estrella de Kleene) | D0 a D4, acepta D3 |
| `04-paralelo-and.bpmn` | Ramas paralelas: se aceptan todos los órdenes de ejecución | D0 a D6, acepta D6 |
| `05-inclusivo-or.bpmn` | Compuerta inclusiva: una rama, la otra o ambas | D0 a D5, acepta D4 |
| `06-solicitud-credito.bpmn` | Proceso completo: formularios, conector HTTP, regla de negocio, decisión de tres salidas, ramas paralelas y dos eventos de fin | D0 a D13, acepta D10 y D13 |
| `07-gestion-incidentes.bpmn` | Proceso con carriles (pool y tres lanes), ramas paralelas, ciclo de corrección y dos eventos de fin | D0 a D13, acepta D12 y D13 |

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

## 06-solicitud-credito.bpmn

17 nodos y 19 flujos. Reúne en un solo proceso los elementos que el compilador traduce a Ruby.

- Símbolos: `task_1` registrar solicitud, `task_2` consultar historial (HTTP), `task_3` evaluar riesgo (regla de negocio), `task_4` aprobar automáticamente, `task_5` revisar con analista, `task_6` notificar rechazo (HTTP), `task_7` generar contrato, `task_8` notificar aprobación (HTTP), `task_9` desembolsar, `end_1` rechazada, `end_2` desembolsado.
- Decisión `¿Nivel de riesgo?`: `riesgo < 30 && monto <= ingresos * 10` aprueba automáticamente, `riesgo < 70` pasa al analista y el flujo por defecto rechaza.
- `/compile` devuelve cinco variables de formulario en `data_contract.required_inputs` y dos salidas en `produced_outputs`: `historial` (respuesta HTTP) y `riesgo` (regla de negocio).
- Ruby generado: dos formularios en `app/forms/`, tres jobs HTTP en `app/jobs/`, tres servicios en `app/services/` y un servicio de decisión en `app/services/decisions/`.
- `/simulate` con `{"cliente": "Ana", "monto": 1000, "ingresos": 500, "riesgo": 10}` aprueba automáticamente y termina en `end_2`.
- Con `"riesgo": 50` y `"aprobado_analista": true` pasa por el analista y termina en `end_2`; con `"aprobado_analista": false` termina en `end_1`.
- Con `"riesgo": 90` o con `{}` toma el flujo por defecto y termina en `end_1`.
- Ruta aceptada, con las ramas paralelas en el otro orden: `["start_1","task_1","task_2","task_3","task_4","task_8","task_7","task_9","end_2"]`
- Ruta rechazada (`NO_TRANSITION` en el índice 6, esperaba `task_8`): `["start_1","task_1","task_2","task_3","task_5","task_7","task_9","end_2"]`, porque falta una de las ramas paralelas.
- Ruta rechazada (`NO_TRANSITION` en el índice 5): `["start_1","task_1","task_2","task_3","task_4","end_1"]`, porque una solicitud aprobada no puede terminar como rechazada.

## 07-gestion-incidentes.bpmn

17 nodos y 19 flujos, dentro de un pool `Mesa de servicios` con tres carriles: `Mesa de ayuda`, `Soporte nivel 2` y `Atención al cliente`.

- Símbolos: `task_1` registrar incidente, `task_2` diagnosticar en nivel 1, `task_3` notificar a gerencia (HTTP), `task_4` asignar especialista, `task_5` aplicar solución, `task_6` verificar con el cliente, `task_7` escalar al proveedor (HTTP), `task_8` registrar inconformidad, `task_9` cerrar incidente, `end_1` escalado, `end_2` resuelto.
- `/compile` devuelve los carriles en `metadata.lanes` y el nombre del pool en `metadata.participant_name`. El FlowSpec agrupa los nodos en bloques `lane "..."`.
- `/compile` informa un `VALID_LOOP` entre `task_5`, `task_6` y `task_8`: mientras el cliente no esté conforme, se vuelve a aplicar una solución.
- `/simulate` con `{"severidad": 2, "cliente_conforme": true, "reintentos": 0}` pasa por nivel 1 y termina en `end_2`.
- Con `"severidad": 5` toma las ramas paralelas (`task_3` y `task_4`) antes de aplicar la solución.
- Con `{"severidad": 2, "cliente_conforme": false, "reintentos": 3}` termina en `end_1`.
- Con `{"severidad": 2, "cliente_conforme": false, "reintentos": 0}` los datos nunca cambian, así que la simulación repite el ciclo hasta `MAX_STEPS_EXCEEDED`. Para mostrar el ciclo conviene `/validate-trace`.
- Ruta aceptada, con una vuelta por el ciclo: `["start_1","task_1","task_2","task_5","task_6","task_8","task_5","task_6","task_9","end_2"]`
- Ruta aceptada, crítica y escalada al proveedor: `["start_1","task_1","task_4","task_3","task_5","task_6","task_7","end_1"]`
- Ruta rechazada (`NO_TRANSITION` en el índice 6, esperaba `task_5`): `["start_1","task_1","task_2","task_5","task_6","task_8","task_9","end_2"]`, porque después de una inconformidad hay que aplicar otra solución.
- Ruta rechazada (`NO_TRANSITION` en el índice 3, esperaba `task_4`): `["start_1","task_1","task_3","task_5","task_6","task_9","end_2"]`, porque falta una de las ramas paralelas.
