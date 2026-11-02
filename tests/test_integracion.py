"""Pruebas reales optativas; cada prueba usa fixtures exclusivas y conserva evidencia."""

import json, os, subprocess, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from pathlib import Path
from app.demo_comun import motores, crear_escenario, emitir
from app.flujos_durables import planificar, entregar, reasignar
from app.fallas import InyectorFallas
from app.operaciones import identidad, Saga, OperacionOcupada
from app.recuperar_operaciones import recuperar_operaciones
from app.trazabilidad import consultar_trazabilidad_completa


@unittest.skipUnless(
    os.getenv("TPO_INTEGRACION") == "1", "Requiere TPO_INTEGRACION=1 y cuatro motores"
)
class IntegracionTest(unittest.TestCase):
    def guardar(self, nombre, datos):
        p = Path("evidencias/correcciones")
        p.mkdir(parents=True, exist_ok=True)
        (p / f"{nombre}-{uuid4().hex[:8]}.json").write_text(
            json.dumps(datos, default=str, ensure_ascii=False, indent=2)
        )

    def entrega(self, f):
        return dict(
            id_operacion=f["demo_id"] + "-entrega",
            viaje_id=f["viaje"],
            paquete_codigo=f["paquetes"][0],
            vehiculo_patente=f["vehiculos"][0],
            fecha_hora=datetime.now(timezone.utc).isoformat(),
            receptor_nombre="Receptor prueba",
            latitud=-34.63,
            longitud=-58.45,
        )

    def averia(self, f):
        return dict(
            id_operacion=f["demo_id"] + "-rescate",
            id_viaje_averiado=f["viaje"],
            patente_averiada=f["vehiculos"][0],
            patente_reemplazo=f["vehiculos"][1],
            conductor_reemplazo=f["conductores"][1],
            id_punto_averia=f["puntos"][0],
        )

    def verificar_restaura(self, e, f):
        for p in f["paquetes"]:
            self.assertEqual(
                e.db.paquetes.find_one({"_id": p})["estado"], "EN_TRANSITO"
            )
            self.assertEqual(
                e.db.asignaciones.count_documents(
                    {"paquete_codigo": p, "estado": "ACTIVA"}
                ),
                1,
            )
        self.assertEqual(
            e.db.viajes.find_one({"_id": f["viaje"]})["estado"], "EN_CURSO"
        )

    def test_falla_final_redis_entrega(self):
        with motores() as e:
            f = crear_escenario(e, "FINAL06", paquetes=1)
            d = self.entrega(f)
            r = entregar(e.redis, e.db, e.cql, d, InyectorFallas("CU06_REDIS_CONFIRM"))
            self.assertFalse(r["exito"])
            self.assertTrue(r["compensado"])
            self.verificar_restaura(e, f)
            filas = list(
                e.cql.execute(
                    "SELECT * FROM logistica_flota.confirmaciones_entrega_por_viaje_dia WHERE viaje_id=%s AND dia=%s",
                    (f["viaje"], datetime.now(timezone.utc).date()),
                )
            )
            self.assertEqual(filas, [])
            progreso = e.redis.hgetall(f"viaje:{f['viaje']}:progreso")
            self.assertEqual(progreso["entregas_pendientes"], "1")
            self.guardar(
                "redis_final_entrega",
                dict(
                    fixture=f,
                    resultado=r,
                    comprobantes=0,
                    progreso=progreso,
                    verificado=True,
                ),
            )

    def test_falla_final_redis_rescate_y_parcial_mongo(self):
        for punto in ["CU05_REDIS_CONFIRM", "CU05_PAQUETES"]:
            with self.subTest(punto=punto), motores() as e:
                f = crear_escenario(e, "FINAL05")
                r = reasignar(
                    e.redis, e.db, e.neo, self.averia(f), InyectorFallas(punto)
                )
                self.assertFalse(r["exito"])
                self.assertTrue(r["compensado"])
                self.verificar_restaura(e, f)
                self.assertFalse(
                    e.redis.exists(f"reserva:vehiculo:{f['vehiculos'][1]}")
                )
                self.assertEqual(
                    e.db.vehiculos.find_one({"_id": f["vehiculos"][0]})["estado"],
                    "EN_VIAJE",
                )
                self.guardar(punto, dict(fixture=f, resultado=r, verificado=True))

    def test_entrega_reintento_y_metricas_demora(self):
        with motores() as e:
            f = crear_escenario(e, "METRICAS", paquetes=1)
            d = self.entrega(f)
            v = e.db.viajes.find_one({"_id": f["viaje"]})
            v["paradas"][-1]["hora_planificada"] = datetime.now(
                timezone.utc
            ) - timedelta(minutes=10)
            e.db.viajes.update_one(
                {"_id": f["viaje"]}, {"$set": {"paradas": v["paradas"]}}
            )
            r = entregar(e.redis, e.db, e.cql, d)
            self.assertTrue(r["exito"], r)
            r2 = entregar(e.redis, e.db, e.cql, d)
            self.assertTrue(r2["repetida"])
            self.assertEqual(r2["saga_id"], r["saga_id"])
            v = e.db.viajes.find_one({"_id": f["viaje"]})
            self.assertEqual(v["entregas_completadas"], 1)
            self.assertEqual(v["entregas_pendientes"], 0)
            self.assertGreater(v["demora_acumulada_min"], 9.9)
            # Redis perdido no vuelve a entregar el paquete ni revierte MongoDB.
            e.redis.delete(f"paquete:{f['paquetes'][0]}:estado")
            otro = dict(d, id_operacion="otro-" + uuid4().hex)
            self.assertFalse(entregar(e.redis, e.db, e.cql, otro)["exito"])
            self.assertEqual(
                e.db.paquetes.find_one({"_id": f["paquetes"][0]})["estado"], "ENTREGADO"
            )
            self.guardar(
                "metricas_reintento",
                dict(
                    fixture=f,
                    resultado=r,
                    metricas={
                        k: v[k]
                        for k in [
                            "entregas_completadas",
                            "entregas_pendientes",
                            "demora_acumulada_min",
                        ]
                    },
                    verificado=True,
                ),
            )

    def test_viajes_compatibles_y_superpuestos(self):
        with motores() as e:
            f = crear_escenario(e, "AGENDA", activo=False, paquetes=3)
            inicio = datetime.now(timezone.utc) + timedelta(hours=1)
            base = dict(
                id_ruta=f["ruta"],
                id_vehiculo=f["vehiculos"][0],
                id_conductor=f["conductores"][0],
            )
            r = []
            for i, offset in enumerate([0, 2, 0.5]):
                d = dict(
                    base,
                    paquetes=[f["paquetes"][i]],
                    inicio_planificado=inicio + timedelta(hours=offset),
                    fin_planificado=inicio + timedelta(hours=offset + 1),
                )
                r.append(planificar(e.redis, e.db, d, e.neo))
            self.assertTrue(r[0]["exito"], r[0])
            self.assertTrue(r[1]["exito"], r[1])
            self.assertFalse(r[2]["exito"])
            for x in r[:2]:
                v = e.db.viajes.find_one({"_id": x["id_viaje"]})
                self.assertTrue(all(p.get("hora_planificada") for p in v["paradas"]))
                self.assertIsNotNone(v.get("planificado_por_usuario_id"))
            self.guardar("agenda", dict(fixture=f, resultados=r, verificado=True))

    def test_operacion_viva_no_se_roba_y_bloqueo_sobrevive_redis(self):
        with motores() as e:
            f = crear_escenario(e, "LOCK", paquetes=1)
            d = self.entrega(f)
            s = Saga(e.db, "ENTREGA", d)
            s.bloquear([f"paquete:{f['paquetes'][0]}"])
            e.redis.delete(f"lock:entrega:paquete:{f['paquetes'][0]}")
            with self.assertRaises(OperacionOcupada):
                Saga.recuperar(e.db, e.db.operaciones.find_one({"_id": s.id}))
            r = entregar(
                e.redis, e.db, e.cql, dict(d, id_operacion="competidor-" + uuid4().hex)
            )
            self.assertFalse(r["exito"])
            self.assertEqual(
                e.db.paquetes.find_one({"_id": f["paquetes"][0]})["estado"],
                "EN_TRANSITO",
            )
            s.compensar([], "fin de prueba")
            self.guardar("propiedad", dict(fixture=f, resultado=r, verificado=True))

    def test_caida_proceso_y_recuperacion_idempotente(self):
        for tipo, punto in [
            ("ENTREGA", "CU06_CASSANDRA"),
            ("ENTREGA", "MONGO_PARCIAL"),
            ("ENTREGA", "CU06_REDIS_CONFIRM"),
            ("PLANIFICACION", "CU01_NEO4J"),
            ("REASIGNACION", "MONGO_PARCIAL"),
            ("REASIGNACION", "CU05_REDIS_CONFIRM"),
        ]:
            with self.subTest(tipo=tipo, punto=punto), motores() as e:
                f = crear_escenario(
                    e, "CAIDA", activo=tipo != "PLANIFICACION", paquetes=1
                )
                if tipo == "ENTREGA":
                    d = self.entrega(f)
                elif tipo == "REASIGNACION":
                    d = self.averia(f)
                else:
                    d = dict(
                        id_operacion=f["demo_id"],
                        id_ruta=f["ruta"],
                        id_vehiculo=f["vehiculos"][0],
                        id_conductor=f["conductores"][0],
                        paquetes=f["paquetes"],
                    )
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / "datos.json"
                    path.write_text(json.dumps(d))
                    hijo = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "tests.worker_caida",
                            tipo,
                            punto,
                            str(path),
                        ],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                self.assertEqual(hijo.returncode, 93, hijo.stdout + hijo.stderr)
                ident, _ = identidad(tipo, d)
                op = e.db.operaciones.find_one({"_id": ident})
                self.assertNotIn(op["estado"], ["COMPLETADO", "COMPENSADO"])
                if tipo != "PLANIFICACION":
                    tr = consultar_trazabilidad_completa(f["paquetes"][0])
                    self.assertFalse(tr["exito"])
                r = recuperar_operaciones(ident)
                self.assertTrue(r[0]["compensado"], r)
                r2 = recuperar_operaciones(ident)
                self.assertTrue(r2[0]["compensado"], r2)
                self.assertFalse(
                    e.db.bloqueos_operacion.find_one({"operacion_id": ident})
                )
                if tipo == "PLANIFICACION":
                    self.assertEqual(
                        e.db.paquetes.find_one({"_id": f["paquetes"][0]})["estado"],
                        "PENDIENTE",
                    )
                    self.assertFalse(e.db.viajes.find_one({"_id": op["viaje_id"]}))
                else:
                    self.verificar_restaura(e, f)
                self.guardar(
                    f"caida_{tipo}_{punto}",
                    dict(
                        fixture=f,
                        operacion=ident,
                        exit_code=93,
                        recuperacion=r,
                        repeticion=r2,
                        verificado=True,
                    ),
                )

    def test_ack_commit_perdido_no_revierte_entrega(self):
        from unittest.mock import patch

        real = Saga.guardar

        def perdido(saga, **campos):
            real(saga, **campos)
            if campos.get("estado") == "COMPLETADO":
                raise RuntimeError("ACK del commit perdido")

        with motores() as e:
            f = crear_escenario(e, "ACK_COMMIT", paquetes=1)
            d = self.entrega(f)
            with patch.object(Saga, "guardar", perdido):
                r = entregar(e.redis, e.db, e.cql, d)
            self.assertTrue(r["exito"], r)
            self.assertEqual(
                e.db.paquetes.find_one({"_id": f["paquetes"][0]})["estado"], "ENTREGADO"
            )
            recuperar_operaciones(r["saga_id"])
            self.assertFalse(
                e.db.bloqueos_operacion.find_one({"operacion_id": r["saga_id"]})
            )
            self.guardar("ack_commit", dict(fixture=f, resultado=r, verificado=True))

    def test_ack_commit_anomalia_y_cierre_no_reabre_operacion(self):
        from unittest.mock import patch
        from app.anomalias import procesar_anomalias_telemetria

        real = Saga.guardar

        def perdido(saga, **campos):
            real(saga, **campos)
            if campos.get("estado") == "COMPLETADO":
                raise RuntimeError("ACK perdido")

        with motores() as e:
            f = crear_escenario(e, "ACK_ALERTA")
            d, _ = emitir(f, 105)
            with patch.object(Saga, "guardar", perdido):
                r = procesar_anomalias_telemetria(d)
            self.assertTrue(r["exito"])
            op = e.db.operaciones.find_one(
                {"tipo": "ANOMALIA", "datos.id_evento": d["id_evento"]}
            )
            self.assertEqual(op["estado"], "COMPLETADO")
            recuperar_operaciones(op["_id"])
            normal = dict(d, id_evento=str(uuid4()), velocidad=40)
            with patch.object(Saga, "guardar", perdido):
                r2 = procesar_anomalias_telemetria(normal)
            self.assertTrue(r2["exito"])
            cierre = e.db.operaciones.find_one(
                {"tipo": "CIERRE_ANOMALIA", "datos.id_evento": normal["id_evento"]}
            )
            self.assertEqual(cierre["estado"], "COMPLETADO")
            recuperar_operaciones(cierre["_id"])
            self.guardar(
                "ack_commit_alerta",
                dict(fixture=f, resultado=r, cierre=r2, verificado=True),
            )

    def test_anomalia_cruza_dia_mas_de_15_lecturas_y_perdida_redis(self):
        from app.anomalias import procesar_anomalias_telemetria
        from app.repositorio_telemetria import registrar_medicion_cassandra
        from app.repositorio_alertas import obtener_alertas_abiertas_cassandra

        with motores() as e:
            f = crear_escenario(e, "MEDIANOCHE", paquetes=1)
            fin = datetime.now(timezone.utc).replace(
                hour=0, minute=5, second=0, microsecond=0
            )
            d = dict(
                vehiculo_patente=f["vehiculos"][0],
                viaje_id=f["viaje"],
                latitud=-34.7,
                longitud=-58.6,
                velocidad=0,
                estado_vehiculo="DETENIDO",
            )
            for i in range(45):
                fecha = fin - timedelta(seconds=(44 - i) * 15)
                registrar_medicion_cassandra(
                    e.cql, dict(d, id_evento=str(uuid4()), fecha_hora=fecha.isoformat())
                )
            evento = dict(d, id_evento=str(uuid4()), fecha_hora=fin.isoformat())
            r = procesar_anomalias_telemetria(evento)
            self.assertEqual(len(r["anomalias_detectadas"]), 1)
            alerta = r["anomalias_detectadas"][0]["alerta_id"]
            e.redis.delete(
                f"alerta:activa:{d['vehiculo_patente']}:PARADA_NO_PROGRAMADA"
            )
            r2 = procesar_anomalias_telemetria(dict(evento, id_evento=str(uuid4())))
            self.assertEqual(r2["anomalias_detectadas"][0]["alerta_id"], alerta)
            self.assertEqual(
                r2["anomalias_detectadas"][0]["estado"], "DEDUPLICADA_SOSTENIDA"
            )
            self.assertEqual(
                len(obtener_alertas_abiertas_cassandra(e.cql, d["vehiculo_patente"])), 1
            )
            procesar_anomalias_telemetria(
                dict(
                    evento,
                    id_evento=str(uuid4()),
                    velocidad=40,
                    estado_vehiculo="EN_MOVIMIENTO",
                )
            )
            self.assertEqual(
                obtener_alertas_abiertas_cassandra(e.cql, d["vehiculo_patente"]), []
            )
            self.guardar(
                "medianoche_deduplicacion",
                dict(fixture=f, resultado=r, repeticion=r2, verificado=True),
            )

    def test_alerta_parcial_cassandra_se_compensa(self):
        from unittest.mock import patch
        import app.anomalias as a
        from app.repositorio_alertas import obtener_alertas_abiertas_cassandra

        with motores() as e:
            f = crear_escenario(e, "ALERTA_PARCIAL")
            d, _ = emitir(f, 105)
            real = a.guardar_alerta_cassandra

            def ack_perdido(sesion, datos):
                real(sesion, datos)
                raise RuntimeError("ACK perdido tras escribir todas las proyecciones")

            with patch.object(a, "guardar_alerta_cassandra", side_effect=ack_perdido):
                with self.assertRaises(RuntimeError):
                    a.procesar_anomalias_telemetria(d)
            self.assertEqual(
                obtener_alertas_abiertas_cassandra(e.cql, d["vehiculo_patente"]), []
            )
            filas = list(
                e.cql.execute(
                    "SELECT * FROM logistica_flota.alertas_por_viaje_dia WHERE viaje_id=%s AND dia=%s",
                    (f["viaje"], datetime.now(timezone.utc).date()),
                )
            )
            self.assertEqual(filas, [])
            self.assertFalse(
                e.redis.exists(
                    f"alerta:activa:{d['vehiculo_patente']}:EXCESO_VELOCIDAD"
                )
            )
            self.guardar(
                "alerta_ack_perdido",
                dict(fixture=f, filas_residuales=0, verificado=True),
            )

    def test_compensacion_falla_y_reintenta(self):
        from unittest.mock import patch
        import app.flujos_durables as flujos

        with motores() as e:
            f = crear_escenario(e, "COMPENSACION", paquetes=1)
            d = self.entrega(f)
            with patch.object(
                flujos,
                "compensar_entrega_cassandra",
                side_effect=RuntimeError("Cassandra no disponible al compensar"),
            ):
                r = entregar(e.redis, e.db, e.cql, d, InyectorFallas("CU06_MONGO"))
            self.assertEqual(r["estado"], "COMPENSACION_PENDIENTE")
            self.assertIsNotNone(
                e.db.bloqueos_operacion.find_one({"operacion_id": r["id_operacion"]})
            )
            recuperado = recuperar_operaciones(r["id_operacion"])
            self.assertTrue(recuperado[0]["compensado"], recuperado)
            self.verificar_restaura(e, f)
            self.guardar(
                "compensacion_reintentada",
                dict(fixture=f, resultado=r, recuperacion=recuperado, verificado=True),
            )


if __name__ == "__main__":
    unittest.main()
