"""
Módulo para inyección de fallas controladas (CU-03).
Permite provocar fallas a voluntad en pasos específicos del flujo
para demostrar la consistencia y el rollback durante la defensa oral (Sección 5 del TPO).
"""

class FallaSimuladaError(RuntimeError):
    """Excepción lanzada intencionalmente para simular caídas en pasos específicos."""
    pass


class InyectorFallas:
    PUNTOS_FALLA = {
        "REDIS_CLAIM",         # Falla durante el claim inicial en Redis
        "CASSANDRA_WRITE",     # Falla al persistir la alerta en Cassandra
        "REDIS_CONFIRM",       # Falla al confirmar el estado ACTIVE en Redis
        "NOTIFICACION",        # Falla al emitir la alerta/notificación final
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

