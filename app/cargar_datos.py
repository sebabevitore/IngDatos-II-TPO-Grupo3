"""Modelo determinista independiente de los drivers de bases de datos.

Las fechas son UTC sin tzinfo para BSON/CQL; al serializar se indica UTC.
Los campos id_* duplicados en Viaje adaptan los consumidores CU01 y CU04–08.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from math import cos, radians, sqrt
from uuid import uuid5, NAMESPACE_URL

VERSION = 1
PREFIJO = 'SEED26-'
BASE = datetime(2026, 10, 26, 8)
OWNER = 'tpo-generador-v1'
PK = {
 'telemetria_por_viaje_dia': ('viaje_id','dia','fecha_hora','id_evento'),
 'telemetria_por_vehiculo_dia': ('vehiculo_patente','dia','fecha_hora','id_evento'),
 'alertas_por_viaje_dia': ('viaje_id','dia','fecha_hora','alerta_id'),
 'alertas_por_vehiculo_dia': ('vehiculo_patente','dia','fecha_hora','alerta_id'),
 'alertas_abiertas_por_vehiculo': ('vehiculo_patente','tipo'),
 'confirmaciones_entrega_por_viaje_dia': ('viaje_id','dia','fecha_hora','paquete_codigo'),
 'tiempos_tramo_historico': ('tramo_id','fecha_hora'),
 'tiempos_tramo_por_mes': ('tramo_id','mes','fecha_fin','viaje_id'),
}
PART = {t: keys[:2] if t.endswith('_dia') or t == 'tiempos_tramo_por_mes' else keys[:1]
        for t, keys in PK.items()}


def ident(tipo, n):
    return f'{PREFIJO}{tipo}-{n:05d}'


def distancia(a, b):
    return sqrt(((a['latitud']-b['latitud'])*111.32)**2 +
                ((a['longitud']-b['longitud'])*111.32*cos(radians(a['latitud'])))**2)


def generar(mediciones=50000):
    if mediciones < 50000 or mediciones > 1000000:
        raise ValueError('La entrega requiere entre 50.000 y 1.000.000 mediciones')
    mongo = defaultdict(list)
    cql = defaultdict(list)
    nodes, edges, redis = [], [], {}

    def doc(coll, codigo_tipo, n, **kw):
        d = dict(_id=ident(codigo_tipo,n), seed_owner=OWNER, **kw)
        mongo[coll].append(d)
        return d

    def node(label, key, value, **kw):
        nodes.append(dict(label=label,key=key,value=value,props=dict(seed_owner=OWNER,**kw)))

    def edge(al, ak, av, rel, bl, bk, bv, **props):
        edges.append(dict(al=al,ak=ak,av=av,rel=rel,bl=bl,bk=bk,bv=bv,
                          props=dict(seed_owner=OWNER,**props)))

    coord = doc('contactos','CON',100, tipo='PERSONA', dni=ident('DNI',100),
                nombre='Coordinación sintética', email='coordinacion@example.invalid')
    user = doc('usuarios','USR',0,contacto_id=coord['_id'], username=ident('USR',0),
               rol='COORDINADOR',estado='INACTIVO',password_hash='!SIN_ACCESO_SINTETICO')
    for i in range(100):
        contact = doc('contactos','CON',i,tipo='PERSONA',dni=ident('DNI',i),
                      nombre=f'Conductor sintético {i}',email=f'conductor{i}@example.invalid')
        doc('conductores','COND',i, contacto_id=contact['_id'],nro_licencia=ident('LIC',i),
            vencimiento=datetime(2030,1,1),estado='ASIGNADO' if i<50 else 'DISPONIBLE')
        doc('vehiculos','VEH',i, patente=ident('VEH',i),marca='Flota sintética',modelo='Carga',
            anio=2024,tipo='CAMION',estado='EN_VIAJE' if i<50 else 'DISPONIBLE')
    for i in range(50):
        doc('contactos','CLI',i,tipo='EMPRESA',cuit=ident('CUIT',i),
            razon_social=f'Cliente sintético {i}',email=f'cliente{i}@example.invalid')
    # Cinco corredores con diez puntos cada uno. Las diagonales permiten evitar bloqueos.
    points=[]
    for i in range(50):
        p=doc('puntos_entrega','PTO',i,nombre=f'Depósito sintético {i}',localidad='AMBA',
              provincia='Buenos Aires',direccion=f'Calle de prueba {i}',
              latitud=-34.60+(i//10)*.025,longitud=-58.50+(i%10)*.01)
        points.append(p)
        node('PuntoEntrega','punto_entrega_id',p['_id'],**{k:v for k,v in p.items() if k not in ('_id','seed_owner')})
    tramos={}
    for a in range(50):
        for b in range(50):
            if a==b or not ((a//10==b//10 and abs(a-b) in (1,2)) or
                            (a%10==b%10 and abs(a-b)==10)):
                continue
            km=distancia(points[a],points[b]);tid=ident('TR',a*50+b)
            tramos[a,b]=tid
            edge('PuntoEntrega','punto_entrega_id',points[a]['_id'],'CONECTA',
                 'PuntoEntrega','punto_entrega_id',points[b]['_id'],
                 tramo_id=tid,distancia_km=km,tiempo_estimado_min=km/40*60,habilitado=True)
    routes=[]
    for i in range(25):
        start=(i//5)*10+i%5
        seq=list(range(start,start+4));rid=ident('RUT',i)
        routes.append(seq)
        doc('rutas','RUT',i,nombre=f'Corredor {i}',estado='HABILITADA',
            planificada_por_usuario_id=user['_id'],fecha=BASE,
            puntos=[dict(orden=j+1,punto_entrega_id=points[p]['_id']) for j,p in enumerate(seq)])
        node('Ruta','ruta_id',rid,estado='HABILITADA')
        for j,p in enumerate(seq):
            edge('Ruta','ruta_id',rid,'INCLUYE','PuntoEntrega','punto_entrega_id',points[p]['_id'],orden=j+1)
    latest={}
    for i in range(500):
        vid=ident('VIA',i);veh=ident('VEH',i%100);cond=ident('COND',i%100)
        activo=i>=400 and i%100<50
        start=BASE+timedelta(days=i//100,hours=(i%100)//20)
        n=mediciones//500+(i<mediciones%500)
        seq=routes[i%25];rid=ident('RUT',i%25)
        step_seconds=495/(n-1)
        end=start+timedelta(seconds=495)
        codes=[ident('PAQ',i*4+k) for k in range(4)]
        trip=doc('viajes','VIA',i,ruta_id=rid,id_ruta=rid,vehiculo_patente=veh,id_vehiculo=veh,
                 conductor_id=cond,id_conductor=cond,estado='EN_CURSO' if activo else 'FINALIZADO',
                 paquetes=codes,planificado_por_usuario_id=user['_id'],inicio_planificado=start,
                 fin_planificado=start+(end-start)/(0.8 if activo else 1),fecha_inicio=start,inicio_real=start,
                 fin_real=None if activo else end,fecha_creacion=start-timedelta(days=1),
                 paradas=[dict(orden=j+1,punto_entrega_id=points[p]['_id'],
                              hora_planificada=start+(end-start)*j/3/(0.8 if activo else 1),
                              hora_real=None if activo and j==3 else start+(end-start)*j/3/(0.8 if activo else 1),
                              estado='PENDIENTE' if activo and j==3 else 'COMPLETADA') for j,p in enumerate(seq)])
        node('Viaje','viaje_id',vid,estado=trip['estado'],id_vehiculo=veh,id_conductor=cond)
        edge('Viaje','viaje_id',vid,'ASIGNADO_A','Ruta','ruta_id',rid)
        samples=[]
        length=sum(distancia(points[a],points[b]) for a,b in zip(seq,seq[1:]))
        final_progress=0.8 if activo else 1.0
        spike_delta=105*step_seconds/3600/length
        regular_delta=(final_progress-spike_delta)/(n-2)
        progress=0.0
        for j in range(n):
            if j: progress+=spike_delta if j==n//2 else regular_delta
            progress=min(final_progress,progress)
            segment=min(2,int(progress*3));f=progress*3-segment
            a,b=points[seq[segment]],points[seq[segment+1]]
            speed=105.0 if j==n//2 else round(regular_delta*length/step_seconds*3600,3)
            if j==n-1 and not activo: speed=0.0
            row=dict(viaje_id=vid,vehiculo_patente=veh,fecha_hora=start+timedelta(seconds=j*step_seconds),
                     dia=start.date(),id_evento=uuid5(NAMESPACE_URL,f'{vid}/gps/{j}'),
                     latitud=a['latitud']+(b['latitud']-a['latitud'])*f,
                     longitud=a['longitud']+(b['longitud']-a['longitud'])*f,
                     velocidad=speed,estado_vehiculo='EN_MOVIMIENTO' if speed else 'DISPONIBLE')
            cql['telemetria_por_viaje_dia'].append(row)
            cql['telemetria_por_vehiculo_dia'].append(row.copy());samples.append(row)
        latest[veh]=samples[-1]
        # Un evento de exceso por viaje, luego resuelto por una medición normal.
        s=samples[n//2];aid=ident('ALT',i)
        alert=dict(viaje_id=vid,vehiculo_patente=veh,dia=s['dia'],fecha_hora=s['fecha_hora'],
                   alerta_id=aid,tipo='EXCESO_VELOCIDAD',descripcion='Exceso sintético de 105 km/h',
                   latitud=s['latitud'],longitud=s['longitud'],valor_observado=105.,umbral=90.,
                   clave_deduplicacion=f'{veh}:EXCESO_VELOCIDAD:{vid}',resuelta=True,
                   fecha_resolucion=samples[n//2+1]['fecha_hora'],contexto='{"origen":"seed"}')
        cql['alertas_por_viaje_dia'].append(alert)
        cql['alertas_por_vehiculo_dia'].append(alert.copy())
        mongo['alertas'].append(dict(_id=aid,seed_owner=OWNER,**{k:v for k,v in alert.items() if k!='dia'}))
        for k,code in enumerate(codes):
            dest=points[seq[k%3+1]]['_id']
            delivered=not activo or k%3<2
            fecha=start+(end-start)*(k%3+1)/3/(0.8 if activo else 1)
            receptor=dict(nombre='Receptor sintético',dni=ident('DNI-CLI',i*4+k),vinculo='TITULAR')
            pkg=doc('paquetes','PAQ',i*4+k,codigo_seguimiento=code,
                    remitente_id=ident('CLI',i%50),destinatario_id=ident('CLI',(i+1)%50),
                    punto_entrega_id=dest,estado='ENTREGADO' if delivered else 'EN_TRANSITO',
                    fecha_registro=start-timedelta(days=1),peso_kg=5.0)
            asig=doc('asignaciones','ASIG',i*4+k,viaje_id=vid,paquete_codigo=code,
                     punto_inicio_id=points[seq[0]]['_id'],punto_fin_id=dest,
                     estado='COMPLETADA' if delivered else 'ACTIVA',fecha_asignacion=start,
                     creada_por_usuario_id=user['_id'])
            if delivered:
                pkg.update(fecha_entrega=fecha,receptor=receptor)
                asig.update(fecha_fin=fecha,entregado_a=receptor)
                p=next(p for p in points if p['_id']==dest)
                cql['confirmaciones_entrega_por_viaje_dia'].append(dict(
                    viaje_id=vid,dia=fecha.date(),fecha_hora=fecha,paquete_codigo=code,
                    vehiculo_patente=veh,receptor_nombre=receptor['nombre'],receptor_dni=receptor['dni'],
                    receptor_vinculo='TITULAR',latitud=p['latitud'],longitud=p['longitud'],
                    id_evento=uuid5(NAMESPACE_URL,f'{code}/entrega')))
            redis[f'paquete:{code}:estado']=dict(estado=pkg['estado'],viaje_id=vid)
        redis[f'viaje:{vid}:progreso']=dict(entregas_completadas=sum(p['estado']=='ENTREGADO' for p in mongo['paquetes'][-4:]))
        if activo:
            redis[f'reserva:vehiculo:{veh}']=vid
            redis[f'reserva:conductor:{cond}']=vid
        if not activo:
            for j,(a,b) in enumerate(zip(seq,seq[1:])):
                fecha=start+(end-start)*(j+1)/3
                minutes=(end-start).total_seconds()/180
                cql['tiempos_tramo_historico'].append(dict(tramo_id=tramos[a,b],fecha_hora=fecha,
                                                         viaje_id=vid,duracion_minutos=minutes))
                cql['tiempos_tramo_por_mes'].append(dict(tramo_id=tramos[a,b],mes=fecha.strftime('%Y-%m'),
                                                        fecha_fin=fecha,viaje_id=vid,duracion_segundos=round(minutes*60)))
    # Pedidos todavía sin asignar para planificar un viaje nuevo (CU01).
    for i in range(2000,2020):
        code=ident('PAQ',i)
        doc('paquetes','PAQ',i,codigo_seguimiento=code,remitente_id=ident('CLI',0),
            destinatario_id=ident('CLI',1),punto_entrega_id=ident('PTO',3),
            estado='PENDIENTE',fecha_registro=BASE,peso_kg=5.0)
        redis[f'paquete:{code}:estado']=dict(estado='PENDIENTE',viaje_id='')
    for veh,row in latest.items():
        redis[f'vehiculo:{veh}:estado']=dict(fecha_hora_ms=int((row['fecha_hora']-datetime(1970,1,1)).total_seconds()*1000),
            viaje_id=row['viaje_id'] if row['estado_vehiculo']!='DISPONIBLE' else '',
            latitud=row['latitud'],longitud=row['longitud'],velocidad=row['velocidad'],estado=row['estado_vehiculo'])
    return dict(version=VERSION,mediciones=mediciones,mongo=dict(mongo),cql=dict(cql),nodes=nodes,edges=edges,redis=redis)


def validar_local(data):
    """Rechaza claves duplicadas, referencias rotas y estados incompatibles."""
    def require(ok,msg):
        if not ok: raise ValueError(msg)
    m=data['mongo'];by={c:{x['_id']:x for x in docs} for c,docs in m.items()}
    for c,docs in m.items(): require(len(by[c])==len(docs),f'_id duplicado en {c}')
    for t,rows in data['cql'].items():
        require(len({tuple(r[k] for k in PK[t]) for r in rows})==len(rows),f'PK duplicada en {t}')
    require(len(data['cql']['telemetria_por_viaje_dia'])==data['mediciones']>=50000,'Volumen insuficiente')
    require(data['cql']['telemetria_por_viaje_dia']==data['cql']['telemetria_por_vehiculo_dia'],'Espejo GPS desigual')
    active=set()
    for a in m['asignaciones']:
        require(a['viaje_id'] in by['viajes'] and a['paquete_codigo'] in by['paquetes'],'Asignación huérfana')
        p=by['paquetes'][a['paquete_codigo']];v=by['viajes'][a['viaje_id']]
        require(p['punto_entrega_id']==a['punto_fin_id'],'Destino incompatible')
        require(p['remitente_id'] in by['contactos'] and p['destinatario_id'] in by['contactos'],'Contacto ausente')
        if a['estado']=='ACTIVA':
            require(a['paquete_codigo'] not in active and v['estado']=='EN_CURSO' and p['estado']=='EN_TRANSITO','Asignación activa incompatible')
            active.add(a['paquete_codigo'])
        else: require(p['estado']=='ENTREGADO' and a['fecha_fin']==p['fecha_entrega'],'Entrega incoherente')
    occupied=set()
    for v in m['viajes']:
        require(v['ruta_id'] in by['rutas'] and v['vehiculo_patente'] in by['vehiculos'] and v['conductor_id'] in by['conductores'],'Viaje huérfano')
        require(v['id_ruta']==v['ruta_id'] and v['id_vehiculo']==v['vehiculo_patente'],'Alias inconsistente')
        if v['estado']=='EN_CURSO':
            require(v['vehiculo_patente'] not in occupied,'Dos viajes activos por vehículo')
            occupied.add(v['vehiculo_patente'])
    connections={(e['av'],e['bv']) for e in data['edges'] if e['rel']=='CONECTA'}
    for r in m['rutas']:
        seq=[p['punto_entrega_id'] for p in r['puntos']]
        require(all((a,b) in connections for a,b in zip(seq,seq[1:])),'Ruta sin conexión')
        # El camino alternativo directo evita el segundo punto del recorrido.
        require((seq[0],seq[2]) in connections,'No existe desvío para CU07')
    for r in data['cql']['telemetria_por_viaje_dia']:
        v=by['viajes'][r['viaje_id']]
        require(v['vehiculo_patente']==r['vehiculo_patente'] and r['dia']==r['fecha_hora'].date(),'GPS sin relación válida')
        require(-90<=r['latitud']<=90 and -180<=r['longitud']<=180 and r['velocidad']>=0,'GPS inválido')
    for a in data['cql']['alertas_por_viaje_dia']:
        require(a['valor_observado']>a['umbral'] and a['fecha_resolucion']>a['fecha_hora'],'Alerta incompatible')
    return dict(mediciones_logicas=data['mediciones'],mongo={c:len(d) for c,d in m.items()},
                cassandra={t:len(d) for t,d in data['cql'].items()},
                neo4j_nodos=len(data['nodes']),neo4j_relaciones=len(data['edges']),redis_claves=len(data['redis']))


ESQUEMAS = {'06_update_if_newer.lua': "-- KEYS[1] = vehiculo:{patente}:estado\n-- ARGV[1] = fecha_hora_ms (Unix en milisegundos)\n-- ARGV[2] = viaje_id\n-- ARGV[3] = latitud\n-- ARGV[4] = longitud\n-- ARGV[5] = velocidad\n-- ARGV[6] = estado\n\nlocal incoming = tonumber(ARGV[1])\n\nif not incoming then\n    return redis.error_reply('fecha_hora_ms invalida')\nend\n\nlocal last = redis.call('HGET', KEYS[1], 'fecha_hora_ms')\nlocal last_number = nil\n\nif last then\n    last_number = tonumber(last)\n\n    if not last_number then\n        return redis.error_reply('fecha_hora_ms almacenada invalida')\n    end\n\n    -- No sobrescribir con una medición antigua o repetida.\n    if incoming <= last_number then\n        return 0\n    end\nend\n\n-- Guardar la medición más reciente.\nredis.call(\n    'HSET',\n    KEYS[1],\n    'fecha_hora_ms', ARGV[1],\n    'viaje_id', ARGV[2],\n    'latitud', ARGV[3],\n    'longitud', ARGV[4],\n    'velocidad', ARGV[5],\n    'estado', ARGV[6]\n)\n\nreturn 1", '03_neo4j.cypher': "// Ingeniería de Datos II — red logística Neo4j\n// Ejecutar en Neo4j Browser por sentencias o con cypher-shell -f neo4j/03_neo4j.cypher\n// No crea nodos ni recorridos de prueba; solo restricciones e índices.\nCREATE CONSTRAINT punto_id_unico IF NOT EXISTS FOR (p:PuntoEntrega) REQUIRE p.punto_entrega_id IS UNIQUE;\nCREATE CONSTRAINT ruta_id_unico IF NOT EXISTS FOR (r:Ruta) REQUIRE r.ruta_id IS UNIQUE;\nCREATE INDEX punto_localidad IF NOT EXISTS FOR (p:PuntoEntrega) ON (p.localidad);\nCREATE INDEX ruta_estado IF NOT EXISTS FOR (r:Ruta) ON (r.estado);\n// Modelo acordado:\n// (:PuntoEntrega {punto_entrega_id, nombre, latitud, longitud, localidad})\n// -[:CONECTA {tramo_id, distancia_km, tiempo_estimado_min, habilitado}]->\n// (:PuntoEntrega)\n// (:Ruta {ruta_id, estado})-[:INCLUYE {orden}]->(:PuntoEntrega)\n// Para tramos bidireccionales crear ambas relaciones dirigidas CONECTA.\n// Cada relación CONECTA se identifica por tramo_id a nivel aplicativo.\n// Idempotencia de datos de prueba: usar MERGE en los nodos y relación con clave tramo_id.\n// EJEMPLO DE PRUEBA (cargar datos reales antes):\n// MATCH (a:PuntoEntrega {punto_entrega_id:'P-1'}), (b:PuntoEntrega {punto_entrega_id:'P-2'})\n// MERGE (a)-[t:CONECTA {tramo_id:'T-1-2'}]->(b)\n// SET t.distancia_km=3.8, t.tiempo_estimado_min=8, t.habilitado=true;\n// Consulta de conexiones habilitadas a un punto:\n// MATCH (a:PuntoEntrega {punto_entrega_id:'P-1'})-[c:CONECTA]->(b:PuntoEntrega)\n// WHERE c.habilitado = true\n// RETURN b.punto_entrega_id, c.distancia_km, c.tiempo_estimado_min;\n// Para CU-07 usar búsqueda de caminos con filtro por habilitación y validación de costos\n// mediante Cypher/GDS según la edición instalada (pendiente de implementar y probar).", '02_cassandra.cql': "-- Ingeniería de Datos II — TPO Etapa 2\n-- Ejecutar con cqlsh. Diseño orientado a consultas por viaje/vehículo y fecha.\nCREATE KEYSPACE IF NOT EXISTS logistica_flota\nWITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};\n-- SimpleStrategy RF=1 es SOLO para laboratorio local; revisar para producción/Astra DB.\nUSE logistica_flota;\n\n-- CU-02 y CU-08: telemetría por viaje y día, orden temporal.\nCREATE TABLE IF NOT EXISTS telemetria_por_viaje_dia (\n  viaje_id text,\n  dia date,\n  fecha_hora timestamp,\n  id_evento uuid,\n  vehiculo_patente text,\n  latitud double,\n  longitud double,\n  velocidad double,\n  estado_vehiculo text,\n  PRIMARY KEY ((viaje_id, dia), fecha_hora, id_evento)\n) WITH CLUSTERING ORDER BY (fecha_hora ASC, id_evento ASC);\n\n-- CU-02: consulta histórica puntual por vehículo y día, inclusive sin viaje activo.\n-- Es una tabla desnormalizada deliberadamente: el proceso de ingesta escribe en ambas.\nCREATE TABLE IF NOT EXISTS telemetria_por_vehiculo_dia (\n  vehiculo_patente text,\n  dia date,\n  fecha_hora timestamp,\n  id_evento uuid,\n  viaje_id text,\n  latitud double,\n  longitud double,\n  velocidad double,\n  estado_vehiculo text,\n  PRIMARY KEY ((vehiculo_patente, dia), fecha_hora, id_evento)\n) WITH CLUSTERING ORDER BY (fecha_hora ASC, id_evento ASC);\n\n-- CU-03 y CU-08: Registro histórico de alertas por viaje y día (análisis temporal y trazabilidad).\nCREATE TABLE IF NOT EXISTS alertas_por_viaje_dia (\n  viaje_id text,\n  dia date,\n  fecha_hora timestamp,\n  alerta_id text,\n  vehiculo_patente text,\n  tipo text,\n  descripcion text,\n  latitud double,\n  longitud double,\n  valor_observado double,\n  umbral double,\n  clave_deduplicacion text,\n  resuelta boolean,\n  fecha_resolucion timestamp,\n  contexto text,\n  PRIMARY KEY ((viaje_id, dia), fecha_hora, alerta_id)\n) WITH CLUSTERING ORDER BY (fecha_hora ASC, alerta_id ASC);\n\n-- CU-03: Histórico de alertas por vehículo y día (inclusive sin viaje activo).\nCREATE TABLE IF NOT EXISTS alertas_por_vehiculo_dia (\n  vehiculo_patente text,\n  dia date,\n  fecha_hora timestamp,\n  alerta_id text,\n  viaje_id text,\n  tipo text,\n  descripcion text,\n  latitud double,\n  longitud double,\n  valor_observado double,\n  umbral double,\n  clave_deduplicacion text,\n  resuelta boolean,\n  fecha_resolucion timestamp,\n  contexto text,\n  PRIMARY KEY ((vehiculo_patente, dia), fecha_hora, alerta_id)\n) WITH CLUSTERING ORDER BY (fecha_hora ASC, alerta_id ASC);\n\n-- CU-03: Espejo durable de anomalías abiertas (fuente de la verdad para reconciliar con Redis).\nCREATE TABLE IF NOT EXISTS alertas_abiertas_por_vehiculo (\n  vehiculo_patente text,\n  tipo text,\n  alerta_id text,\n  viaje_id text,\n  dia date,\n  fecha_hora timestamp,\n  PRIMARY KEY ((vehiculo_patente), tipo)\n);\n\n-- CU-03: Bitácora de pasos completados por operación (requisito obligatorio de la Sección 5).\nCREATE TABLE IF NOT EXISTS alertas_log_pasos (\n  alerta_id text,\n  ts timestamp,\n  paso text,\n  estado text,\n  detalle text,\n  PRIMARY KEY ((alerta_id), ts, paso)\n) WITH default_time_to_live = 604800;\n\n-- CU-06: Histórico inmutable de confirmaciones de entrega (Proof of Delivery / Trazabilidad).\nCREATE TABLE IF NOT EXISTS confirmaciones_entrega_por_viaje_dia (\n  viaje_id text,\n  dia date,\n  fecha_hora timestamp,\n  paquete_codigo text,\n  vehiculo_patente text,\n  receptor_nombre text,\n  receptor_dni text,\n  receptor_vinculo text,\n  latitud double,\n  longitud double,\n  id_evento uuid,\n  PRIMARY KEY ((viaje_id, dia), fecha_hora, paquete_codigo)\n) WITH CLUSTERING ORDER BY (fecha_hora ASC, paquete_codigo ASC);\n\n-- Tiempos históricos precalculados por tramo para ETA (CU-04).\n-- Este modelo requiere que la aplicación complete estas filas a partir de viajes concluidos.\nCREATE TABLE IF NOT EXISTS tiempos_tramo_por_mes (\n  tramo_id text,\n  mes text,\n  fecha_fin timestamp,\n  viaje_id text,\n  duracion_segundos int,\n  PRIMARY KEY ((tramo_id, mes), fecha_fin, viaje_id)\n) WITH CLUSTERING ORDER BY (fecha_fin DESC, viaje_id ASC);\n\nCREATE TABLE IF NOT EXISTS logistica_flota.tiempos_tramo_historico (\n  tramo_id text,\n  fecha_hora timestamp,\n  viaje_id text,\n  duracion_minutos double,\n  PRIMARY KEY (tramo_id, fecha_hora)\n) WITH CLUSTERING ORDER BY (fecha_hora DESC);\n\n\n-- Consultas de ejemplo:\n-- SELECT * FROM telemetria_por_viaje_dia\n-- WHERE viaje_id = 'VIAJE-1001' AND dia = '2026-10-25'\n-- AND fecha_hora >= '2026-10-25T09:00:00Z'\n-- AND fecha_hora < '2026-10-25T10:00:00Z';\n-- SELECT * FROM telemetria_por_vehiculo_dia\n-- WHERE vehiculo_patente = 'AB123CD' AND dia = '2026-10-25';\n-- SELECT * FROM alertas_por_vehiculo_dia\n-- WHERE vehiculo_patente = 'AB123CD' AND dia = '2026-10-25';\n-- SELECT * FROM confirmaciones_entrega_por_viaje_dia\n-- WHERE viaje_id = 'VIAJE-1001' AND dia = '2026-10-30';", '01_mongodb.js': "// Ingeniería de Datos II — TPO Etapa 2\n// Ejecutar desde mongosh. Diseño inicial: NO incluye aplicación ni transacciones entre motores.\nconst dbLog = db.getSiblingDB('logistica_flota');\n\nconst collections = ['contactos','usuarios','conductores','vehiculos','puntos_entrega','rutas','paquetes','viajes','asignaciones','alertas','operaciones'];\nfor (const name of collections) {\n  if (!dbLog.getCollectionNames().includes(name)) dbLog.createCollection(name);\n}\n\n// Identificadores compartidos: viaje_id (string), paquete_codigo (string),\n// vehiculo_patente (string), conductor_id (string), id_evento (UUID/string).\n// El campo _id puede coincidir con el identificador de negocio para búsquedas exactas.\n\ndbLog.usuarios.createIndex({ username: 1 }, { unique: true });\ndbLog.usuarios.createIndex({ contacto_id: 1 }, { unique: true, sparse: true });\ndbLog.conductores.createIndex({ contacto_id: 1 }, { unique: true });\ndbLog.conductores.createIndex({ nro_licencia: 1 }, { unique: true });\ndbLog.contactos.createIndex({ dni: 1 }, { unique: true, partialFilterExpression: { tipo: 'PERSONA', dni: { $type: 'string' } } });\ndbLog.contactos.createIndex({ cuit: 1 }, { unique: true, partialFilterExpression: { tipo: 'EMPRESA', cuit: { $type: 'string' } } });\n\ndbLog.paquetes.createIndex({ estado: 1, punto_entrega_id: 1 });\ndbLog.paquetes.createIndex({ remitente_id: 1, fecha_registro: -1 });\ndbLog.paquetes.createIndex({ destinatario_id: 1, fecha_registro: -1 });\n\ndbLog.viajes.createIndex({ vehiculo_patente: 1, inicio_planificado: 1, fin_planificado: 1 });\ndbLog.viajes.createIndex({ conductor_id: 1, inicio_planificado: 1, fin_planificado: 1 });\ndbLog.viajes.createIndex({ estado: 1, ruta_id: 1 });\n\ndbLog.asignaciones.createIndex({ viaje_id: 1, estado: 1 });\ndbLog.asignaciones.createIndex({ paquete_codigo: 1, fecha_asignacion: 1 });\n// Garantía: como máximo una asignación ACTIVA por paquete.\ndbLog.asignaciones.createIndex(\n  { paquete_codigo: 1 },\n  { unique: true, partialFilterExpression: { estado: 'ACTIVA' }, name: 'unica_asignacion_activa_por_paquete' }\n);\n\ndbLog.alertas.createIndex({ clave_deduplicacion: 1 }, { unique: true });\ndbLog.alertas.createIndex({ viaje_id: 1, fecha_hora: 1 });\ndbLog.operaciones.createIndex({ estado: 1, fecha_inicio: 1 });\n\nprint('Colecciones e índices de MongoDB preparados en logistica_flota');\nprintjson(dbLog.getCollectionNames());"}

"""CLI: generar, cargar, verificar y limpiar exclusivamente este conjunto seed."""
import argparse
from collections import defaultdict
from contextlib import ExitStack
from datetime import date, datetime
import hashlib
import re
import json
from pathlib import Path
import sys
from uuid import UUID



ROOT=Path(__file__).resolve().parent


def serial(obj):
    if isinstance(obj,datetime): return {'$datetime':obj.isoformat(timespec='milliseconds')}
    if isinstance(obj,date): return {'$date':obj.isoformat()}
    if isinstance(obj,UUID): return {'$uuid':str(obj)}
    raise TypeError(type(obj).__name__)


def canon(obj):
    return json.dumps(obj,default=serial,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def save(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj,default=serial,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)


def digest(data):
    return hashlib.sha256(canon(data).encode()).hexdigest()


class SeedError(RuntimeError):
    pass


def require(ok,msg):
    if not ok: raise SeedError(msg)


def normal(value):
    """Normaliza tipos leídos de los drivers sin ocultar diferencias de datos."""
    if isinstance(value,datetime): return value.replace(tzinfo=None,microsecond=value.microsecond//1000*1000)
    if value.__class__.__module__.startswith('cassandra') and value.__class__.__name__=='Date':
        return value.date()
    if isinstance(value,dict): return {k:normal(v) for k,v in value.items()}
    if isinstance(value,list): return [normal(v) for v in value]
    return value


class Motores:
    def __init__(self,stack):
        # Importación diferida: --solo-generar y tests funcionan sin dependencias externas.
        from app.conexiones import conectar_mongodb,conectar_cassandra,conectar_redis,conectar_neo4j
        self.mongo=conectar_mongodb();stack.callback(self.mongo.close)
        self.cluster,self.cql=conectar_cassandra();stack.callback(self.cluster.shutdown)
        self.redis=conectar_redis();stack.callback(self.redis.close)
        self.neo=conectar_neo4j();stack.callback(self.neo.close)
        self.db=self.mongo['logistica_flota']

    def completar_esquema_cassandra(self):
        """Evolución aditiva: CREATE IF NOT EXISTS no completa tablas antiguas.

        Se comprueban tipos y claves antes de agregar columnas regulares.
        Nunca elimina datos, cambia claves primarias ni convierte tipos.
        """
        esquema = ESQUEMAS['02_cassandra.cql']
        definiciones = re.findall(
            r'CREATE TABLE IF NOT EXISTS (?:logistica_flota\.)?(\w+)\s*\((.*?)PRIMARY KEY',
            esquema, re.S,
        )
        cambios = []
        for tabla, cuerpo in definiciones:
            esperadas = dict(re.findall(
                r'^\s*(\w+)\s+(text|date|timestamp|uuid|double|boolean|int)\b',
                cuerpo, re.M,
            ))
            filas = self.cql.execute(
                'SELECT column_name, type, kind, position FROM system_schema.columns '
                'WHERE keyspace_name=%s AND table_name=%s',
                ('logistica_flota', tabla),
            )
            actuales = {r.column_name: r for r in filas}
            require(bool(actuales), f'No se encontró la tabla Cassandra {tabla}')
            for columna, tipo in esperadas.items():
                if columna in actuales:
                    require(actuales[columna].type == tipo,
                            f'Tipo incompatible en Cassandra {tabla}.{columna}: '
                            f'{actuales[columna].type}, esperado {tipo}. No se modificaron tipos.')
            if tabla in PK:
                particion = tuple(r.column_name for r in sorted(
                    (r for r in actuales.values() if r.kind == 'partition_key'), key=lambda r: r.position))
                clustering = tuple(r.column_name for r in sorted(
                    (r for r in actuales.values() if r.kind == 'clustering'), key=lambda r: r.position))
                require(particion == tuple(PART[tabla]) and particion + clustering == tuple(PK[tabla]),
                        f'Clave primaria incompatible en Cassandra {tabla}; requiere revisión, no se borra la tabla.')
            for columna, tipo in esperadas.items():
                if columna not in actuales:
                    # Nombres y tipos salen del DDL embebido, no de entradas externas.
                    self.cql.execute(f'ALTER TABLE logistica_flota.{tabla} ADD {columna} {tipo}')
                    cambios.append(f'{tabla}.{columna}')
        if cambios:
            print('Cassandra: se agregaron columnas faltantes: ' + ', '.join(cambios), file=sys.stderr)

    def inicializar(self):
        """Solo DDL aditivo, copiado del esquema final. Nunca drop/flush/truncate."""
        cql=ESQUEMAS['02_cassandra.cql']
        clean='\n'.join(line.split('--')[0] for line in cql.splitlines())
        for statement in clean.split(';'):
            if statement.strip(): self.cql.execute(statement.strip())
        self.completar_esquema_cassandra()
        cypher=ESQUEMAS['03_neo4j.cypher']
        clean='\n'.join(line for line in cypher.splitlines() if not line.strip().startswith('//'))
        with self.neo.session() as session:
            for statement in clean.split(';'):
                if statement.strip(): session.run(statement).consume()
            session.run('CREATE CONSTRAINT seed_viaje_unico IF NOT EXISTS FOR (v:Viaje) REQUIRE v.viaje_id IS UNIQUE').consume()
        # Mismos índices de 01_mongodb.js; se usa PyMongo para no requerir mongosh.
        for name in ['contactos','usuarios','conductores','vehiculos','puntos_entrega','rutas','paquetes','viajes','asignaciones','alertas','operaciones']:
            if name not in self.db.list_collection_names(): self.db.create_collection(name)
        indexes={
            'usuarios':[([('username',1)],dict(unique=True)),([('contacto_id',1)],dict(unique=True,sparse=True))],
            'conductores':[([('contacto_id',1)],dict(unique=True)),([('nro_licencia',1)],dict(unique=True))],
            'contactos':[([('dni',1)],dict(unique=True,partialFilterExpression={'tipo':'PERSONA','dni':{'$type':'string'}})),
                         ([('cuit',1)],dict(unique=True,partialFilterExpression={'tipo':'EMPRESA','cuit':{'$type':'string'}}))],
            'paquetes':[([('estado',1),('punto_entrega_id',1)],{}),([('remitente_id',1),('fecha_registro',-1)],{}),([('destinatario_id',1),('fecha_registro',-1)],{})],
            'viajes':[([('vehiculo_patente',1),('inicio_planificado',1),('fin_planificado',1)],{}),([('conductor_id',1),('inicio_planificado',1),('fin_planificado',1)],{}),([('estado',1),('ruta_id',1)],{})],
            'asignaciones':[([('viaje_id',1),('estado',1)],{}),([('paquete_codigo',1),('fecha_asignacion',1)],{}),([('paquete_codigo',1)],dict(unique=True,partialFilterExpression={'estado':'ACTIVA'},name='unica_asignacion_activa_por_paquete'))],
            'alertas':[([('clave_deduplicacion',1)],dict(unique=True)),([('viaje_id',1),('fecha_hora',1)],{})],
            'operaciones':[([('estado',1),('fecha_inicio',1)],{})]}
        for coll,items in indexes.items():
            for keys,options in items: self.db[coll].create_index(keys,**options)

    def preflight(self,data):
        """Antes de escribir, rechaza colisiones con entidades ajenas al generador."""
        for coll,docs in data['mongo'].items():
            for d in docs:
                old=self.db[coll].find_one({'_id':d['_id']})
                require(old is None or normal(old)==normal(d),f'Colisión o cambio MongoDB {coll}/{d["_id"]}')
        with self.neo.session() as session:
            for n in data['nodes']:
                rows=list(session.run(f'MATCH (n:{n["label"]} {{{n["key"]}:$id}}) RETURN properties(n) AS props',id=n['value']))
                want=dict(n['props'],**{n['key']:n['value']})
                require(len(rows)<=1 and all(dict(r['props'])==want for r in rows),'Colisión o cambio de nodo Neo4j')
            for e in data['edges']:
                rows=list(session.run(f'MATCH (a:{e["al"]} {{{e["ak"]}:$a}})-[r]->(b:{e["bl"]} {{{e["bk"]}:$b}}) WHERE type(r)=$tipo RETURN properties(r) AS props',a=e['av'],b=e['bv'],tipo=e['rel']))
                require(len(rows)<=1 and all(dict(r['props'])==e['props'] for r in rows),'Colisión o cambio de relación Neo4j')
        # Redis y Cassandra usan claves de negocio: cualquier valor preexistente diferente
        # impide sobrescrituras incluso si pertenece a una demostración anterior del TPO.
        for key,expected in data['redis'].items():
            typ=self.redis.type(key)
            require(typ in ('none','hash' if isinstance(expected,dict) else 'string'),f'Tipo Redis incompatible {key}')
            if typ!='none':
                actual=self.redis.hgetall(key) if typ=='hash' else self.redis.get(key)
                want={k:str(v) for k,v in expected.items()} if isinstance(expected,dict) else expected
                require(actual==want,f'Redis modificado: {key}; usar conjunto limpio')
        for table,rows in data['cql'].items():
            expected={tuple(normal(r[k]) for k in PK[table]):normal(r) for r in rows}
            for actual in self.leer_particiones(table,rows):
                key=tuple(normal(actual[k]) for k in PK[table])
                require(key not in expected or normal(actual)==expected[key],f'Cassandra modificado: {table}')

    def leer_particiones(self,table,rows):
        partitions={tuple(r[k] for k in PART[table]) for r in rows}
        query='SELECT * FROM logistica_flota.'+table+' WHERE '+' AND '.join(k+'=%s' for k in PART[table])
        for values in partitions:
            for row in self.cql.execute(query,values): yield row._asdict()

    def cql_lotes(self,data,concurrencia,delete=False):
        from cassandra.concurrent import execute_concurrent_with_args
        for table,rows in data['cql'].items():
            if not rows: continue
            cols=list(PK[table]) if delete else list(rows[0])
            if delete:
                query='DELETE FROM logistica_flota.'+table+' WHERE '+' AND '.join(k+'=?' for k in cols)
            else:
                query='INSERT INTO logistica_flota.'+table+' ('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')'
            prepared=self.cql.prepare(query)
            for offset in range(0,len(rows),500):
                results=execute_concurrent_with_args(self.cql,prepared,
                    [tuple(r[k] for k in cols) for r in rows[offset:offset+500]],
                    concurrency=concurrencia,raise_on_first_error=True)
                require(all(ok for ok,_ in results),f'Falló escritura Cassandra {table}')

    def cargar(self,data,concurrencia):
        from pymongo import ReplaceOne
        for coll,docs in data['mongo'].items():
            for offset in range(0,len(docs),500):
                self.db[coll].bulk_write([ReplaceOne({'_id':d['_id']},d,upsert=True) for d in docs[offset:offset+500]],ordered=True)
        self.cql_lotes(data,concurrencia)
        with self.neo.session() as session:
            # Etiquetas/propiedades provienen de constantes del generador, nunca de entradas externas.
            for n in data['nodes']:
                session.run(f'MERGE (n:{n["label"]} {{{n["key"]}:$id}}) SET n += $props',id=n['value'],props=n['props']).consume()
            for e in data['edges']:
                session.run(f'MATCH (a:{e["al"]} {{{e["ak"]}:$a}}), (b:{e["bl"]} {{{e["bk"]}:$b}}) MERGE (a)-[r:{e["rel"]}]->(b) SET r += $props',
                            a=e['av'],b=e['bv'],props=e['props']).consume()
        lua=ESQUEMAS['06_update_if_newer.lua']
        for key,value in data['redis'].items():
            if key.startswith('vehiculo:'):
                self.redis.eval(lua,1,key,*[value[k] for k in ('fecha_hora_ms','viaje_id','latitud','longitud','velocidad','estado')])
            elif isinstance(value,dict): self.redis.hset(key,mapping=value)
            else: self.redis.set(key,value)

    def verificar(self,data):
        counts={}
        for coll,docs in data['mongo'].items():
            for expected in docs:
                actual=self.db[coll].find_one({'_id':expected['_id']})
                require(normal(actual)==normal(expected),f'MongoDB distinto: {coll}/{expected["_id"]}')
            counts['mongo.'+coll]=len(docs)
        for table,rows in data['cql'].items():
            expected={tuple(normal(r[k]) for k in PK[table]):normal(r) for r in rows}
            found=set()
            for row in self.leer_particiones(table,rows):
                key=tuple(normal(row[k]) for k in PK[table])
                if key in expected:
                    require(normal(row)==expected[key],f'Cassandra distinto: {table}/{key}')
                    found.add(key)
            require(len(found)==len(expected),f'Cassandra incompleto: {table} ({len(found)}/{len(expected)})')
            counts['cassandra.'+table]=len(found)
        with self.neo.session() as session:
            for n in data['nodes']:
                result=list(session.run(f'MATCH (n:{n["label"]} {{{n["key"]}:$id}}) RETURN properties(n) AS props',id=n['value']))
                want=dict(n['props'],**{n['key']:n['value']})
                require(len(result)==1 and dict(result[0]['props'])==want,'Nodo Neo4j incompleto')
            for e in data['edges']:
                result=list(session.run(f'MATCH (a:{e["al"]} {{{e["ak"]}:$a}})-[r]->(b:{e["bl"]} {{{e["bk"]}:$b}}) WHERE type(r)=$tipo RETURN properties(r) AS props',a=e['av'],b=e['bv'],tipo=e['rel']))
                require(len(result)==1 and dict(result[0]['props'])==e['props'],'Relación Neo4j incompleta')
        for key,value in data['redis'].items():
            actual=self.redis.hgetall(key) if isinstance(value,dict) else self.redis.get(key)
            expected={k:str(v) for k,v in value.items()} if isinstance(value,dict) else value
            require(actual==expected,f'Redis distinto: {key}')
        counts.update(neo4j_nodos=len(data['nodes']),neo4j_relaciones=len(data['edges']),redis_claves=len(data['redis']))
        return counts

    def limpiar(self,data,concurrencia):
        # Comprobar que ningún dato del seed fue reutilizado por la aplicación.
        self.preflight(data)
        with self.neo.session() as s:
            external=s.run('MATCH (n {seed_owner:$owner})-[r]-(m) WHERE coalesce(r.seed_owner, "") <> $owner OR coalesce(m.seed_owner, "") <> $owner RETURN count(r) AS c',owner=OWNER).single()['c']
            require(external==0,'Hay relaciones ajenas conectadas al seed; no se borra')
        self.cql_lotes(data,concurrencia,delete=True)
        for key,value in data['redis'].items():
            self.redis.delete(key)
        for coll,docs in data['mongo'].items():
            self.db[coll].delete_many({'_id':{'$in':[d['_id'] for d in docs]},'seed_owner':OWNER})
        with self.neo.session() as s:
            for n in data['nodes']:
                s.run(f'MATCH (n:{n["label"]} {{{n["key"]}:$id, seed_owner:$owner}}) DETACH DELETE n',id=n['value'],owner=OWNER).consume()
        for table,rows in data['cql'].items():
            expected={tuple(normal(r[k]) for k in PK[table]) for r in rows}
            require(not any(tuple(normal(r[k]) for k in PK[table]) in expected for r in self.leer_particiones(table,rows)),f'Limpieza CQL incompleta: {table}')
        for coll,docs in data['mongo'].items():
            require(self.db[coll].count_documents({'_id':{'$in':[d['_id'] for d in docs]}})==0,'Limpieza Mongo incompleta')
        require(all(not self.redis.exists(k) for k in data['redis']),'Limpieza Redis incompleta')
        with self.neo.session() as s:
            require(s.run('MATCH (n {seed_owner:$o}) RETURN count(n) AS c',o=OWNER).single()['c']==0,'Limpieza Neo4j incompleta')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mediciones',type=int,default=50000)
    p.add_argument('--concurrencia',type=int,default=8)
    g=p.add_mutually_exclusive_group()
    g.add_argument('--solo-generar',action='store_true')
    g.add_argument('--solo-validar',action='store_true')
    g.add_argument('--limpiar-seed',action='store_true')
    p.add_argument('--salida',type=Path,default=Path('seed_resultados'))
    args=p.parse_args(argv)
    if not 1<=args.concurrencia<=64: p.error('concurrencia debe estar entre 1 y 64')
    data=normal(generar(args.mediciones));summary=validar_local(data)
    fingerprint=digest(data);args.salida.mkdir(parents=True,exist_ok=True)
    manifest=args.salida/'manifiesto.json'
    record=dict(version=data['version'],mediciones=args.mediciones,sha256_datos=fingerprint,resumen=summary)
    if manifest.exists():
        require(json.loads(manifest.read_text())==record,'Manifiesto distinto; conservar el anterior y limpiar con sus parámetros')
    elif args.solo_validar or args.limpiar_seed:
        raise RuntimeError('Se necesita el manifiesto original para validar o limpiar')
    else: save(manifest,record)
    report=dict(sha256_datos=fingerprint,validacion_local=summary,motores_reales=False,estado='SOLO_GENERADO')
    report_path=args.salida/'resultado.json'
    if args.solo_generar:
        save(args.salida/'muestra.json',dict(viaje=data['mongo']['viajes'][400],paquete=data['mongo']['paquetes'][1602],medicion=data['cql']['telemetria_por_viaje_dia'][40000]))
    else:
        report.update(estado='EN_PROCESO')
        save(report_path,report)
        try:
            with ExitStack() as stack:
                engines=Motores(stack)
                # Lock distribuido para impedir dos instancias de este generador.
                token=UUID(bytes=__import__('os').urandom(16)).hex
                require(engines.redis.set('seed:tpo:lock',token,nx=True),'Ya hay otro generador; revisar seed:tpo:lock')
                stack.callback(lambda:engines.redis.eval("if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",1,'seed:tpo:lock',token))
                # La firma durable en Redis protege aun si se usa otra carpeta de salida.
                signature=engines.redis.get('seed:tpo:firma')
                require(signature is None or signature==fingerprint,'Existe otro volumen seed: limpiar con su manifiesto')
                if args.limpiar_seed:
                    engines.limpiar(data,args.concurrencia)
                    engines.redis.delete('seed:tpo:firma')
                    report.update(estado='LIMPIEZA_VERIFICADA',motores_reales=True)
                else:
                    if not args.solo_validar:
                        engines.inicializar();engines.preflight(data)
                        engines.redis.set('seed:tpo:firma',fingerprint)
                        engines.cargar(data,args.concurrencia)
                    report.update(lectura_motores=engines.verificar(data),motores_reales=True,estado='CARGA_VERIFICADA')
        except Exception as exc:
            # No copiar mensajes de conexión: pueden contener credenciales.
            report.update(estado='ERROR',tipo_error=type(exc).__name__)
            if isinstance(exc,SeedError): report['detalle']=str(exc)
            elif type(exc).__name__ == 'InvalidRequest':
                report['detalle'] = str(exc)
                print('Cassandra rechazó una consulta: ' + str(exc), file=sys.stderr)
            save(report_path,report)
            if isinstance(exc,SeedError): raise
            raise RuntimeError(f'No se completó la operación ({type(exc).__name__}). Revisar conectividad, esquemas y manifiesto; no se certifica la carga.') from None
    save(report_path,report)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    try: sys.exit(main())
    except (RuntimeError,ValueError) as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)
