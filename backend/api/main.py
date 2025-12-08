"""FastAPI application entry point."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import analyze, nodes, workspaces

app = FastAPI(
    title="ArchAI API",
    description="Architecture analysis for open source repositories",
    version="0.1.0",
)

# CORS: use CORS_ORIGINS env var in production, allow all in development
cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
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
