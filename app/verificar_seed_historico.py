"""Verifica el seed persistente sin exigir que Redis conserve una posición antigua.

La validación estricta original sigue disponible en cargar_datos --solo-validar.
Después de simular GPS, la posición Redis debe avanzar; se verifica por simulación,
no restaurando el estado viejo del seed.
"""

import argparse, json
from contextlib import ExitStack
from pathlib import Path
from app.cargar_datos import generar, normal, validar_local, digest, Motores


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--manifiesto", type=Path, default=Path("seed_resultados/manifiesto.json")
    )
    p.add_argument(
        "--salida", type=Path, default=Path("evidencias/seed-historico.json")
    )
    a = p.parse_args()
    m = json.loads(a.manifiesto.read_text())
    data = normal(generar(m["mediciones"]))
    validar_local(data)
    if digest(data) != m["sha256_datos"]:
        raise ValueError("El código generador no reproduce el manifiesto")
    # Exclusión explícita de proyecciones mutables; no se inventa su validación.
    data = dict(data, redis={})
    with ExitStack() as stack:
        motores = Motores(stack)
        lecturas = motores.verificar(data)
    lecturas.pop("redis_claves", None)
    resultado = dict(
        estado="PERSISTENCIA_SEED_VERIFICADA",
        motores_reales=True,
        sha256_datos=m["sha256_datos"],
        mediciones_logicas=m["mediciones"],
        lectura_motores=lecturas,
        redis="No comparado con snapshot inicial; consultar evidencia de simulación de flota",
    )
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps(resultado, ensure_ascii=False, indent=2))
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
