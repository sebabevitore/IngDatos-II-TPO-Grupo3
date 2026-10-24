
import os
from dotenv import load_dotenv

from pymongo import MongoClient
from cassandra.cluster import Cluster
import redis
from neo4j import GraphDatabase

load_dotenv()


def conectar_mongodb():
    cliente = MongoClient(
        os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        serverSelectionTimeoutMS=5000
    )
    cliente.admin.command("ping")
    return cliente


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
    driver.verify_connectivity()
    return driver
