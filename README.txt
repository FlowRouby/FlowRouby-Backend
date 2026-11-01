BPMN TO FLOWSPEC AND RUBY COMPILER API


Esta API en FastAPI compila diagramas BPMN 2.0 con extensiones de Camunda hacia el lenguaje intermedio FlowSpec, realiza analisis formal mediante Automatas Finitos y Expresiones Regulares, genera plantillas de codigo para Ruby on Rails con Sidekiq y permite simular flujos sin persistir instancias.


1. INSTALACION Y PUESTA EN MARCHA


Primero entra a la carpeta backend, crea un entorno virtual y activalo:

    cd backend
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1


Segundo, instala las dependencias del proyecto:

    pip install -r requirements.txt


Tercero, levanta el servidor con uvicorn indicando el puerto que prefieras, por ejemplo el 8080:

    python -m uvicorn app.main:app --reload --port XXXX


Cuarto, entra al Swagger desde tu navegador en la direccion http://localhost:XXXX/docs y veras todos los endpoints disponibles listos para probar.


2. ENDPOINTS DISPONIBLES


POST /api/v1/processes/compile

Compila un diagrama BPMN pasando por todas las etapas del compilador.

Que requiere para la peticion:
Recibe en el campo files un unico archivo .bpmn por peticion.

Que retorna:
Retorna metadata y validation con los datos generales del proceso, sus carriles y el resultado de las validaciones estructurales y semanticas.
Retorna data_contract con las variables de entrada requeridas, las salidas producidas y un sample_payload de ejemplo listo para usar en simulacion.
Retorna el Automata Finito dentro de formal_analysis, incluyendo la clasificacion Tipo 3, la tabla de estados y transiciones del DFA con sus subconjuntos de estados, las regiones de flags para compuertas paralelas o inclusivas, la expresion regular de las trazas del flujo, las rutas aciclicas y el diagnostico de nodos muertos, deadlocks y ciclos infinitos.
Retorna flowspec con la representacion del flujo en el lenguaje intermedio FlowSpec y su tabla de simbolos.
Retorna generated_ruby con el template generado en Ruby para Rails y Sidekiq dentro del diccionario files, incluyendo el orquestador del workflow, los objetos de formulario para tareas de usuario, los jobs de Sidekiq con llamadas HTTP para conectores, los stubs de reglas de negocio y la suite de pruebas en RSpec.


POST /api/v1/flowspec/compile

Compila directamente codigo escrito en el lenguaje intermedio FlowSpec sin necesidad de subir un archivo XML BPMN.

Que requiere para la peticion:
Recibe un cuerpo JSON con el campo flowspec_code que contiene la declaracion del proceso en sintaxis FlowSpec. La guia de sintaxis de este lenguaje se encuentra en docs/flowspec_reference.md.

Que retorna:
Retorna metadata, validation, data_contract, el bloque flowspec validado semanticamente con su tabla de simbolos y generated_ruby con los archivos Ruby generados dentro de files.


POST /api/v1/processes/simulate

Ejecuta una simulacion del flujo evaluando condiciones de compuertas, formularios, conectores HTTP simulados y bucles sin guardar instancias en base de datos.

Que requiere para la peticion:
Recibe el archivo .bpmn en el campo file o bien el codigo en texto en el campo flowspec_code.
Recibe ademas en el campo input_data un objeto JSON en formato texto con las variables de entrada y respuestas de formularios necesarias para evaluar los caminos del flujo. Puedes tomar directamente el sample_payload que entrega el endpoint de compilacion.

Que retorna:
Retorna completed y terminated_reason indicando si el flujo alcanzo satisfactoriamente un evento de fin.
Retorna accepted_by_dfa confirmando si la secuencia de nodos recorrida fue aceptada por el Automata Finito Determinista del proceso.
Retorna visited_nodes y step_logs con la secuencia ordenada de nodos visitados y el registro paso a paso de las decisiones tomadas.
Retorna http_requests_simulated con el detalle de las peticiones HTTP simuladas en las tareas de servicio.
Retorna final_context con el estado final de todas las variables al concluir la simulacion.


GET /health

Verifica que el servidor este activo y responde con el estado ok.


3. ELEMENTOS BPMN SOPORTADOS Y UBICACION DE SU DICCIONARIO


Eventos soportados:
Soporta startEvent y endEvent, incluyendo formularios de inicio mediante atributos formRef, formKey y campos formField de Camunda.


Tareas soportadas:
Soporta userTask con definicion de campos formData y referencias formRef.
Soporta serviceTask tanto con conectores HTTP http-connector como con clases delegadas camunda:class, ademas de las variantes genericas task, sendTask y receiveTask.
Soporta scriptTask con extraccion del bloque de codigo script.
Soporta manualTask para actividades manuales del proceso.
Soporta businessRuleTask con atributos decisionRef y resultVariable en modo stub preparado para futura integracion con tablas DMN.
Soporta callActivity para invocacion de subprocesos externos mediante calledElement y mapeo de variables de entrada y salida.


Compuertas soportadas:
Soporta exclusiveGateway con evaluacion de expresiones condicionales y flujo por defecto.
Soporta parallelGateway para bifurcacion y sincronizacion de ramas concurrentes mediante vectores de flags en el automata.
Soporta inclusiveGateway para activacion y sincronizacion de subconjuntos de ramas condicionales.


Ubicacion del diccionario de elementos en el codigo:
El catalogo de tipos de nodos y estructuras del modelo intermedio se encuentra definido en la enumeracion NodeType dentro de backend/app/features/processes/intermediate_model/models.py.
El mapeo directo desde las etiquetas XML de BPMN y Camunda hacia estos nodos se ubica en el metodo _parse_flow_node dentro de backend/app/features/processes/bpmn_importer/importer.py.
El diccionario de palabras reservadas y tokens equivalentes en el lenguaje intermedio FlowSpec se encuentra en el diccionario KEYWORDS dentro de backend/app/features/flowspec/lexer/lexer.py.


