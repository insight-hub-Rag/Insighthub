import logging
from contextlib import asynccontextmanager

# pyrefly: ignore [missing-import]
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import router, health_router
from app.admin.connectors.router import router as connectors_router
from app.admin.users.router import router as users_router
from app.dashboard.router import router as dashboard_router
from app.documents.router import router as documents_router
from app.auth.router import router as auth_router
from app.auth.dependencies import get_current_user
from app.db.init_db import initialize_database_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_database_schema()
    yield


app = FastAPI(title="InsightHub", version="0.1.0", lifespan=lifespan)


# ── CORS ────────────────────────────────────────────────────────────────────
# Autorise le frontend Next.js (port 3000 en dev ET en Docker)
# à appeler l'API sans que le navigateur ne bloque la requête.
# allow_credentials=True est requis pour que le cookie refresh_token
# (httpOnly, posé par /auth/login) parte bien sur les requêtes cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",      # Next.js dev local
        "http://frontend:3000",       # Next.js dans Docker (service name)
        "https://d2w746ndepgb8z.cloudfront.net",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes publiques — aucune authentification requise ──────────────────────
app.include_router(auth_router)
app.include_router(health_router)

# ── Routes protégées — Depends(get_current_user) exigé sur chaque appel ─────
# Un seul point de vérité : tout nouvel endpoint ajouté dans l'un de ces
# routers hérite automatiquement de la protection, sans rien à répéter.
app.include_router(router, dependencies=[Depends(get_current_user)])
app.include_router(connectors_router, dependencies=[Depends(get_current_user)])
app.include_router(users_router, dependencies=[Depends(get_current_user)])
app.include_router(dashboard_router, dependencies=[Depends(get_current_user)])
app.include_router(documents_router, dependencies=[Depends(get_current_user)])