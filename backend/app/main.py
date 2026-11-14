from fastapi import FastAPI

from backend.app.api.calculations import (
    router as calculations_router,
)
from backend.app.api.health import (
    router as health_router,
)


app = FastAPI(
    title="Sync-Lnk API",
    version="0.1.0"
)


app.include_router(health_router)
app.include_router(calculations_router)