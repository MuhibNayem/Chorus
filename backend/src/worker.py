import os
import asyncio
import logging
from celery import Celery
from dotenv import load_dotenv

if os.getenv("PYTHON_DOTENV_DISABLED", "").lower() not in {"1", "true", "yes"}:
    load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger("worker")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# Define Celery app
app = Celery(
    "deepseek_swarm",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)

@app.task(name="tasks.run_swarm")
def run_swarm_task(project_id: str, user_message: str, context_mode: str, run_mode: str, ui_mode: str):
    """Celery task wrapper for the agent swarm."""
    from .main import start_swarm_background
    
    logger.info(f"[Worker] Received swarm task for project: {project_id}")
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(start_swarm_background(
        project_id=project_id,
        user_message=user_message,
        context_mode=context_mode,
        run_mode=run_mode,
        ui_mode=ui_mode
    ))

@app.task(name="tasks.run_plan")
def run_plan_task(project_id: str, user_message: str, context_mode: str):
    """Celery task wrapper for the planning mode (RootDep only)."""
    from .main import start_plan_swarm_background
    
    logger.info(f"[Worker] Received plan task for project: {project_id}")
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(start_plan_swarm_background(
        project_id=project_id,
        user_message=user_message,
        context_mode=context_mode
    ))
