"""Recovery Monitor local control plane (FastAPI). Run from recovery-monitor-backend/:

    uvicorn main:app --host 127.0.0.1 --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from app.auth import seed_demo_users
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.config import AI_ENDPOINTS, CORS_ORIGINS, REPO_ROOT
from app.guards import assert_local
from app.routes import auth, intakes, legacy_api, patients, review, sessions, system, tutorials


@asynccontextmanager
async def lifespan(_app: FastAPI):
    assert_local(AI_ENDPOINTS)  # refuse to run if any AI endpoint is off the device (#21)
    db.conn()
    db.all_("SELECT 1")
    # Sessions interrupted by a restart would otherwise look "processing" forever.
    seed_demo_users()
    with db.tx() as c:
        c.execute("UPDATE sessions SET status = 'failed', stage = 'failed', error = 'Interrupted by a server restart; "
                  "please upload again.' WHERE status IN ('uploaded', 'processing')")
    yield


app = FastAPI(title="Recovery Monitor Local Control Plane", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"])

# Order matters: legacy /api/sessions/{id}/check-in and /decision are more specific than nothing
# in the new routers, and the new routers never define those exact paths.
for r in (system.router, auth.router, auth.onboarding_router, intakes.router, patients.router, sessions.router, review.router, tutorials.router, legacy_api.router):
    app.include_router(r)

# Serve the built UI (npm run build) from the same port, so the demo is one process.
DIST = REPO_ROOT / "recovery-monitor-frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        # Never cache the page itself: after a rebuild it must point at the new asset files.
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
