import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger("main")

from .swarm.agents import AgentSwarm, AGENT_SYSTEM_PROMPTS
from .blackboard.redis_blackboard import RedisBlackboard
from .blackboard.database import Database
from .llm.minimax import get_llm
from .rag.pipeline import RAGPipeline, ingest_knowledge_base, KNOWLEDGE_BASE

blackboard = RedisBlackboard()
database = Database()
rag_pipeline = RAGPipeline()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await blackboard.connect()
        logger.info("Connected to Redis blackboard")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")

    try:
        await database.connect()
        await database.init_schema()
        logger.info("Connected to PostgreSQL and initialized schema")
    except Exception as e:
        logger.error(f"PostgreSQL connection failed: {e}")

    yield

    await blackboard.disconnect()
    await database.disconnect()

app = FastAPI(
    title="Chorus Agent Swarm API",
    lifespan=lifespan
)

class ChatRequest(BaseModel):
    message: str
    project_id: str | None = None


class AgentEvent(BaseModel):
    type: str
    agent_id: str | None = None
    agent_name: str | None = None
    content: str | None = None
    data: dict | None = None
    timestamp: int | None = None


AGENT_IDS = {name: f"agent-{name.lower()}" for name in AGENT_SYSTEM_PROMPTS.keys()}


async def start_swarm_background(project_id: str, user_message: str):
    """Background task to run the swarm without blocking."""
    from .swarm.agents import AgentSwarm

    logger.info(f"[BG] Starting background swarm for project: {project_id}")

    task_definitions = {
        "rootdep": [f"Parse and analyze the project requirement: {user_message}"],
        "backend": [f"Generate Spring Boot backend for: {user_message}"],
        "frontend": [f"Generate Svelte 5 frontend for: {user_message}"],
        "devops": [f"Create Docker configuration for: {user_message}"],
        "packager": [f"Package the project: {user_message}"],
    }

    swarm = AgentSwarm(llm_provider="minimax", blackboard=blackboard)

    try:
        await swarm.initialize(project_id, {"message": user_message})
        await blackboard.set_project_state(project_id, {"status": "running"})
        await swarm.execute_parallel(task_definitions)
        await blackboard.set_project_state(project_id, {"status": "complete"})
        await blackboard.publish_agent_event(project_id, "system", "complete", "Project generation finished")
        logger.info(f"[BG] Swarm completed for project: {project_id}")
    except Exception as e:
        logger.error(f"[BG] Swarm error: {e}")
        await blackboard.set_project_state(project_id, {"status": "error", "error": str(e)})
        await blackboard.publish_agent_event(project_id, "system", "error", str(e))
    finally:
        await swarm.shutdown()


async def event_generator(project_id: str, user_message: str) -> AsyncGenerator[str, None]:
    logger.info(f"[SSE] Starting event generator for project: {project_id}")

    project_state = await blackboard.get_project_state(project_id)
    if project_state and project_state.get("status") == "complete":
        yield json.dumps({
            "type": "RunFinished",
            "content": "Project already completed",
            "timestamp": int(datetime.now().timestamp() * 1000),
            "data": {"status": "success", "project_id": project_id}
        }) + "\n"
        return

    if project_state and project_state.get("status") == "running":
        logger.info(f"[SSE] Project {project_id} already running, just listening")
    else:
        asyncio.create_task(start_swarm_background(project_id, user_message))

    yield json.dumps({
        "type": "RunStarted",
        "content": f"Starting project generation",
        "timestamp": int(datetime.now().timestamp() * 1000),
        "data": {"status": "started", "project_id": project_id}
    }) + "\n"

    try:
        pubsub = blackboard._redis.pubsub()
        channel = f"project:{project_id}:events"
        await pubsub.subscribe(channel)

        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                event_type = data.get("type", "")

                if event_type in ("complete", "done"):
                    agent_name = data.get("agent_name", "")
                    # Only the final system-level complete triggers download + finish
                    if agent_name == "system":
                        yield json.dumps({
                            "type": "download_ready",
                            "agent_id": "system",
                            "agent_name": "system",
                            "content": "Project generation complete!",
                            "timestamp": int(datetime.now().timestamp() * 1000),
                            "data": {
                                "zip_url": f"/api/download/{project_id}/project.zip",
                                "docker_url": f"/api/download/{project_id}/project.zip",
                                "project_name": project_id[:8],
                                "project_id": project_id,
                            }
                        }) + "\n"

                        yield json.dumps({
                            "type": "RunFinished",
                            "content": "Project generation complete!",
                            "timestamp": int(datetime.now().timestamp() * 1000),
                            "data": {"outcome": {"type": "success"}, "project_id": project_id}
                        }) + "\n"
                        break
                    else:
                        # Per-agent complete — forward it so the UI can update each card
                        yield json.dumps({
                            "type": "complete",
                            "agent_id": data.get("agent_id", "system"),
                            "agent_name": agent_name,
                            "content": data.get("content", ""),
                            "timestamp": int(datetime.now().timestamp() * 1000),
                            "data": data.get("data", {})
                        }) + "\n"
                        continue

                if event_type == "error":
                    yield json.dumps({
                        "type": "RunError",
                        "content": data.get("content", "Error occurred"),
                        "timestamp": int(datetime.now().timestamp() * 1000),
                    }) + "\n"
                    break

                # Forward all other event types with their original type intact
                yield json.dumps({
                    "type": event_type,
                    "agent_id": data.get("agent_id", "system"),
                    "agent_name": data.get("agent_name", "system"),
                    "content": data.get("content", ""),
                    "timestamp": int(datetime.now().timestamp() * 1000),
                    "data": data.get("data", {})
                }) + "\n"

    except asyncio.CancelledError:
        logger.info(f"[SSE] SSE connection cancelled")
    except Exception as e:
        logger.error(f"[SSE] Error: {e}")
        yield json.dumps({
            "type": "RunError",
            "content": str(e),
            "timestamp": int(datetime.now().timestamp() * 1000),
        }) + "\n"
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except:
            pass


@app.get("/")
async def root():
    return JSONResponse({"status": "ok", "service": "DeepSeek Agent Swarm - Phase 2"})


@app.post("/api/chat")
async def chat(request: ChatRequest):
    project_id = request.project_id or str(uuid.uuid4())

    return JSONResponse({
        "project_id": project_id,
        "message": f"Starting swarm execution for: {request.message[:50]}...",
    })


@app.get("/api/stream/{project_id}")
async def stream(project_id: str, request: Request):
    user_message = request.query_params.get("message") or "Demo project"

    async def event_generator_wrapper():
        async for event in event_generator(project_id, user_message):
            if await request.is_disconnected():
                break
            yield event

    return EventSourceResponse(event_generator_wrapper())


@app.get("/api/status/{project_id}")
async def get_status(project_id: str):
    state = await blackboard.get_project_state(project_id)
    if not state:
        return JSONResponse({"error": "Project not found"}, status_code=404)
    return JSONResponse({
        "project_id": project_id,
        "status": state.get("status", "unknown"),
        "error": state.get("error"),
    })


@app.get("/api/health")
async def health():
    return JSONResponse({"status": "healthy"})


@app.post("/api/rag/ingest")
async def ingest_rag():
    rag_pipeline.set_database(database)
    await ingest_knowledge_base(rag_pipeline)
    return JSONResponse({"status": "ingested", "categories": list(KNOWLEDGE_BASE.keys())})


@app.get("/api/rag/search")
async def search_rag(query: str, top_k: int = 5):
    rag_pipeline.set_database(database)
    context = await rag_pipeline.get_context_for_query(query, top_k)
    return JSONResponse({"query": query, "context": context})


@app.get("/api/download/{project_id}/project.zip")
async def download_project(project_id: str):
    from pathlib import Path
    zip_path = Path(f"/tmp/deepseek/workspaces/{project_id}/{project_id}.zip")
    if not zip_path.exists():
        return JSONResponse({"error": "ZIP not found"}, status_code=404)

    from fastapi.responses import FileResponse
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"project_{project_id[:8]}.zip"
    )


@app.get("/api/download/{project_id}/url")
async def get_fresh_download_url(project_id: str):
    """Generate a fresh presigned MinIO download URL.
    
    Call this when the original download URL has expired (default 1h).
    """
    from src.storage.minio_client import MinioStorage
    storage = MinioStorage()
    
    try:
        await storage.connect()
        object_name = f"projects/{project_id}/{project_id}.zip"
        
        if not await storage.object_exists(object_name):
            return JSONResponse(
                {"error": "Project not found in storage", "project_id": project_id},
                status_code=404
            )
        
        url = await storage.get_presigned_url(object_name, expires_seconds=3600)
        return JSONResponse({
            "status": "success",
            "project_id": project_id,
            "download_url": url,
            "expires_seconds": 3600,
            "zip_url": f"/api/download/{project_id}/project.zip",
        })
    except Exception as e:
        logger.error(f"[download_url] Failed for {project_id}: {e}")
        return JSONResponse(
            {"error": str(e), "project_id": project_id},
            status_code=500
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
