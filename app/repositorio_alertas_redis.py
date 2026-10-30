import os
from typing import Optional, Dict, Any, Tuple
import redis

# Scripts Lua cargados en memoria
_SHA_CLAIM: Optional[str] = None
_SHA_LIBERAR: Optional[str] = None


def _obtener_sha_claim(cliente: redis.Redis) -> str:
    global _SHA_CLAIM
    if _SHA_CLAIM is None or not cliente.script_exists(_SHA_CLAIM)[0]:
        ruta = os.path.join("redis", "07_claim_alerta.lua")
        with open(ruta, "r", encoding="utf-8") as f:
            script = f.read()
        _SHA_CLAIM = cliente.script_load(script)
    return _SHA_CLAIM


def _obtener_sha_liberar(cliente: redis.Redis) -> str:
    global _SHA_LIBERAR
    if _SHA_LIBERAR is None or not cliente.script_exists(_SHA_LIBERAR)[0]:
        ruta = os.path.join("redis", "08_liberar_alerta.lua")
        with open(ruta, "r", encoding="utf-8") as f:
            script = f.read()
        _SHA_LIBERAR = cliente.script_load(script)
    return _SHA_LIBERAR


def clave_alerta_activa(patente: str, tipo: str) -> str:
    """Genera la clave uniforme para la anomalía activa en Redis."""
    return f"alerta:activa:{patente.strip()}:{tipo.strip()}"


def reclamar_anomalia_redis(
    cliente: redis.Redis,
    patente: str,
    tipo: str,
    alerta_id: str,
    viaje_id: Optional[str],
    dia: str,
    fecha_hora_iso: str,
    ttl_pending: int = 30,
    ttl_activo: int = 120
) -> Tuple[bool, str]:
    """
    Intenta reclamar la anomalía en Redis de forma atómica.
    
    Retorna:
        (True, "NUEVO_CLAIM"): La anomalía es nueva. Se reservó con estado PENDING.
        (False, "DEDUPLICADO"): La anomalía ya estaba activa. Se extendió el TTL y se incrementó el contador.
    """
    clave = clave_alerta_activa(patente, tipo)
    sha = _obtener_sha_claim(cliente)

    resultado = cliente.evalsha(
        sha,
        1,
        clave,
        alerta_id,
        viaje_id or "",
        str(dia),
        fecha_hora_iso,
        ttl_pending,
        ttl_activo
    )

    if resultado == 1:
        return True, "NUEVO_CLAIM"
    else:
        return False, "DEDUPLICADO"


def confirmar_anomalia_redis(
    cliente: redis.Redis,
    patente: str,
    tipo: str,
    alerta_id: str,
    ttl_activo: int = 120
) -> bool:
    """
    Confirma el paso a estado ACTIVE en Redis una vez persistido en Cassandra.
    Verifica que el alerta_id siga siendo el mismo antes de confirmar.
    """
    clave = clave_alerta_activa(patente, tipo)
    id_almacenado = cliente.hget(clave, "alerta_id")

    if id_almacenado == alerta_id:
        pipe = cliente.pipeline()
        pipe.hset(clave, "estado", "ACTIVE")
        pipe.expire(clave, ttl_activo)
        pipe.execute()
        return True
    return False


def compensar_claim_redis(
    cliente: redis.Redis,
    patente: str,
    tipo: str,
    alerta_id: str
) -> bool:
    """
    Acción de compensación (Rollback): Libera la clave en Redis si la escritura
    en Cassandra falló, permitiendo que eventos futuros reintenten limpiamente.
    """
    clave = clave_alerta_activa(patente, tipo)
    sha = _obtener_sha_liberar(cliente)
    resultado = cliente.evalsha(sha, 1, clave, alerta_id)
    return resultado == 1


def obtener_alerta_activa_redis(
    cliente: redis.Redis,
    patente: str,
    tipo: str
) -> Optional[Dict[str, str]]:
    """Obtiene los datos de la alerta activa desde Redis si existe."""
    clave = clave_alerta_activa(patente, tipo)
    datos = cliente.hgetall(clave)
    return datos if datos else None


def resolver_anomalia_redis(
    cliente: redis.Redis,
    patente: str,
    tipo: str,
    alerta_id: str
) -> bool:
    """Elimina la clave de anomalía activa al resolverse la condición."""
    return compensar_claim_redis(cliente, patente, tipo, alerta_id)

