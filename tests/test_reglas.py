import unittest
from datetime import datetime, timedelta, timezone
from app.geometria import proyectar_segmento, seleccionar_tramo
from app.eta import estimar_restante
from app.tiempos import intervalo, solapan, paradas_planificadas
from app.reglas_anomalias import evaluar_parada_prolongada


class ReglasTest(unittest.TestCase):
    def test_punto_intermedio_no_es_desvio(self):
        a = dict(latitud=-34.6, longitud=-58.4)
        b = dict(latitud=-34.6, longitud=-58.6)
        d, t = proyectar_segmento(-34.6, -58.5, a, b)
        self.assertLess(d, 0.001)
        self.assertAlmostEqual(t, 0.5)

    def test_en_parada_intermedia_toma_siguiente_tramo(self):
        r = [dict(orden=i, punto_id=str(i), latitud=0, longitud=i) for i in range(3)]
        i, t, d = seleccionar_tramo(r, 0, 1, [])
        self.assertEqual(i, 1)
        self.assertEqual(t, 0)

    def test_eta_cambia_con_avance_y_velocidad(self):
        t = dict(tiempo_estimado_min=20, distancia_km=10)
        self.assertAlmostEqual(estimar_restante(t, [20], 0.5, 30), 10)
        self.assertLess(estimar_restante(t, [20], 0.75, 30), 10)
        self.assertLess(estimar_restante(t, [20], 0.5, 60), 10)
        self.assertEqual(estimar_restante(t, [], 0.5, 0), 10)

    def test_intervalos_adyacentes_permitidos(self):
        a = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.assertFalse(
            solapan(
                a,
                a + timedelta(hours=1),
                a + timedelta(hours=1),
                a + timedelta(hours=2),
            )
        )
        self.assertTrue(
            solapan(
                a,
                a + timedelta(hours=2),
                a + timedelta(hours=1),
                a + timedelta(hours=3),
            )
        )

    def test_horarios_invalidos_rechazados(self):
        a = datetime(2026, 11, 1, tzinfo=timezone.utc)
        with self.assertRaises(ValueError):
            intervalo(dict(inicio_planificado=a, fin_planificado=a))
        with self.assertRaises(ValueError):
            paradas_planificadas(
                ["a", "b"],
                dict(
                    paradas=[
                        dict(punto_entrega_id="a", hora_planificada=a),
                        dict(punto_entrega_id="b", hora_planificada=a),
                    ]
                ),
                a,
                a + timedelta(hours=1),
            )

    def test_detencion_cruza_medianoche_y_programada_no_alerta(self):
        a = datetime(2026, 11, 2, 0, 5, tzinfo=timezone.utc)
        d = dict(fecha_hora=a.isoformat(), velocidad=0, estado_vehiculo="DETENIDO")
        h = [
            dict(
                fecha_hora=(a - timedelta(minutes=11)).isoformat(),
                velocidad=0,
                estado_vehiculo="DETENIDO",
            )
        ]
        self.assertIsNotNone(evaluar_parada_prolongada(d, h, 10))
        self.assertIsNone(evaluar_parada_prolongada(d, h, 10, parada_programada=True))

    def test_estado_detencion_no_anula_velocidad_positiva(self):
        a = datetime(2026, 11, 1, tzinfo=timezone.utc)
        d = dict(
            fecha_hora=(a + timedelta(minutes=11)).isoformat(),
            velocidad=0,
            estado_vehiculo="DETENIDO",
        )
        h = [dict(fecha_hora=a.isoformat(), velocidad=30, estado_vehiculo="DETENIDO")]
        self.assertIsNone(evaluar_parada_prolongada(d, h, 10))


if __name__ == "__main__":
    unittest.main()
