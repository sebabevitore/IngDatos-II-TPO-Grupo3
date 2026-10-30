"""
Repositorio Redis para el Caso de Uso 5 (Reasignación por avería).
Responsable del control de concurrencia, reservas atómicas en memoria (SET NX)
y actualización inmediata de estados operativos de vehículos y conductores.
"""

from typing import Tuple, Optional, Dict, Any
import redis

# Script Lua para liberación condicional de reservas (Compare-and-Delete)
SCRIPT_LIBERAR_RESERVA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


def reservar_reemplazo_redis(
    cliente: redis.Redis,
    patente_reemplazo: str,
    conductor_reemplazo: str,
    token_saga: str,
    ttl_segundos: int = 120
) -> Tuple[bool, str]:
    """
    Intenta reservar atómicamente el vehículo y conductor de reemplazo.
    Evita condiciones de carrera entre coordinadores concurrentes.
    
    Devuelve:
        (True, "OK"): Ambos recursos reservados exitosamente.
        (False, motivo): Alguno de los recursos ya estaba ocupado o en avería.
    """
    clave_vehiculo = f"reserva:vehiculo:{patente_reemplazo.strip()}"
    clave_conductor = f"reserva:conductor:{conductor_reemplazo.strip()}"

    # 1. Verificar si el vehículo de reemplazo figura como AVERIADO en su estado operativo
    clave_estado_veh = f"vehiculo:{patente_reemplazo.strip()}:estado"
    estado_actual = cliente.hget(clave_estado_veh, "estado")
    if estado_actual in ["AVERIADO", "EN_MANTENIMIENTO"]:
        return False, f"El vehículo {patente_reemplazo} no está operativo (estado actual: {estado_actual})"

    # 2. Adquirir lock atómico del vehículo
    vehiculo_adquirido = cliente.set(
        clave_vehiculo,
        token_saga,
        nx=True,
        ex=ttl_segundos
    )
    if not vehiculo_adquirido:
        return False, f"El vehículo {patente_reemplazo} ya está reservado o asignado por otra operación"

    # 3. Adquirir lock atómico del conductor
    try:
        conductor_adquirido = cliente.set(
            clave_conductor,
            token_saga,
            nx=True,
            ex=ttl_segundos
        )
    except Exception:
        # Rollback inmediato del vehículo si falló la llamada
        compensar_reserva_redis(cliente, patente_reemplazo, None, token_saga)
        raise

    if not conductor_adquirido:
        # Rollback: liberar el vehículo porque no conseguimos al chofer
        compensar_reserva_redis(cliente, patente_reemplazo, None, token_saga)
        return False, f"El conductor {conductor_reemplazo} ya está reservado por otra operación"

    return True, "OK"


def compensar_reserva_redis(
    cliente: redis.Redis,
    patente_reemplazo: Optional[str],
    conductor_reemplazo: Optional[str],
    token_saga: str
):
    """
    Acción de compensación (Rollback): Libera los locks temporales adquiridos
    únicamente si siguen perteneciendo a este saga_id (evita liberar locks ajenos).
    """
    if patente_reemplazo:
        clave_vehiculo = f"reserva:vehiculo:{patente_reemplazo.strip()}"
        cliente.eval(SCRIPT_LIBERAR_RESERVA, 1, clave_vehiculo, token_saga)

    if conductor_reemplazo:
        clave_conductor = f"reserva:conductor:{conductor_reemplazo.strip()}"
        cliente.eval(SCRIPT_LIBERAR_RESERVA, 1, clave_conductor, token_saga)


def consolidar_estados_redis(
    cliente: redis.Redis,
    patente_averiada: str,
    patente_reemplazo: str,
    id_viaje_rescate: str,
    token_saga: str
):
    """
    Paso final: Consolida los estados operativos definitivos en Redis
    y retira las reservas temporales.
    """
    pipe = cliente.pipeline()

    # 1. Vehículo averiado pasa a estado AVERIADO
    clave_estado_averiado = f"vehiculo:{patente_averiada.strip()}:estado"
    pipe.hset(clave_estado_averiado, mapping={
        "estado": "AVERIADO",
        "motivo": "AVERIA_MECANICA_EN_RUTA"
    })

    # 2. Vehículo de reemplazo pasa a estado EN_VIAJE vinculado al viaje de rescate
    clave_estado_reemplazo = f"vehiculo:{patente_reemplazo.strip()}:estado"
    pipe.hset(clave_estado_reemplazo, mapping={
        "estado": "EN_VIAJE",
        "viaje_id": id_viaje_rescate
    })

    # 3. Liberar locks transitorios de reserva
    clave_reserva_veh = f"reserva:vehiculo:{patente_reemplazo.strip()}"
    pipe.delete(clave_reserva_veh)

    pipe.execute()


def obtener_estado_vehiculo_redis(cliente: redis.Redis, patente: str) -> Dict[str, str]:
    """Recupera el hash de estado de un vehículo."""
    clave = f"vehiculo:{patente.strip()}:estado"
    return cliente.hgetall(clave)

