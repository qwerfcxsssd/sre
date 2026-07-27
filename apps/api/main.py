from fastapi import FastAPI
import time
import redis
import psycopg2
import os

app = FastAPI()

DB_HOST = os.getenv("DB_HOST", "postgres")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")

r=redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    count = r.incr("visits")
    return {"message": "hello its ingeneer from ts2", "visits": count}

@app.get("/slow")
def slow_endpoint():
    time.sleep(3)
    return {"massage": "хз чет перегрузилось"}

@app.get("/db-check")
def db_check():
    conn = psycopg2.connect(
        host=DB_HOST, dbname="sredb", user="sreuser", password="srepass"
    )
    cur = conn.cursor()
    cur.execute("SELECT 1")
    result = cur.fetchone()
    cur.close()
    conn.close()
    return {"db_result": result}
