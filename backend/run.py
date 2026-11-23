from pathlib import Path

import uvicorn
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.main import app

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
ASSETS = STATIC / "assets"

if ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")

@app.get("/{path:path}", include_in_schema=False)
def spa_fallback(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "Not found")
    # Resolve and confine to STATIC: "..", %2f and symlinks must never escape the build folder.
    root = STATIC.resolve()
    candidate = (STATIC / path).resolve()
    if candidate.is_relative_to(root) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(root / "index.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(__import__("os").getenv("PORT", "8000")))
