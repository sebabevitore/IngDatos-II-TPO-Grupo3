"""50 vehículos enviando telemetría concurrente a través del CU-02 real.

Ubicación: app/simular_telemetria.py, dentro del repositorio del TPO.
Ejecutar desde la raíz: python3 -m app.simular_telemetria
Revisar un resultado: python3 -m app.simular_telemetria --solo-verificar CARPETA

Requiere datos maestros y al menos 50 viajes EN_CURSO con vehículos distintos.
No crea viajes, no escribe directamente mediciones ni borra datos existentes.
Todos los envíos pasan por app.telemetria.registrar_telemetria.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import threading
import time
from uuid import UUID, uuid4, uuid5


class SimulacionError(RuntimeError):
    pass


def comprobar(condicion, mensaje):
    if not condicion:
        raise SimulacionError(mensaje)


def guardar(path, objeto):
    path = Path(path)
    temporal = path.with_suffix(path.suffix + '.tmp')
    temporal.write_text(json.dumps(objeto, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporal.replace(path)


def fecha(datos):
    return datetime.fromisoformat(datos['fecha_hora'].replace('Z', '+00:00')).astimezone(timezone.utc)


def milisegundos(datos):
    return int(fecha(datos).timestamp() * 1000)


def abrir_motores(stack):
    from app.conexiones import conectar_mongodb, conectar_cassandra, conectar_redis
    mongo = conectar_mongodb(); stack.callback(mongo.close)
    cluster, cassandra = conectar_cassandra(); stack.callback(cluster.shutdown)
    redis = conectar_redis(); stack.callback(redis.close)
    return mongo, cassandra, redis


def seleccionar_vehiculos(mongo, redis, cantidad):
    """Usa viajes reales, evitando emitir para vehículos repetidos o averiados."""
    db = mongo['logistica_flota']
    maestros = {str(v.get('patente') or v['_id']): v for v in db.vehiculos.find({})}
    viajes = list(db.viajes.find({'estado': 'EN_CURSO'}))
    por_vehiculo = {}
    for viaje in viajes:
        patente = viaje.get('vehiculo_patente') or viaje.get('id_vehiculo')
        if patente:
            por_vehiculo.setdefault(str(patente), []).append(viaje)
    resultado = []
    for patente in sorted(por_vehiculo):
        grupo = por_vehiculo[patente]
        if len(grupo) != 1 or patente not in maestros:
            continue
        if maestros[patente].get('estado') in ('AVERIADO', 'EN_MANTENIMIENTO', 'BAJA'):
            continue
        actual = redis.hgetall(f'vehiculo:{patente}:estado')
        if actual.get('estado') in ('AVERIADO', 'EN_MANTENIMIENTO'):
            continue
        viaje_id = str(grupo[0]['_id'])
        if actual.get('viaje_id') and actual['viaje_id'] != viaje_id:
            continue
        lat = float(actual.get('latitud', -34.60))
        lon = float(actual.get('longitud', -58.40))
        comprobar(math.isfinite(lat) and -89 <= lat <= 89 and math.isfinite(lon) and -180 <= lon <= 180,
                  f'Posición inicial inválida del vehículo {patente}')
        ultimo = int(actual.get('fecha_hora_ms', 0))
        comprobar(ultimo <= time.time_ns() // 1_000_000,
                  f'{patente} tiene una lectura futura en Redis; revisar el reloj antes de simular')
        resultado.append(dict(vehiculo_patente=patente, viaje_id=viaje_id,
                              latitud=lat, longitud=lon, ultimo_ms=ultimo))
        if len(resultado) == cantidad:
            break
    comprobar(len(resultado) == cantidad,
              f'Se necesitan {cantidad} viajes EN_CURSO con vehículos distintos y operativos; '
              f'se encontraron {len(resultado)}. Cargá los datos de prueba primero.')
    return resultado


def preparar_consultas(cassandra):
    # También comprueba antes del envío que las dos tablas del CU-02 existen.
    columnas = 'id_evento,fecha_hora,viaje_id,vehiculo_patente,dia,latitud,longitud,velocidad,estado_vehiculo'
    return {
        'viaje': cassandra.prepare('SELECT ' + columnas + ' FROM logistica_flota.telemetria_por_viaje_dia '
            'WHERE viaje_id=? AND dia=? AND fecha_hora=? AND id_evento=?'),
        'vehiculo': cassandra.prepare('SELECT ' + columnas + ' FROM logistica_flota.telemetria_por_vehiculo_dia '
            'WHERE vehiculo_patente=? AND dia=? AND fecha_hora=? AND id_evento=?'),
    }


def pico_concurrencia(envios):
    """Máximo de llamadas reales a CU02 superpuestas; no cuenta espera en la barrera."""
    bordes = []
    for envio in envios:
        for intento in envio['intentos']:
            bordes.extend(((intento['inicio'], 1), (intento['fin'], -1)))
    activos = pico = 0
    for _, cambio in sorted(bordes):
        activos += cambio
        pico = max(pico, activos)
    return pico


def enviar_flota(vehiculos, mediciones, intervalo, reintentos, run_id, carpeta, registrar):
    """Un hilo independiente por vehículo. Cada uno conserva el orden de sus lecturas."""
    barrera = threading.Barrier(len(vehiculos), timeout=60)
    detener = threading.Event()
    escritura = threading.Lock()
    resultados = []
    with (carpeta/'eventos.jsonl').open('x', encoding='utf-8') as eventos, \
         (carpeta/'envios.jsonl').open('x', encoding='utf-8') as respuestas:
        def guardar_linea(archivo, registro):
            with escritura:
                archivo.write(json.dumps(registro, ensure_ascii=False) + '\n')
                archivo.flush()

        def emisor(vehiculo, indice):
            lat, lon = vehiculo['latitud'], vehiculo['longitud']
            ultimo_ms = vehiculo['ultimo_ms']
            anterior = None
            velocidad = float(30 + indice % 21)
            barrera.wait()
            for numero in range(mediciones):
                if detener.is_set():
                    break
                inicio = time.monotonic()
                if anterior is not None:
                    # Avance hacia el este a la velocidad informada, según tiempo real transcurrido.
                    km = velocidad * (inicio - anterior) / 3600
                    lon += km / (111.32 * math.cos(math.radians(lat)))
                    lon = (lon + 180) % 360 - 180
                anterior = inicio
                instante_ms = max(time.time_ns() // 1_000_000, ultimo_ms + 1)
                ultimo_ms = instante_ms
                datos = dict(id_evento=str(uuid5(UUID(run_id), f'{vehiculo["vehiculo_patente"]}/{numero}')),
                    vehiculo_patente=vehiculo['vehiculo_patente'], viaje_id=vehiculo['viaje_id'],
                    fecha_hora=datetime.fromtimestamp(instante_ms / 1000, timezone.utc).isoformat(timespec='milliseconds'),
                    latitud=lat, longitud=lon, velocidad=velocidad, estado_vehiculo='EN_MOVIMIENTO')
                # Guardar el payload exacto antes de llamar al CU02 permite auditar un fallo parcial.
                guardar_linea(eventos, datos)
                intentos = []
                ok = False
                error = None
                for intento in range(reintentos + 1):
                    principio = time.monotonic()
                    try:
                        ok, _ = registrar(datos.copy())
                        error = None if ok else 'CU02 devolvió error; consultar el evento en MongoDB'
                    except Exception as exc:
                        ok = False
                        error = type(exc).__name__
                    fin = time.monotonic()
                    intentos.append(dict(inicio=principio, fin=fin, exito=bool(ok)))
                    if ok:
                        break
                    if intento < reintentos:
                        detener.wait(0.5)
                envio = dict(id_evento=datos['id_evento'], vehiculo_patente=vehiculo['vehiculo_patente'],
                             exito=bool(ok), intentos=intentos, error=error)
                guardar_linea(respuestas, envio)
                with escritura:
                    resultados.append(envio)
                # No ejecutar varias llamadas concurrentes para el mismo vehículo.
                if detener.wait(max(0, inicio + intervalo - time.monotonic())):
                    break
        pool = ThreadPoolExecutor(max_workers=len(vehiculos), thread_name_prefix='vehiculo')
        futuros = []
        try:
            for i, vehiculo in enumerate(vehiculos):
                futuros.append(pool.submit(emisor, vehiculo, i))
            for futuro in as_completed(futuros):
                futuro.result()
        except BaseException:
            detener.set()
            barrera.abort()
            raise
        finally:
            pool.shutdown(wait=True)
    return resultados


def leer_lineas(path):
    with Path(path).open(encoding='utf-8') as archivo:
        return [json.loads(linea) for linea in archivo if linea.strip()]


def verificar(carpeta, mongo, cassandra, redis, consultas):
    plan = json.loads((carpeta/'plan.json').read_text(encoding='utf-8'))
    eventos = leer_lineas(carpeta/'eventos.jsonl')
    envios = leer_lineas(carpeta/'envios.jsonl')
    esperados = plan['vehiculos'] * plan['mediciones_por_vehiculo']
    comprobar(len(eventos) == esperados and len({d['id_evento'] for d in eventos}) == esperados,
              'La simulación no generó todos los eventos únicos previstos')
    comprobar(len(envios) == esperados and {e['id_evento'] for e in envios} == {d['id_evento'] for d in eventos},
              'Faltan resultados de envío; la simulación quedó incompleta')
    comprobar(all(e['exito'] for e in envios), 'Hubo envíos fallidos; consultar envios.jsonl y eventos_telemetria')
    pico = pico_concurrencia(envios)
    comprobar(pico >= plan['vehiculos'],
              f'Se observaron {pico} llamadas CU02 simultáneas, menos que los {plan["vehiculos"]} emisores requeridos')
    ultimos = {}
    for d in eventos:
        doc = mongo['logistica']['eventos_telemetria'].find_one({'_id': d['id_evento']})
        comprobar(doc is not None and doc.get('datos') == d and doc.get('estado_procesamiento') == 'COMPLETADO'
                  and doc.get('cassandra_guardado') is True and doc.get('redis_procesado') is True,
                  f'Evento incompleto en MongoDB: {d["id_evento"]}')
        instante = fecha(d)
        for tipo, clave in (('viaje', d['viaje_id']), ('vehiculo', d['vehiculo_patente'])):
            fila = cassandra.execute(consultas[tipo], (clave, instante.date(), instante.replace(tzinfo=None), UUID(d['id_evento']))).one()
            comprobar(fila is not None and str(fila.id_evento) == d['id_evento']
                      and fila.viaje_id == d['viaje_id'] and fila.vehiculo_patente == d['vehiculo_patente']
                      and fila.fecha_hora == instante.replace(tzinfo=None) and str(fila.dia) == instante.date().isoformat()
                      and fila.latitud == d['latitud'] and fila.longitud == d['longitud']
                      and fila.velocidad == d['velocidad'] and fila.estado_vehiculo == d['estado_vehiculo'],
                      f'Medición ausente o distinta en Cassandra ({tipo}): {d["id_evento"]}')
        anterior = ultimos.get(d['vehiculo_patente'])
        if anterior is None or milisegundos(d) > milisegundos(anterior):
            ultimos[d['vehiculo_patente']] = d
    comprobar(len(ultimos) == plan['vehiculos'], 'No participaron todos los vehículos')
    for patente, d in ultimos.items():
        estado = redis.hgetall(f'vehiculo:{patente}:estado')
        comprobar(estado.get('fecha_hora_ms') == str(milisegundos(d)) and estado.get('viaje_id') == d['viaje_id']
                  and estado.get('estado') == d['estado_vehiculo']
                  and all(estado.get(k) is not None and float(estado[k]) == d[k] for k in ('latitud','longitud','velocidad')),
                  f'Redis no coincide con la última lectura de {patente}; pudo haber recibido datos posteriores')
    return dict(estado='SIMULACION_VERIFICADA', motores_reales=True, vehiculos=plan['vehiculos'],
                mediciones=esperados, eventos_mongodb_completados=esperados,
                filas_cassandra_por_viaje=esperados, filas_cassandra_por_vehiculo=esperados,
                estados_redis_verificados=len(ultimos), maximo_cu02_en_curso=pico,
                reintentos=sum(len(e['intentos']) - 1 for e in envios))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vehiculos', type=int, default=50)
    parser.add_argument('--mediciones-por-vehiculo', type=int, default=5)
    parser.add_argument('--intervalo', type=float, default=2.0, help='Segundos mínimos entre inicios de lecturas de cada vehículo')
    parser.add_argument('--reintentos', type=int, default=1)
    parser.add_argument('--salida', type=Path, help='Carpeta nueva para esta simulación')
    parser.add_argument('--solo-verificar', type=Path, metavar='CARPETA')
    args = parser.parse_args(argv)
    if not 50 <= args.vehiculos <= 100: parser.error('--vehiculos debe estar entre 50 y 100')
    if not 1 <= args.mediciones_por_vehiculo <= 1000: parser.error('mediciones por vehículo debe estar entre 1 y 1000')
    if not math.isfinite(args.intervalo) or args.intervalo < 0.1: parser.error('--intervalo debe ser al menos 0.1 segundos')
    if not 0 <= args.reintentos <= 3: parser.error('--reintentos debe estar entre 0 y 3')
    if args.solo_verificar and args.salida: parser.error('--salida y --solo-verificar no se combinan')
    run_id = str(uuid4())
    carpeta = args.solo_verificar or args.salida or Path('simulaciones_telemetria') / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + run_id[:8])
    if args.solo_verificar:
        if not (carpeta/'plan.json').is_file():
            parser.error('No existe un plan de simulación en esa carpeta')
    else:
        try:
            carpeta.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            parser.error('--salida debe ser una carpeta nueva; usar --solo-verificar para revisar una existente')
        guardar(carpeta/'resumen.json', dict(estado='EN_PREPARACION', motores_reales=False))
    print(f'Resultados: {carpeta.resolve()}', flush=True)
    try:
        with ExitStack() as stack:
            mongo, cassandra, redis = abrir_motores(stack)
            consultas = preparar_consultas(cassandra)
            if not args.solo_verificar:
                vehiculos = seleccionar_vehiculos(mongo, redis, args.vehiculos)
                guardar(carpeta/'plan.json', dict(id_simulacion=run_id, vehiculos=args.vehiculos,
                    mediciones_por_vehiculo=args.mediciones_por_vehiculo, intervalo=args.intervalo,
                    participantes=vehiculos, fecha_inicio_utc=datetime.now(timezone.utc).isoformat()))
                from app.telemetria import registrar_telemetria
                print(f'Iniciando {len(vehiculos)} emisores concurrentes; cada uno enviará '
                      f'{args.mediciones_por_vehiculo} mediciones mediante CU-02.', flush=True)
                envios = enviar_flota(vehiculos, args.mediciones_por_vehiculo, args.intervalo,
                                      args.reintentos, run_id, carpeta, registrar_telemetria)
                print(f'Envíos terminados: {sum(e["exito"] for e in envios)}/{len(envios)}. '
                      'Verificando lo persistido...', flush=True)
            reporte = verificar(carpeta, mongo, cassandra, redis, consultas)
            guardar(carpeta/'verificacion.json', reporte)
            if not args.solo_verificar:
                guardar(carpeta/'resumen.json', reporte)
            print(json.dumps(reporte, ensure_ascii=False, indent=2))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        detalle = str(error) if isinstance(error, SimulacionError) else type(error).__name__
        reporte = dict(estado='ERROR', motores_reales=False, detalle=detalle,
                       nota='No se certifica la simulación; conservar eventos y consultar los errores del CU02.')
        guardar(carpeta/('verificacion.json' if args.solo_verificar else 'resumen.json'), reporte)
        print(f'No se completó la verificación: {detalle}', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
