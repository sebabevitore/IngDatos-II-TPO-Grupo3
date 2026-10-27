
from app.conexiones import (
    conectar_mongodb,
    conectar_cassandra,
    conectar_redis,
    conectar_neo4j
)


def main():
    print("=== PRUEBA DE CONEXIONES ===")

    try:
        cliente = conectar_mongodb()
        print("[OK] MongoDB conectado")
        cliente.close()
    except Exception as error:
        print("[ERROR] MongoDB:", error)

    try:
        cluster, sesion = conectar_cassandra()
        print("[OK] Cassandra conectado")
        cluster.shutdown()
    except Exception as error:
        print("[ERROR] Cassandra:", error)

    try:
        cliente = conectar_redis()
        print("[OK] Redis conectado")
        cliente.close()
    except Exception as error:
        print("[ERROR] Redis:", error)

    try:
        driver = conectar_neo4j()
        print("[OK] Neo4j conectado")
        driver.close()
    except Exception as error:
        print("[ERROR] Neo4j:", error)


if __name__ == "__main__":
    main()
