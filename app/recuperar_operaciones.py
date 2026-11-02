"""Recupera sagas de procesos locales terminados, sin robar operaciones vivas."""

import argparse
from contextlib import ExitStack
import json
from app.conexiones import (
    conectar_mongodb,
    conectar_redis,
    conectar_neo4j,
    conectar_cassandra,
)
from app.operaciones import Saga, OperacionOcupada
from app.flujos_durables import compensar


def recuperar_operaciones(id_operacion=None):
    resultados = []
    with ExitStack() as stack:
        mongo = conectar_mongodb()
        stack.callback(mongo.close)
        db = mongo["logistica_flota"]
        filtro = {"version": 2}
        if id_operacion:
            filtro["_id"] = id_operacion
        else:
            filtro["estado"] = {"$ne": "COMPENSADO"}
        for doc in db.operaciones.find(filtro):
            if doc["estado"] == "COMPENSADO":
                resultados.append(
                    dict(id_operacion=doc["_id"], estado="COMPENSADO", compensado=True)
                )
                continue
            if doc["estado"] == "COMPLETADO" and not db.bloqueos_operacion.find_one(
                {"operacion_id": doc["_id"]}
            ):
                continue
            try:
                if doc["estado"] == "COMPLETADO":
                    # El commit es terminal: una limpieza concurrente es segura.
                    db.bloqueos_operacion.delete_many({"operacion_id": doc["_id"]})
                    resultados.append(
                        dict(id_operacion=doc["_id"], estado="COMPLETADO")
                    )
                    continue
                s = Saga.recuperar(db, doc)
                redis = conectar_redis()
                stack.callback(redis.close)
                neo = None
                cql = None
                if doc["tipo"] in ("PLANIFICACION", "REASIGNACION"):
                    neo = conectar_neo4j()
                    stack.callback(neo.close)
                if doc["tipo"] in ("ENTREGA", "ANOMALIA", "CIERRE_ANOMALIA"):
                    cluster, cql = conectar_cassandra()
                    stack.callback(cluster.shutdown)
                if doc["tipo"] == "ANOMALIA":
                    from app.anomalias import compensar_anomalia, reconstruir_activa

                    if doc["estado"] == "RECONCILIACION_PENDIENTE":
                        from app.repositorio_alertas import guardar_alerta_cassandra

                        a = doc["alerta"]
                        guardar_alerta_cassandra(cql, a)
                        reconstruir_activa(redis, dict(a, dia=a["fecha_hora"][:10]))
                        print(
                            f"[ALERTA RECUPERADA] {a['vehiculo_patente']} | {a['descripcion']}"
                        )
                        r = dict(
                            alerta_id=a["alerta_id"],
                            tipo=a["tipo"],
                            estado="REGISTRADA_Y_NOTIFICADA",
                        )
                        s.completar(r)
                        resultados.append(dict(id_operacion=s.id, estado="COMPLETADO"))
                    else:
                        resultados.append(
                            compensar_anomalia(s, redis, cql, "Recuperación")
                        )
                elif doc["tipo"] == "CIERRE_ANOMALIA":
                    from app.repositorio_alertas import marcar_alerta_resuelta_cassandra
                    from app.repositorio_alertas_redis import compensar_claim_redis
                    from app.tiempos import utc

                    a = doc["cierre"]
                    marcar_alerta_resuelta_cassandra(
                        cql,
                        a["vehiculo_patente"],
                        a["tipo"],
                        a.get("viaje_id"),
                        a["dia"],
                        utc(a["fecha_hora"]).replace(tzinfo=None),
                        a["alerta_id"],
                    )
                    compensar_claim_redis(
                        redis, a["vehiculo_patente"], a["tipo"], a["alerta_id"]
                    )
                    s.completar(dict(exito=True))
                    resultados.append(dict(id_operacion=s.id, estado="COMPLETADO"))
                else:
                    resultados.append(compensar(s, redis, neo, cql))
            except OperacionOcupada as exc:
                resultados.append(
                    dict(id_operacion=doc["_id"], estado="OCUPADA", error=str(exc))
                )
            except Exception as exc:
                resultados.append(
                    dict(
                        id_operacion=doc["_id"],
                        estado="RECUPERACION_PENDIENTE",
                        error=str(exc),
                    )
                )
    return resultados


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--operacion")
    args = p.parse_args()
    resultados = recuperar_operaciones(args.operacion)
    print(json.dumps(resultados, ensure_ascii=False, indent=2, default=str))
    return (
        1
        if any(
            r["estado"] in ("RECUPERACION_PENDIENTE", "COMPENSACION_PENDIENTE")
            for r in resultados
        )
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
