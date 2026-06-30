from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router
from app.db.init_db import initialize_database_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_database_schema()
    yield


app = FastAPI(title="InsightHub", version="0.1.0", lifespan=lifespan)
app.include_router(router)