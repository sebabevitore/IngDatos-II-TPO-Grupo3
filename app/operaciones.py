"""Bitácora durable y exclusión para sagas del laboratorio local.

Los bloqueos MongoDB no vencen: perder Redis nunca habilita un segundo escritor.
Una operación interrumpida se compensa al confirmar que su proceso local terminó.
No se roba una operación viva ni se asume que un timeout demuestra su muerte.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import socket
from uuid import uuid4
from pymongo.errors import DuplicateKeyError

TERMINALES = {"COMPLETADO", "COMPENSADO"}


def ahora():
    return datetime.now(timezone.utc)


def canon(datos):
    def normal(v):
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc).isoformat(timespec="milliseconds")
        raise TypeError(f"Tipo no serializable: {type(v).__name__}")

    return json.dumps(datos, sort_keys=True, default=normal, ensure_ascii=False)


def identidad(tipo, datos):
    clave = datos.get("id_operacion") or datos.get("clave_idempotencia")
    payload = {
        k: v
        for k, v in datos.items()
        if k not in ("id_operacion", "clave_idempotencia")
    }
    # Fecha generada por el servidor no forma parte del pedido del cliente.
    firma = hashlib.sha256(canon(payload).encode()).hexdigest()
    return (
        f"{tipo}-{hashlib.sha256(str(clave or firma).encode()).hexdigest()[:32]}",
        firma,
    )


def proceso_vivo(ejecutor):
    if not ejecutor:
        return False
    if ejecutor["host"] != socket.gethostname():
        # Sin un coordinador externo no se puede demostrar que murió otro host.
        return True
    try:
        os.kill(ejecutor["pid"], 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class OperacionOcupada(RuntimeError):
    pass


class Saga:
    def __init__(self, db, tipo, datos):
        self.db = db
        self.id, self.firma = identidad(tipo, datos)
        self.token = uuid4().hex
        self.ejecutor = dict(
            host=socket.gethostname(), pid=os.getpid(), token=self.token
        )
        self.doc = None
        try:
            db.operaciones.insert_one(
                dict(
                    _id=self.id,
                    version=2,
                    tipo=tipo,
                    firma=self.firma,
                    datos=deepcopy(datos),
                    estado="PROCESANDO",
                    fecha_inicio=ahora(),
                    ejecutor=self.ejecutor,
                    pasos=[],
                    snapshots=[],
                    recursos=[],
                )
            )
        except DuplicateKeyError:
            doc = db.operaciones.find_one({"_id": self.id})
            if doc.get("firma") != self.firma:
                raise ValueError("La clave de idempotencia ya identifica otro pedido")
            self.doc = doc
            return
        self.doc = db.operaciones.find_one({"_id": self.id})

    @property
    def propia(self):
        return self.doc.get("ejecutor", {}).get("token") == self.token

    def exigir_propiedad(self):
        if not self.db.operaciones.find_one(
            {"_id": self.id, "ejecutor.token": self.token}
        ):
            raise OperacionOcupada("La operación pertenece a otro ejecutor")

    def guardar(self, **campos):
        self.exigir_propiedad()
        res = self.db.operaciones.update_one(
            {"_id": self.id, "ejecutor.token": self.token}, {"$set": campos}
        )
        if res.matched_count != 1:
            raise OperacionOcupada("Se perdió la propiedad de la operación")
        self.doc.update(campos)

    def bloquear(self, recursos):
        for recurso in sorted(set(recursos)):
            self.exigir_propiedad()
            # Registrar intención antes de adquirir: recuperable si cae tras insert_one.
            self.db.operaciones.update_one(
                {"_id": self.id, "ejecutor.token": self.token},
                {"$addToSet": {"recursos": recurso}},
            )
            try:
                self.db.bloqueos_operacion.insert_one(
                    {"_id": recurso, "operacion_id": self.id}
                )
            except DuplicateKeyError:
                lock = self.db.bloqueos_operacion.find_one({"_id": recurso})
                if lock.get("operacion_id") != self.id:
                    raise OperacionOcupada(f"Recurso en operación: {recurso}")
        self.doc = self.db.operaciones.find_one({"_id": self.id})

    def snapshot(self, coleccion, ids):
        actuales = list(self.doc.get("snapshots", []))
        for ident in ids:
            if any(s["coleccion"] == coleccion and s["id"] == ident for s in actuales):
                continue
            actuales.append(
                dict(
                    coleccion=coleccion,
                    id=ident,
                    antes=self.db[coleccion].find_one({"_id": ident}),
                )
            )
        self.guardar(snapshots=actuales)

    def cambiar(self, coleccion, ident, campos):
        if not any(
            s["coleccion"] == coleccion and s["id"] == ident
            for s in self.doc["snapshots"]
        ):
            raise RuntimeError("Falta snapshot durable antes de escribir")
        self.exigir_propiedad()
        self.db[coleccion].update_one(
            {"_id": ident},
            {"$set": dict(campos, ultima_operacion=self.id)},
            upsert=True,
        )

    def paso(self, nombre, accion, inyector=None):
        pasos = list(self.doc["pasos"])
        if nombre not in pasos:
            pasos.append(nombre)
        self.guardar(pasos=pasos, paso_actual=nombre)
        if inyector:
            inyector.verificar(nombre)
        resultado = accion()
        self.db.operaciones.update_one(
            {"_id": self.id, "ejecutor.token": self.token},
            {"$addToSet": {"pasos_completados": nombre}},
        )
        return resultado

    def restaurar_mongo(self):
        for s in reversed(self.doc.get("snapshots", [])):
            self.exigir_propiedad()
            coll = self.db[s["coleccion"]]
            actual = coll.find_one({"_id": s["id"]})
            if not actual or actual.get("ultima_operacion") != self.id:
                continue
            filtro = {"_id": s["id"], "ultima_operacion": self.id}
            if s["antes"] is None:
                coll.delete_one(filtro)
            else:
                coll.replace_one(filtro, s["antes"])

    def liberar(self):
        self.exigir_propiedad()
        self.db.bloqueos_operacion.delete_many({"operacion_id": self.id})

    def completar(self, resultado):
        self.guardar(estado="COMPLETADO", resultado=resultado, fecha_fin=ahora())
        try:
            self.liberar()
        except Exception:
            # El commit durable ya ocurrió. Solo queda limpiar bloqueos, nunca
            # convertir un éxito observable en un rollback posterior.
            return dict(resultado, limpieza_pendiente=True)
        return resultado

    def compensar(self, acciones, error):
        actual = self.db.operaciones.find_one({"_id": self.id})
        if actual and actual.get("estado") == "COMPLETADO":
            return actual["resultado"]
        self.guardar(estado="COMPENSANDO", error=str(error))
        errores = []
        for nombre, accion in acciones:
            try:
                self.exigir_propiedad()
                accion()
                self.db.operaciones.update_one(
                    {"_id": self.id, "ejecutor.token": self.token},
                    {"$addToSet": {"compensaciones_completadas": nombre}},
                )
            except Exception as exc:
                errores.append(f"{nombre}: {exc}")
        estado = "COMPENSACION_PENDIENTE" if errores else "COMPENSADO"
        self.guardar(estado=estado, errores_compensacion=errores)
        if errores:
            self.guardar(ejecutor={})
        if not errores:
            self.liberar()
        return dict(
            exito=False,
            saga_id=self.id,
            id_operacion=self.id,
            error=str(error),
            compensado=not errores,
            estado=estado,
            errores_compensacion=errores,
        )

    @classmethod
    def recuperar(cls, db, doc):
        if proceso_vivo(doc.get("ejecutor")):
            raise OperacionOcupada("El ejecutor sigue vivo o pertenece a otro host")
        saga = object.__new__(cls)
        saga.db, saga.id = db, doc["_id"]
        saga.token = uuid4().hex
        saga.ejecutor = dict(
            host=socket.gethostname(), pid=os.getpid(), token=saga.token
        )
        res = db.operaciones.update_one(
            {"_id": saga.id, "ejecutor": doc.get("ejecutor")},
            {"$set": {"ejecutor": saga.ejecutor}},
        )
        if res.matched_count != 1:
            raise OperacionOcupada("Otro recuperador tomó la operación")
        saga.doc = db.operaciones.find_one({"_id": saga.id})
        return saga


def operacion_pendiente(db, recursos):
    return db.bloqueos_operacion.find_one({"_id": {"$in": recursos}})
