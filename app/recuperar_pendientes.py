
from app.telemetria import recuperar_telemetria_pendiente


if __name__ == "__main__":
    exito, resultado = recuperar_telemetria_pendiente(limite=100)

    print("Recuperación exitosa:", exito)
    print("Resultado:", resultado)
