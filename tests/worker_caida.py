"""Proceso hijo usado por las pruebas de recuperación; os._exit simula una caída real."""

import json, os, sys
from app.demo_comun import motores
from app.operaciones import Saga
from app.flujos_durables import entregar, planificar, reasignar


def main():
    tipo, punto, archivo = sys.argv[1:]
    datos = json.load(open(archivo))
    original = Saga.paso
    cambiar = Saga.cambiar

    def paso(self, nombre, accion, inyector=None):
        resultado = original(self, nombre, accion, inyector)
        if nombre == punto:
            os._exit(93)
        return resultado

    def escritura(self, coleccion, ident, campos):
        cambiar(self, coleccion, ident, campos)
        if punto == "MONGO_PARCIAL" and coleccion == "paquetes":
            os._exit(93)

    Saga.paso = paso
    Saga.cambiar = escritura
    with motores() as e:
        if tipo == "ENTREGA":
            entregar(e.redis, e.db, e.cql, datos)
        elif tipo == "PLANIFICACION":
            planificar(e.redis, e.db, datos, e.neo)
        else:
            reasignar(e.redis, e.db, e.neo, datos)
    raise AssertionError("No se alcanzó el punto de caída")


if __name__ == "__main__":
    main()
