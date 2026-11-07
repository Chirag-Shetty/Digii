from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.rider import router as rider_router
from app.api.staff import router as staff_router
from app.db import init_db

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Campus Transport Experience",
    description="Disruption notifications & ETA transparency for campus transit.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(rider_router)
app.include_router(staff_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health", tags=["system"])
def health_check():
    return {"status": "ok"}


@app.get("/", tags=["system"])
def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Campus Transport Experience API"}


@app.get("/staff", tags=["system"])
def serve_staff():
    staff_file = STATIC_DIR / "staff.html"
    if staff_file.exists():
        return FileResponse(staff_file)
    return {"message": "Campus Transport Staff Portal"}

