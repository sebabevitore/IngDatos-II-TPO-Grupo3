"""
Módulo para inyección de fallas controladas (CU-01, CU-03, CU-05 y CU-06).
Permite provocar fallas a voluntad en pasos específicos del flujo
para demostrar la consistencia y el rollback durante la defensa oral (Sección 5 del TPO).
"""

class FallaSimuladaError(RuntimeError):
    """Excepción lanzada intencionalmente para simular caídas en pasos específicos."""
    pass


class InyectorFallas:
    PUNTOS_FALLA = {
        # CU-03 (Detección de anomalías)
        "REDIS_CLAIM",         # Falla durante el claim inicial en Redis
        "CASSANDRA_WRITE",     # Falla al persistir la alerta en Cassandra
        "REDIS_CONFIRM",       # Falla al confirmar el estado ACTIVE en Redis
        "NOTIFICACION",        # Falla al emitir la alerta/notificación final

        # CU-05 (Reasignación por avería)
        "CU05_REDIS_RESERVA",  # Falla al reservar vehículo/chofer en Redis
        "CU05_NEO4J",          # Falla al validar/vincular la ruta en Neo4j
        "CU05_MONGO",          # Falla al persistir reasignación en MongoDB
        "CU05_REDIS_CONFIRM",  # Falla al consolidar estados en Redis

        # CU-06 (Confirmación de entrega)
        "CU06_REDIS_LOCK",     # Falla al adquirir lock de entrega en Redis
        "CU06_CASSANDRA",      # Falla al registrar evento inmutable en Cassandra
        "CU06_MONGO",          # Falla al actualizar paquete/asignación en MongoDB
        "CU06_REDIS_CONFIRM",  # Falla al actualizar contadores en Redis
    }

    def __init__(self, punto_falla: str = None):
        """
        punto_falla: Uno de PUNTOS_FALLA o None para ejecución normal.
        """
        if punto_falla and punto_falla.upper() not in self.PUNTOS_FALLA:
            raise ValueError(
                f"Punto de falla '{punto_falla}' no reconocido. "
                f"Opciones válidas: {sorted(list(self.PUNTOS_FALLA))}"
            )
        self.punto_falla = punto_falla.upper() if punto_falla else None

    def verificar(self, punto_actual: str):
        """Si el punto actual coincide con el punto configurado, lanza una excepción."""
        if self.punto_falla and self.punto_falla == punto_actual.upper():
            raise FallaSimuladaError(
                f"[SIMULACIÓN DE FALLA] Error provocado intencionalmente en el paso: '{punto_actual}'"
            )
