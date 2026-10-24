
from app.reservas import reservar_recursos


class RedisSimulado:
    def __init__(self):
        self.datos = {}

    def set(self, clave, valor, nx=False, ex=None):
        if nx and clave in self.datos:
            return False
        self.datos[clave] = valor
        return True

    def eval(self, script, cantidad_claves, clave, token):
        if self.datos.get(clave) == token:
            del self.datos[clave]
            return 1
        return 0


def main():
    redis = RedisSimulado()

    # Primera reserva: debe funcionar
    resultado1 = reservar_recursos(redis, "V001", "C001")
    assert resultado1[0] is True
    print("PRUEBA 1: Reserva inicial correcta")

    # Segundo viaje intenta usar el mismo vehiculo
    resultado2 = reservar_recursos(redis, "V001", "C002")
    assert resultado2[0] is False
    print("PRUEBA 2: Vehiculo ocupado detectado")

    # Tercer viaje intenta usar el mismo conductor
    resultado3 = reservar_recursos(redis, "V002", "C001")
    assert resultado3[0] is False

    # El vehiculo V002 debe haberse liberado
    assert "reserva:vehiculo:V002" not in redis.datos
    print("PRUEBA 3: Compensacion correcta")

    print("TODAS LAS PRUEBAS PASARON")


if __name__ == "__main__":
    main()
