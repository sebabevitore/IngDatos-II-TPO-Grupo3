
from app.repositorio_viajes import (
    registrar_viaje,
    eliminar_viaje
)


class ResultadoEliminacion:
    def __init__(self, cantidad):
        self.deleted_count = cantidad


class ColeccionSimulada:
    def __init__(self):
        self.documentos = {}

    def insert_one(self, documento):
        self.documentos[documento["_id"]] = documento

    def delete_one(self, filtro):
        id_viaje = filtro["_id"]

        if id_viaje in self.documentos:
            del self.documentos[id_viaje]
            return ResultadoEliminacion(1)

        return ResultadoEliminacion(0)


def main():
    coleccion = ColeccionSimulada()

    datos = {
        "id_ruta": "R001",
        "id_vehiculo": "V001",
        "id_conductor": "C001",
        "paquetes": ["P001", "P002"]
    }

    id_viaje = registrar_viaje(coleccion, datos)

    assert id_viaje in coleccion.documentos
    print("PRUEBA 1: Viaje registrado correctamente")

    documento = coleccion.documentos[id_viaje]

    assert documento["estado"] == "PLANIFICADO"
    assert len(documento["paquetes"]) == 2
    print("PRUEBA 2: Datos del viaje correctos")

    eliminado = eliminar_viaje(coleccion, id_viaje)

    assert eliminado is True
    assert id_viaje not in coleccion.documentos
    print("PRUEBA 3: Compensacion MongoDB correcta")

    print("TODAS LAS PRUEBAS PASARON")


if __name__ == "__main__":
    main()
