from typing import Dict, Any
from app.conexiones import conectar_neo4j
from app.repositorio_rutas_alternativas import (
    identificar_viajes_afectados,
    buscar_camino_alternativo
)

def consultar_impacto_y_alternativa(
    origen_id: str,
    destino_id: str,
    punto_bloqueado_id: str
) -> Dict[str, Any]:
    driver = None
    try:
        driver = conectar_neo4j()
        
        # 1. Analizar el impacto del bloqueo
        afectados = identificar_viajes_afectados(driver, punto_bloqueado_id)
        
        # 2. Calcular ruta de escape
        camino = buscar_camino_alternativo(driver, origen_id, destino_id, punto_bloqueado_id)
        
        return {
            "exito": True,
            "punto_bloqueado": punto_bloqueado_id,
            "impacto": afectados,
            "alternativa": camino if camino else "No existe ruta alternativa posible."
        }
    except Exception as e:
        return {"exito": False, "error": str(e)}
    finally:
        if driver:
            driver.close()