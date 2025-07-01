# backend/main.py
import uuid
from io import BytesIO
from httpx import Timeout
import numpy as np
import sqlalchemy
import httpx
from fastapi import FastAPI, HTTPException, File, UploadFile, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from databases import Database
from sqlalchemy import func
import traceback

# --- Configuración de la base de datos Render (Postgres) ---
DATABASE_URL = "postgresql://tensorflow_db_user:o6XOvQOaOz544C70R7m8r98BNBFHC1Rr@dpg-d1gbuc7fte5s738f64qg-a.oregon-postgres.render.com:5432/tensorflow_db"

database = Database(DATABASE_URL)

# --- Definición de tabla jobs con SQLAlchemy Core ---
metadata = sqlalchemy.MetaData()
jobs = sqlalchemy.Table(
    "jobs",
    metadata,
    sqlalchemy.Column("job_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("status", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("class", sqlalchemy.String, nullable=True),
    sqlalchemy.Column("score", sqlalchemy.Float, nullable=True),
    sqlalchemy.Column("detail", sqlalchemy.Text, nullable=True),
    sqlalchemy.Column(
        "created_at",
        sqlalchemy.DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    ),
    sqlalchemy.Column(
        "updated_at",
        sqlalchemy.DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    ),
)

# Crea la tabla si no existe
engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

# --- Configuración de la app FastAPI ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Etiquetas y endpoint del modelo
LABELS = [
    "Angus",
    "Belted Galloway",
    "Charolais",
    "Desconocido",
    "Highland",
    "Limousin"
]

#TF_SERVING_URL = (
#    "https://modelo-cocina-314745621240.europe-west1.run.app"
#    "/v1/models/modelo_cocina:predict"
#)


TF_SERVING_URL = "https://modelo-tensorflow-cattle.onrender.com/v1/models/modelo_cocina:predict"


# --- Eventos de inicio y cierre para la conexión a BD ---
@app.on_event("startup")
async def startup():
    await database.connect()

@app.on_event("shutdown")
async def shutdown():
    await database.disconnect()

# --- Endpoint: recibe imagen y devuelve job_id ---
@app.post("/predict-image")
async def submit_predict(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    contents = await file.read()
    job_id = str(uuid.uuid4())

    # Inserta registro inicial en la base de datos
    await database.execute(
        jobs.insert().values(job_id=job_id, status="pending")
    )

    # Encola el procesamiento en background
    background_tasks.add_task(process_job, job_id, contents)
    return {"job_id": job_id}

# --- Función que procesa la imagen y actualiza el job ---
async def process_job(job_id: str, contents: bytes):
    try:
        # Preprocesamiento de la imagen
        img = Image.open(BytesIO(contents)).convert("RGB").resize((224,224))
        arr = np.array(img, dtype="float32") / 255.0
        payload = {"instances": [arr.tolist()]}

        # Llamada al modelo SIN timeout explícito
        
        async with httpx.AsyncClient(timeout=None) as client:
            resp = await client.post(TF_SERVING_URL, json=payload)
        resp.raise_for_status()

        # Postprocesamiento de la respuesta
        data = resp.json()
        scores = data["predictions"][0]
        idx = int(np.argmax(scores))
        etiqueta = LABELS[idx]
        puntaje = float(scores[idx])

        # Actualiza registro en BD con resultado
        await database.execute(
            jobs.update()
            .where(jobs.c.job_id == job_id)
            .values(
                status="done",
                **{"class": etiqueta},
                score=puntaje
            )
        )
    except Exception as e:
        # Log completo al servidor
        err = traceback.format_exc()
        print(f"[ERROR] Fallo en job {job_id}:\n{err}")

        # Actualiza la BD con el mensaje
        await database.execute(
            jobs.update()
                .where(jobs.c.job_id == job_id)
                .values(status="error", detail=str(e))
        )

# --- Endpoint: consulta estado del job ---
@app.get("/predict-status/{job_id}")
async def get_status(job_id: str):
    row = await database.fetch_one(
        sqlalchemy.select(
            jobs.c.status,
            jobs.c["class"],
            jobs.c.score,
            jobs.c.detail
        ).where(jobs.c.job_id == job_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Job no encontrado")

    result = {"status": row["status"]}
    if row["status"] == "done":
        result["class"] = row["class"]
        result["score"] = row["score"]
    elif row["status"] == "error":
        result["detail"] = row["detail"]
    return result

# --- Health check ---
@app.get("/health")
def health():
    return {"status": "ok"}
