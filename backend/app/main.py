from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.calculations import router as calculations_router
from backend.app.api.health import router as health_router
from backend.app.api.real_estate import router as real_estate_router

app = FastAPI(title="Sync-Lnk API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(calculations_router)
app.include_router(real_estate_router, prefix="/api/v1")