from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import auth, chat, chef, oss
from app.common.logger import setup_logging
from app.core.settings import settings


setup_logging()

app = FastAPI(
    title=settings.app_name,
    description=settings.app_description,
    version=settings.app_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(chef.router, prefix="/api/v1", tags=["chef"])
app.include_router(oss.router, prefix="/api/v1", tags=["oss"])


@app.get("/health", tags=["system"])
async def health_check():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "features": {
            "llm": settings.llm_ready,
            "search": settings.search_ready,
            "oss": settings.oss_ready,
            "chef_memory": True,
            "meal_plan": True,
            "inventory_tools": True,
            "nutrition_estimate": True,
            "cooking_steps": True,
            "auth": True,
            "household_profile": True,
        },
    }


static_dir = Path(__file__).parent / "static"


@app.get("/{path:path}", include_in_schema=False)
async def serve_frontend(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)

    file_path = static_dir / path
    if file_path.is_file():
        return FileResponse(file_path)

    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)

    return {"message": "Personal Chief API is running", "status": "ok"}


if static_dir.exists():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
