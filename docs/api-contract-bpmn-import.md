# Contrato de API: importación BPMN y diagnósticos

Contrato entre el backend (FastAPI) y el frontend (Angular + bpmn-js) para la importación de diagramas BPMN.
Los ejemplos de este documento fueron obtenidos ejecutando la API real; no son ilustrativos.

- Base URL local: `http://localhost:8000` (Swagger en `/docs`).
- Todas las claves de diagnóstico están en `camelCase`, y también toda la respuesta de `/import`. El resto de la respuesta de `compile` (`metadata`, `formal_analysis`, ...) conserva `snake_case`.
- Los IDs de BPMN (`elementId`) son **los originales del XML**, los mismos que usa bpmn-js. Sirven para resaltar elementos en el canvas.

## 1. Endpoints que reciben BPMN

| Método | Ruta | Entrada | Uso |
|---|---|---|---|
| POST | `/api/v1/processes/compile` | `multipart/form-data`, campo `files` (exactamente 1 archivo `.bpmn` o `.xml`) | Importa, analiza, emite FlowSpec y genera Ruby |
| POST | `/api/v1/processes/simulate` | `multipart/form-data`, campo `file` (`.bpmn`) **o** `flowspec_code`; opcional `input_data` (JSON string) | Simulación sin estado |
| POST | `/api/v1/processes/import` | `multipart/form-data`, campo `file` (exactamente 1 archivo `.bpmn` o `.xml`) | **Solo importa**: devuelve el modelo y los diagnósticos, sin análisis, FlowSpec, Ruby ni persistencia |

Los tres importan el XML con las mismas reglas. `compile` y `simulate` se detienen (`422`) cuando el análisis no puede ejecutarse; `import` responde `200` en ese caso para que el diagrama pueda mostrarse.

### 1.1 `POST /api/v1/processes/import`

**Petición:** `multipart/form-data` con un único campo `file`. Se aplican las reglas de carga del servicio de importación (una sola extensión válida: `.bpmn` o `.xml`; otro caso responde `INVALID_UPLOAD`).

**Respuestas:**

| HTTP | Cuándo | Cuerpo |
|---|---|---|
| `200` | Se pudo construir el modelo, aunque haya advertencias o el análisis esté bloqueado | `{ "supported", "diagnostics", "document" }` |
| `422` | No se pudo importar (hay diagnósticos `error`) | `{ "detail": { "message", "diagnostics": [errores] } }` (igual que `compile`, ver 2.2) |
| `422` | Falta el campo `file` | lista de errores de validación de FastAPI (ver 2.4) |

**Campos de la respuesta `200`:**

| Campo | Descripción |
|---|---|
| `supported` | `true` si el **análisis formal puede ejecutarse** sobre esta importación (ningún diagnóstico tiene `blocksAnalysis: true`). **No** significa "el diagrama es BPMN válido": un diagrama importable con `supported: false` se puede visualizar igual |
| `diagnostics` | **Todos** los diagnósticos (`error` no puede aparecer aquí; sí `warning` e `info`, bloqueantes o no) con la forma de la sección 3 |
| `document` | El modelo importado (ver abajo) |

**Forma de `document`** (todas las claves en `camelCase`; los nombres de atributos de extensión son datos del XML y se devuelven tal cual):

| Ruta | Contenido |
|---|---|
| `document` | `definitionsId`, `name`, `targetNamespace`, `sourceLine`, `participants[]`, `processes[]`, `extensions`, `unrecognized[]` |
| `processes[]` | `id`, `name`, `isExecutable`, `documentation`, `sourceLine`, `participant`, `laneSets[]`, `nodes[]`, `sequenceFlows[]`, `extensions`, `unrecognized[]`. Se devuelven **todos** los procesos del documento |
| `laneSets[].lanes[]` | `id`, `name`, `flowNodeRefs[]`, `childLaneSet`, `sourceLine` |
| `nodes[]` | `id` (ID BPMN original), `name`, `bpmnType` (tag BPMN), `nodeType` (tipo normalizado), `support` (`analyzable`, `preserved` o `unsupported`), `documentation`, `defaultFlowId`, `incoming[]` y `outgoing[]` (IDs de flujos), `sourceLine`, `extensions`, `unrecognized[]`. Según el tipo, además: `scriptFormat` y `script` (`scriptTask`), `calledElement` (`callActivity`), `source` (nodos `unsupported`: el elemento original completo) |
| `sequenceFlows[]` | `id`, `sourceRef`, `targetRef`, `name`, `condition` (`{ text, language, xsiType }` con el texto sin modificar, o `null`), `isDefault`, `documentation`, `sourceLine`, `extensions`, `unrecognized[]` |
| `extensions` | `{ attributes, elements[] }`: atributos y elementos de otros namespaces (por ejemplo Camunda), identificados por URI. Atributo: clave `"{namespaceUri}nombre"`. Elemento: `{ namespaceUri, localName, attributes, text, children[] }` |
| `unrecognized[]` | Contenido BPMN que FlowRouby no interpreta, con la misma forma genérica que `extensions.elements[]`. No se pierde |

Los nodos no soportados (`nodeType: "unsupported"`) **aparecen en `nodes[]`** con su ID, para poder resaltarlos en el canvas.

**Ejemplo: proceso de 3 nodos importado correctamente** (respuesta real, `200`):

```json
{
  "supported": true,
  "diagnostics": [],
  "document": {
    "definitionsId": "Defs",
    "name": null,
    "targetNamespace": null,
    "sourceLine": 2,
    "participants": [],
    "processes": [
      {
        "id": "P",
        "name": "Demo",
        "isExecutable": true,
        "documentation": null,
        "sourceLine": 3,
        "participant": null,
        "laneSets": [],
        "nodes": [
          {
            "id": "Start",
            "name": "Begin",
            "bpmnType": "startEvent",
            "nodeType": "start_event",
            "support": "analyzable",
            "documentation": null,
            "defaultFlowId": null,
            "incoming": [],
            "outgoing": [
              "f1"
            ],
            "sourceLine": 4,
            "extensions": {
              "attributes": {},
              "elements": []
            },
            "unrecognized": []
          },
          {
            "id": "Task_A",
            "name": "Register request",
            "bpmnType": "userTask",
            "nodeType": "user_task",
            "support": "analyzable",
            "documentation": null,
            "defaultFlowId": null,
            "incoming": [
              "f1"
            ],
            "outgoing": [
              "f2"
            ],
            "sourceLine": 5,
            "extensions": {
              "attributes": {
                "{http://camunda.org/schema/1.0/bpmn}formKey": "form1"
              },
              "elements": []
            },
            "unrecognized": []
          },
          {
            "id": "End",
            "name": "Done",
            "bpmnType": "endEvent",
            "nodeType": "end_event",
            "support": "analyzable",
            "documentation": null,
            "defaultFlowId": null,
            "incoming": [
              "f2"
            ],
            "outgoing": [],
            "sourceLine": 6,
            "extensions": {
              "attributes": {},
              "elements": []
            },
            "unrecognized": []
          }
        ],
        "sequenceFlows": [
          {
            "id": "f1",
            "sourceRef": "Start",
            "targetRef": "Task_A",
            "name": null,
            "condition": null,
            "isDefault": false,
            "documentation": null,
            "sourceLine": 7,
            "extensions": {
              "attributes": {},
              "elements": []
            },
            "unrecognized": []
          },
          {
            "id": "f2",
            "sourceRef": "Task_A",
            "targetRef": "End",
            "name": null,
            "condition": null,
            "isDefault": false,
            "documentation": null,
            "sourceLine": 8,
            "extensions": {
              "attributes": {},
              "elements": []
            },
            "unrecognized": []
          }
        ],
        "extensions": {
          "attributes": {},
          "elements": []
        },
        "unrecognized": []
      }
    ],
    "extensions": {
      "attributes": {},
      "elements": []
    },
    "unrecognized": []
  }
}
```

**Ejemplo: diagrama con un subproceso** (`200`, `supported: false`). Se muestran `supported`, `diagnostics` y el nodo `Sub` de `document.processes[0].nodes` (fragmento de la respuesta real):

```json
{
  "supported": false,
  "diagnostics": [
    {
      "severity": "warning",
      "code": "UNSUPPORTED_ELEMENT",
      "message": "<subProcess> is not supported yet; it is kept as an opaque node.",
      "elementId": "Sub",
      "elementType": "subProcess",
      "processId": "P",
      "blocksAnalysis": true,
      "line": 5
    }
  ]
}
```

```json
{
  "id": "Sub",
  "name": "Nested",
  "bpmnType": "subProcess",
  "nodeType": "unsupported",
  "support": "unsupported",
  "documentation": null,
  "defaultFlowId": null,
  "incoming": [
    "f1"
  ],
  "outgoing": [
    "f2"
  ],
  "sourceLine": 5,
  "extensions": {
    "attributes": {},
    "elements": []
  },
  "unrecognized": [],
  "source": {
    "namespaceUri": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "localName": "subProcess",
    "attributes": {
      "id": "Sub",
      "name": "Nested"
    },
    "text": null,
    "children": [
      {
        "namespaceUri": "http://www.omg.org/spec/BPMN/20100524/MODEL",
        "localName": "task",
        "attributes": {
          "id": "Inner"
        },
        "text": null,
        "children": []
      }
    ]
  }
}
```

**Ejemplo: no se puede importar** (`422`, proceso sin `endEvent`):

```json
{
  "detail": {
    "message": "The BPMN document could not be imported.",
    "diagnostics": [
      {
        "severity": "error",
        "code": "NO_END_EVENT",
        "message": "FlowRouby import profile: process 'P' must contain an endEvent. This is a FlowRouby restriction, not a general BPMN rule.",
        "elementId": null,
        "elementType": "endEvent",
        "processId": "P",
        "blocksAnalysis": false,
        "line": 3
      }
    ]
  }
}
```

**Ejemplo: extensión inválida** (`422`, archivo `demo.txt`):

```json
{
  "detail": {
    "message": "The BPMN document could not be imported.",
    "diagnostics": [
      {
        "severity": "error",
        "code": "INVALID_UPLOAD",
        "message": "Invalid file extension for 'demo.txt'. Expected a .bpmn or .xml file.",
        "elementId": null,
        "elementType": null,
        "processId": null,
        "blocksAnalysis": false,
        "line": null
      }
    ]
  }
}
```

## 2. Respuestas

### 2.1 Éxito: `200`
`compile` devuelve, entre otros, estos bloques relacionados con la importación:

```json
{
  "metadata": {
    "process_id": "P",
    "process_name": "Demo",
    "participant_name": null,
    "is_executable": null,
    "lanes": [],
    "node_count": 3,
    "edge_count": 2
  },
  "validation": {
    "valid": true,
    "diagnostics": [],
    "semantic_errors": [],
    "semantic_warnings": []
  }
}
```

- `process_name` cae al `process_id` si el proceso no tiene nombre.
- `is_executable` es `null` cuando el atributo no está en el XML.
- `validation.diagnostics` trae las advertencias e informaciones que **no bloquean** (ver 3). Puede venir vacío.
- Otros bloques de la respuesta (`data_contract`, `formal_analysis`, `flowspec`, `generated_ruby`) no cambian con esta intervención.

### 2.2 El documento no se pudo importar: `422`
Hay errores de estructura. No se construye ningún modelo.

```json
{
  "detail": {
    "message": "The BPMN document could not be imported.",
    "diagnostics": [
      {
        "severity": "error",
        "code": "INVALID_REFERENCE",
        "message": "The sequenceFlow 'f1' references the unknown targetRef 'X'.",
        "elementId": "f1",
        "elementType": "sequenceFlow",
        "processId": "P",
        "blocksAnalysis": false,
        "line": 4
      }
    ]
  }
}
```

`detail.diagnostics` contiene **todos** los errores encontrados, no solo el primero.

### 2.3 Se importó, pero no se puede analizar: `422`
El documento es válido pero contiene algo que FlowRouby todavía no interpreta.

```json
{
  "detail": {
    "message": "The BPMN document was imported but cannot be analyzed yet.",
    "diagnostics": [
      {
        "severity": "warning",
        "code": "UNSUPPORTED_ELEMENT",
        "message": "<subProcess> is not supported yet; it is kept as an opaque node.",
        "elementId": "SP",
        "elementType": "subProcess",
        "processId": "P",
        "blocksAnalysis": true,
        "line": 4
      }
    ]
  }
}
```

Aquí `detail.diagnostics` contiene **solo los diagnósticos que bloquean** (`blocksAnalysis: true`). Las demás advertencias no se incluyen en este caso.

Para mostrar el diagrama aunque no pueda analizarse, usar `POST /api/v1/processes/import` (1.1), que responde `200` con el modelo y `supported: false`.

### 2.4 Otros `422` (no son diagnósticos de importación)
Distingue la forma de `detail`:

| Situación | Forma de `detail` |
|---|---|
| Archivo con extensión inválida o más de un archivo | objeto con `message` y `diagnostics` (código `INVALID_UPLOAD`) |
| No se envió el campo `files` | lista de errores de validación de FastAPI: `[{ "type", "loc", "msg", "input" }]` |
| `input_data` no es un JSON objeto (simulate) | `{ "message": "..." }` |
| Error de sintaxis FlowSpec generado | `{ "message", "line", "column", "flowspec_code" }` |

Regla práctica para el frontend: si `detail` es un **array**, es validación de FastAPI; si es un **objeto** con `diagnostics`, es el contrato de este documento.

## 3. Modelo de diagnóstico

| Campo | Tipo | Descripción |
|---|---|---|
| `severity` | `"error"` \| `"warning"` \| `"info"` | Gravedad |
| `code` | string | Código estable (tabla 4) |
| `message` | string | Texto legible en inglés (no usar para lógica) |
| `elementId` | string \| null | ID BPMN original del elemento afectado |
| `elementType` | string \| null | Tag BPMN original (`sequenceFlow`, `subProcess`, ...) |
| `processId` | string \| null | Proceso al que pertenece |
| `blocksAnalysis` | boolean | Si es `true`, el análisis formal no se ejecuta |
| `line` | number \| null | Línea de la etiqueta de apertura del elemento en el XML importado |

Las tres situaciones que distingue el backend:

1. **`error`**: no se puede construir un modelo consistente. HTTP 422.
2. **`warning` / `info` con `blocksAnalysis: false`**: el diagrama se importa y se analiza; el usuario debe estar informado.
3. **`warning` con `blocksAnalysis: true`**: el diagrama se importó, pero el análisis no se ejecuta. HTTP 422 (ver 2.3).

## 4. Códigos

Las reglas marcadas como *perfil FlowRouby* son restricciones explícitas del alcance actual del proyecto, **no** reglas universales de validez de BPMN.

| Código | Severidad | Bloquea | Origen | Significado |
|---|---|---|---|---|
| `INVALID_UPLOAD` | error | n/a | petición | Más de un archivo o extensión distinta de `.bpmn`/`.xml` |
| `XML_MALFORMED` | error | n/a | XML | XML mal formado o con DTD/entidades (rechazado por seguridad) |
| `NOT_BPMN` | error | n/a | BPMN | La raíz no es `definitions` en el namespace BPMN 2.0 |
| `NO_PROCESS` | error | n/a | BPMN | No hay ningún `process` |
| `MISSING_ID` | error | n/a | BPMN | Falta un `id` obligatorio |
| `DUPLICATE_ID` | error | n/a | BPMN | ID repetido (incluye colisión entre nodos y flujos) |
| `MISSING_REF_ATTRIBUTE` | error | n/a | BPMN | `sequenceFlow` sin `sourceRef` o `targetRef` |
| `INVALID_REFERENCE` | error | n/a | BPMN | Referencia a un elemento inexistente (flujo o lane) |
| `NO_START_EVENT` | error | n/a | perfil FlowRouby | El proceso no tiene `startEvent` |
| `NO_END_EVENT` | error | n/a | perfil FlowRouby | El proceso no tiene `endEvent` |
| `UNSUPPORTED_ELEMENT` | warning | **sí** | perfil FlowRouby | Elemento preservado como nodo opaco (subproceso, eventos intermedios, ...) |
| `MULTIPLE_START_EVENTS` | warning | **sí** | perfil FlowRouby | Varios `startEvent`; pendiente de definir su representación formal |
| `MULTIPLE_PROCESSES` | warning | **sí** | perfil FlowRouby | El documento tiene más de un proceso |
| `PRESERVED_NOT_ANALYZABLE` | warning | no | perfil FlowRouby | `callActivity` o `inclusiveGateway`: importados y válidos para generar código, pero fuera del perfil inicial de análisis; los resultados del análisis que los involucren son provisionales |
| `DISCONNECTED_NODE` | warning | no | BPMN | Nodo sin conexiones |
| `GATEWAY_WITHOUT_OUTGOING` | warning | no | BPMN | Compuerta sin flujos de salida |
| `XOR_FLOW_WITHOUT_CONDITION_OR_DEFAULT` | warning | no | BPMN | Salida de XOR sin condición y sin ser la default |
| `IGNORED_ELEMENT` | info | no | perfil FlowRouby | Elemento no relevante para el análisis (anotaciones, asociaciones, layout BPMNDI, ...) |

Varios `endEvent` están permitidos y no generan diagnóstico.

## 5. Uso recomendado en el frontend

- Resaltar en el canvas usando `elementId` (ej. `canvas.addMarker(elementId, 'fr-error')`). Puede ser `null`: mostrar entonces solo el mensaje.
- Mostrar `line` como ayuda para localizar el problema en el XML original.
- Decidir la lógica por `code`, `severity` y `blocksAnalysis`; **nunca** por el texto de `message`.
- Tratar `info` como no intrusivo (por ejemplo, un contador), `warning` como aviso visible y `error` como bloqueo.
- `bpmn-js` valida y muestra el diagrama por su cuenta: un `422` del backend no impide visualizar el XML en el canvas.
- Para mostrar el modelo importado y sus diagnósticos sin ejecutar análisis, llamar a `/import` y usar `supported` solo para decidir si ofrecer `compile`/`simulate`.

## 6. Limitaciones y pendientes

1. **No hay CORS configurado.** El backend no incluye `CORSMiddleware`; el frontend en otro origen será bloqueado por el navegador hasta que se configure.
2. **Sin persistencia.** Nada se guarda; cada petición importa de cero (MongoDB queda para una etapa posterior).
3. `message` está en inglés y no es estable; el frontend debe traducir por `code`.
4. Los endpoints `/api/v1/flowspec/compile` y la simulación sobre `flowspec_code` no forman parte de este contrato.
5. En `compile`, un `process` sin atributo `isExecutable` devuelve `is_executable: null`.
