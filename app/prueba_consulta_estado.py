
from app.consulta_telemetria import consultar_estado_actual


exito, resultado = consultar_estado_actual("AB123CD")

print("Éxito:", exito)
print("Resultado:", resultado)
