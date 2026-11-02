# Sistema de logística y tracking de flota

Ingeniería de Datos II, Grupo 3. Python, MongoDB, Cassandra, Redis y Neo4j.

## Instalación y ejecución

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Configurar credenciales locales en .env; nunca subir ese archivo.
docker compose up -d
python -m app.main --check
python -m app.cargar_datos --mediciones 50000
python -m app.main
```

Esperar los cuatro servicios saludables. El cargador inicializa los esquemas y genera/verifica datos reproducibles. No borra datos ajenos. El entorno es un laboratorio de una instancia por motor, no un despliegue de alta disponibilidad.

## Operaciones y recuperación

CU01, CU05 y CU06 escriben intención, entradas, claves y fotografías anteriores en `logistica_flota.operaciones` antes de modificar datos. Se registra un paso iniciado antes de enviar la escritura: si se pierde el ACK, la recuperación también lo compensa. Las fotografías revierten únicamente documentos marcados por esa operación; las reservas se liberan solo por su propietario. Una compensación fallida queda pendiente y mantiene bloqueados los recursos.

Enviar `id_operacion` o `clave_idempotencia` estable en el diccionario de entrada para reintentar un pedido. La misma clave con datos diferentes se rechaza. Repetir un pedido completo con la misma clave devuelve su resultado con `repetida=true`; sin clave explícita se calcula una identidad del contenido y se rechaza la repetición. Un pedido compensado conserva su resultado: para un nuevo intento de negocio usar una clave nueva.

Los bloqueos durables por paquete, viaje, vehículo y conductor viven en MongoDB y no vencen. Redis mantiene reservas/proyecciones, pero su pérdida no habilita otro escritor. CU01 permite viajes con intervalos compatibles y rechaza superpuestos bajo el mismo bloqueo de recurso. La agenda se consulta en los viajes persistentes; las reservas Redis no representan por sí solas la disponibilidad temporal. Se debe indicar `planificado_por_usuario_id` existente (o que la ruta lo tenga); CU05 hereda el coordinador del viaje si no se proporciona `creada_por_usuario_id`.

```bash
# Compensar operaciones interrumpidas de procesos locales que ya terminaron:
python -m app.recuperar_operaciones
# O recuperar una operación específica:
python -m app.recuperar_operaciones --operacion ID
# Recuperación de eventos GPS:
python -m app.recuperar_pendientes
```

El recuperador no roba un proceso vivo ni uno de otro host: no supone que un timeout significa muerte. El alcance es el laboratorio local; para otro host se necesita confirmar su terminación y un protocolo de fencing distribuido antes de permitir la toma. No cambiar manualmente propietarios o borrar bloqueos para saltarse una operación pendiente. MongoDB debe estar disponible para coordinar. Los lectores de trazabilidad/ETA rechazan recursos con operación pendiente; no hay una transacción global entre motores.

CU05 y CU06 **compensan también si falla Redis al final**, en lugar de devolver éxito con cambios pendientes. Después de una caída anterior a confirmar toda la saga, la política de recuperación es compensar. Si ya se confirmó durablemente, se conserva el resultado y solo se limpian bloqueos remanentes.

## Funciones completadas

- CU01 almacena horarios por parada (recibe `paradas` con `punto_entrega_id` y `hora_planificada`, en el orden de la ruta). Si no se indican, distribuye explícitamente el intervalo previsto de manera uniforme como plan de referencia. Guarda coordinador en viaje y asignaciones; no inventa usuarios.
- CU04 calcula el tiempo restante sobre segmentos del trazado disponible, combinando duración histórica/planificada restante y tiempo a velocidad instantánea con peso 50/50. Detenido, usa el histórico/plan. Sin histórico, prioriza la duración entre horarios de las paradas y usa el tiempo del grafo si faltan esos horarios. Informa llegada, horario previsto y demora. Rechaza posición con más de 300 segundos (configurable `ETA_MAX_EDAD_SEGUNDOS`). Es una aproximación geométrica entre puntos; no incorpora una red vial externa ni un modelo de tráfico.
- CU06 cierra la parada cuando no quedan paquetes activos para ese destino. La demora acumulada es la suma de retrasos positivos de paradas completadas, contada una vez por parada. Guarda completadas, pendientes y demora en el viaje MongoDB y proyecta los valores absolutos en Redis, sin incrementos repetibles.
- CU03 consulta una ventana temporal de umbral + 2 minutos, recorriendo todos los días/páginas necesarios. Una parada prevista se reconoce dentro de 200 metros del punto y +/-15 minutos del horario (`PARADA_TOLERANCIA_MINUTOS`). Es una regla explícita ajustable, no geocodificación vial. Una lectura normal cierra la anomalía; el TTL Redis no determina su fin. Las alertas abiertas Cassandra preservan su ID aunque Redis pierda la clave.
- Una alerta Cassandra parcialmente escrita se compensa usando la clave estable guardada previamente en MongoDB. Si quedó persistida y falta confirmar Redis o emitir el aviso, se completa hacia adelante mediante recuperación. La emisión es en consola y puede repetirse si cae después de imprimir, antes de registrar su finalización.

## Fuentes oficiales y copias

- MongoDB `logistica_flota`: maestros, viajes, paradas, asignaciones, entregas comerciales, métricas y bitácora de sagas. `logistica.eventos_telemetria`: progreso y payload GPS.
- Cassandra: histórico GPS, comprobantes, tiempos y alertas operativas; el orquestador mantiene sus proyecciones por vehículo/viaje y día.
- Redis: posición actual, reservas y proyecciones operativas. No es la autoridad del estado comercial de una entrega.
- Neo4j: conectividad y orden de rutas; CU01/CU05 mantienen el vínculo de viajes con esa red.

La colección MongoDB `alertas` se conserva por compatibilidad con el seed y no se debe consultar como espejo actualizado de CU03. Las rutas/puntos MongoDB aportan metadatos, y el grafo aporta la conectividad. No se incluye un editor genérico de maestros/rutas: cualquier modificación debe mantener explícitamente las representaciones afectadas. No hay un sincronizador que detecte ediciones manuales fuera de los flujos.

## Pruebas y evidencia

```bash
python -m unittest tests.test_reglas -v
TPO_INTEGRACION=1 python -m unittest tests.test_integracion -v
# Reglas, integración y menús CU01-CU07 con logs y huellas del código:
python -m app.verificar_correcciones --integracion
```

Las pruebas reales crean fixtures con prefijos exclusivos, sin vaciar motores ni reiniciar entidades existentes. Guardan evidencia en `evidencias/correcciones`. Los menús guardan sus comprobaciones en `resultados_menus`. La prueba de caída termina un proceso hijo deliberadamente; después verifica la compensación y su repetición. CU08 se verifica en las demostraciones de planificación/rescate/entrega y durante las operaciones pendientes; también existe `python -m app.test_cu08` para su fixture histórica.

Demostraciones individuales nuevas:

```bash
python -m app.menu_cu05 5  # falla Redis final
python -m app.menu_cu05 6  # falla en transferencia parcial
python -m app.menu_cu06 5  # falla Redis final
```

Antes de entregar, actualizar el informe técnico con el comportamiento y las evidencias de esta rama; el informe previo describía la versión anterior.

### Validar el seed después de una simulación

`cargar_datos --solo-validar` exige igualdad exacta con el snapshot original, incluso de la posición Redis. Después de recibir GPS nuevo, ese estado debe ser diferente. Para verificar los datos persistentes sin retroceder la posición actual:

```bash
python -m app.verificar_seed_historico
```

Este comando comprueba MongoDB, Cassandra y Neo4j contra el manifiesto y excluye explícitamente Redis de esa comparación. El estado Redis actualizado se comprueba en la evidencia de la simulación de flota. Ver `docs/IMPLEMENTACION_Y_VALIDACION.md` para secuencias, alcance y evidencia.
