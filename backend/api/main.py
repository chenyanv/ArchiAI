"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import analyze, nodes, workspaces

app = FastAPI(
    title="ArchAI API",
    description="Architecture analysis for open source repositories",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze.router, prefix="/api", tags=["analyze"])
app.include_router(workspaces.router, prefix="/api/workspaces", tags=["workspaces"])
app.include_router(nodes.router, prefix="/api/nodes", tags=["nodes"])


@app.get("/health")
async def health():
    return {"status": "ok"}
