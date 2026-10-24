
def validar_viaje(datos):
    campos_obligatorios = [
        "id_ruta",
        "id_vehiculo",
        "id_conductor",
        "paquetes"
    ]

    for campo in campos_obligatorios:
        if campo not in datos:
            return False, f"Falta el campo: {campo}"

    for campo in ["id_ruta", "id_vehiculo", "id_conductor"]:
        if not isinstance(datos[campo], str) or not datos[campo].strip():
            return False, f"El campo {campo} debe ser un texto no vacio"

    if not isinstance(datos["paquetes"], list):
        return False, "Los paquetes deben enviarse en una lista"

    if not datos["paquetes"]:
        return False, "El viaje debe tener al menos un paquete"

    if any(
        not isinstance(paquete, str) or not paquete.strip()
        for paquete in datos["paquetes"]
    ):
        return False, "Cada paquete debe tener un identificador valido"

    if len(datos["paquetes"]) != len(set(datos["paquetes"])):
        return False, "No se pueden repetir paquetes"

    return True, "Datos del viaje validos"
