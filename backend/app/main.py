import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import get_settings
from app.db import init_db

settings = get_settings()


def _bootstrap_demo_db() -> None:
    """First boot on a fresh host: start from the committed demo snapshot."""
    url = settings.resolved_database_url
    if not url.startswith("sqlite:///"):
        return
    db_file = Path(url.removeprefix("sqlite:///"))
    demo = Path(__file__).resolve().parents[1] / "snapshots" / "demo.db"
    if not db_file.exists() and demo.exists():
        db_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(demo, db_file)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _bootstrap_demo_db()
    init_db()
    yield


app = FastAPI(title=f"{settings.app_name} API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

# Serve the built mobile web app from the same origin: one deploy, one URL, no CORS in prod.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        file = (FRONTEND_DIST / path).resolve()
        if path and file.is_file() and FRONTEND_DIST in file.parents:
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
