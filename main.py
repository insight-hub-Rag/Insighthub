from contextlib import asynccontextmanager

# pyrefly: ignore [missing-import]
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router
from app.db.init_db import initialize_database_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_database_schema()
    yield


app = FastAPI(title="InsightHub", version="0.1.0", lifespan=lifespan)

# ── CORS ────────────────────────────────────────────────────────────────────
# Autorise le frontend Next.js (port 3000 en dev ET en Docker)
# à appeler l'API sans que le navigateur ne bloque la requête.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",      # Next.js dev local
        "http://frontend:3000",       # Next.js dans Docker (service name)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
