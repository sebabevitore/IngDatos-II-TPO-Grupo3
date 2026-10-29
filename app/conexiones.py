
import os
from dotenv import load_dotenv

from pymongo import MongoClient
from cassandra.cluster import Cluster
import redis
from neo4j import GraphDatabase

load_dotenv()



def conectar_mongodb():
    usuario = os.getenv("MONGO_USER")
    contrasena = os.getenv("MONGO_PASSWORD")

    if not usuario or not contrasena:
        raise RuntimeError(
            "Faltan MONGO_USER o MONGO_PASSWORD en el archivo .env"
        )

    cliente = MongoClient(
        host="localhost",
        port=27018,
        username=usuario,
        password=contrasena,
        authSource="admin",
        serverSelectionTimeoutMS=5000
    )

    try:
        cliente.admin.command("ping")
        return cliente
    except Exception:
        cliente.close()
        raise


def conectar_cassandra():
    host = os.getenv("CASSANDRA_HOST", "localhost")
    puerto = int(os.getenv("CASSANDRA_PORT", "9042"))

    cluster = Cluster([host], port=puerto)
    sesion = cluster.connect()
    return cluster, sesion


def conectar_redis():
    cliente = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        password=os.getenv("REDIS_PASSWORD"),
        decode_responses=True
    )
    cliente.ping()
    return cliente


def conectar_neo4j():
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "")
        )
    )

    try:
        driver.verify_connectivity()
        return driver
    except Exception:
        driver.close()
        raise