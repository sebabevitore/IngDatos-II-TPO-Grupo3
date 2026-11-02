"""Ejecuta la validación y guarda evidencia con versión y huella del código."""

import argparse
from datetime import datetime, timezone
import hashlib, json, os
from pathlib import Path
import subprocess, sys


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--integracion",
        action="store_true",
        help="Requiere cuatro motores locales; crea fixtures exclusivas",
    )
    p.add_argument("--salida", type=Path)
    a = p.parse_args()
    carpeta = a.salida or Path("evidencias") / (
        "validacion-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    carpeta.mkdir(parents=True, exist_ok=False)
    entorno = dict(os.environ)
    tareas = [("reglas", [sys.executable, "-m", "unittest", "tests.test_reglas", "-v"])]
    if a.integracion:
        entorno["TPO_INTEGRACION"] = "1"
        tareas.append(
            (
                "integracion",
                [sys.executable, "-m", "unittest", "tests.test_integracion", "-v"],
            )
        )
        tareas.extend(
            (f"menu_cu{i:02d}", [sys.executable, "-m", f"app.menu_cu{i:02d}", "--all"])
            for i in range(1, 8)
        )
    resumen = []
    for nombre, cmd in tareas:
        # Timeout no se confunde con una prueba aprobada; queda en el informe.
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, env=entorno, timeout=300
            )
            codigo = r.returncode
            salida = r.stdout + "\n" + r.stderr
        except subprocess.TimeoutExpired as exc:
            codigo = 124
            salida = str(exc)
        (carpeta / f"{nombre}.log").write_text(salida)
        resumen.append(
            dict(prueba=nombre, comando=cmd, codigo_salida=codigo, aprobada=codigo == 0)
        )
        print(nombre, "OK" if codigo == 0 else "ERROR", flush=True)

    def git(*args):
        r = subprocess.run(["git", *args], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    archivos = {
        str(f): hashlib.sha256(f.read_bytes()).hexdigest()
        for root in ["app", "tests", "redis", "mongodb", "cassandra", "neo4j"]
        for f in Path(root).rglob("*")
        if f.is_file() and "__pycache__" not in f.parts
    }
    for nombre in ["requirements.txt", "docker-compose.yml"]:
        archivos[nombre] = hashlib.sha256(Path(nombre).read_bytes()).hexdigest()
    manifiesto = dict(
        fecha_utc=datetime.now(timezone.utc).isoformat(),
        rama=git("branch", "--show-current"),
        commit_base=git("rev-parse", "HEAD"),
        cambios_sin_commit=git("status", "--short"),
        sha256_archivos=archivos,
        motores_reales=a.integracion,
        resultados=resumen,
        aprobada=all(r["aprobada"] for r in resumen),
    )
    (carpeta / "resultado.json").write_text(
        json.dumps(manifiesto, ensure_ascii=False, indent=2)
    )
    print(carpeta / "resultado.json")
    return 0 if manifiesto["aprobada"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
