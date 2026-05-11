import asyncio
import json
import logging
import os
import shutil
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

if os.getenv("PYTHON_DOTENV_DISABLED", "").lower() not in {"1", "true", "yes"}:
    load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger("main")

from .swarm.agents import AgentSwarm, AGENT_SYSTEM_PROMPTS
from .blackboard.event_log import get_project_events_since
from .blackboard.redis_blackboard import RedisBlackboard
from .blackboard.database import Database
from .rag.pipeline import RAGPipeline, ingest_knowledge_base, KNOWLEDGE_BASE
from .swarm.context_engineering import context_summary_to_json
from .storage.minio_client import MinioStorage

blackboard = RedisBlackboard()
database = Database()
rag_pipeline = RAGPipeline()
storage = MinioStorage()


def _sse_message(event: dict) -> dict:
    payload = json.dumps(event, default=str)
    message = {"data": payload}
    event_id = event.get("event_id")
    if event_id is not None:
        message["id"] = str(event_id)
    return message


def _parse_last_event_id(raw_value: str | None) -> int | None:
    if not raw_value:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


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

    # --- Startup cleanup: clear stale swarm locks and reset orphaned running states ---
    try:
        if getattr(blackboard, "_redis", None):
            async for key in blackboard._redis.scan_iter(match="project:*:swarm_lock"):
                await blackboard._redis.delete(key)
                logger.info(f"[STARTUP] Cleared stale swarm lock: {key}")

            async for key in blackboard._redis.scan_iter(match="project:*:state"):
                state_raw = await blackboard._redis.get(key)
                if state_raw:
                    try:
                        state = json.loads(state_raw)
                        if state.get("status") in ("running", "planning"):
                            state["status"] = "error"
                            state["error"] = "Backend restarted while swarm was running"
                            await blackboard._redis.set(key, json.dumps(state))
                            pid = key.split(":")[1]
                            logger.warning(f"[STARTUP] Reset orphaned project state to error: {pid}")
                            try:
                                await database.update_project_status(pid, "error")
                            except Exception:
                                pass
                    except Exception:
                        pass
    except Exception as e:
        logger.warning(f"[STARTUP] Failed to run stale-lock cleanup: {e}")
    # --- End startup cleanup ---

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
    context_mode: str = "auto"
    mode: str = "auto"
    ui_mode: str = "build"


class AgentEvent(BaseModel):
    type: str
    agent_id: str | None = None
    agent_name: str | None = None
    content: str | None = None
    data: dict | None = None
    timestamp: int | None = None


AGENT_IDS = {name: f"agent-{name.lower()}" for name in AGENT_SYSTEM_PROMPTS.keys()}
WORKSPACE_BASE = Path(os.getenv("WORKSPACE_BASE", "/tmp/deepseek/workspaces"))
CHECKPOINT_BASE = Path(os.getenv("CHECKPOINT_BASE", "/tmp/deepseek/checkpoints"))

VAGUE_PATTERNS = [
    r"^(make|build|create|do|fix|update|improve|change|modify)\s+(it|this|that|them|something|anything|everything|nothing)$",
    r"^(make|build|create)\s+(it|this|that)\s+(better|nicer|nice|better|larger|smaller|faster|slower)$",
    r"^(fix|repair|repair)\s+(it|this|that|them)$",
    r"^(improve|enhance|optimize)\s+(it|this|that|the\s+code|the\s+project)$",
    r"^(add|solve)\s+(some|any)\s+features?$",
    r"^(just|simply)\s+.+$",
    r"^(try|see|look|check|review)\s+(if|what|how)\s+.+\s+(works?|doesn?ts?|is|are)$",
    r"^(help|scaffold|bootstrap)$",
    r"^(whatever|anything|something|nothing)$",
    r"^(yes|ok|okay|sure|yeah|yep|god|yes please)$",
    r"^(good|fine|great|cool|nice)$",
    r"^lgtm$",
    r"^looks?\s+good$",
    r"^[.,!?;:\s]+$",
    r"^\?$",
    r"^help$",
    r"^(make|build|create)\s+(me)?\s*a\s+project$",
    r"^test$",
    r"^demo$",
    r"^hello|hi|hey$",
]

VAGUE_KEYWORDS = [
    "better", "nicer", "faster", "smaller", "bigger", "larger",
    "prettier", "cleaner", "modern", "improved", "advanced",
    "something", "anything", "everything", "nothing",
    "stuff", "things", "it", "this", "that", "them",
]

MIN_MESSAGE_LENGTH = 10
MIN_ACTION_WORDS = 2

def _is_vague_request(message: str) -> tuple[bool, str]:
    """Detect vague requests that need clarification.
    
    Returns (is_vague, clarification_prompt)
    """
    import re
    
    msg = message.strip()
    msg_lower = msg.lower()
    
    if len(msg) < MIN_MESSAGE_LENGTH:
        return True, "Please describe what you want to build in more detail. For example: 'Build a task manager with Spring Boot backend and Svelte frontend'."
    
    for pattern in VAGUE_PATTERNS:
        if re.match(pattern, msg_lower, re.IGNORECASE):
            return True, f"Your request is too vague. Instead of '{msg}', try something like:\n- 'Add user authentication with JWT tokens'\n- 'Create a dashboard showing analytics charts'\n- 'Build a REST API for managing tasks'"
    
    action_words = [
        "add", "create", "build", "implement", "make", "design", "develop",
        "fix", "update", "modify", "change", "improve", "enhance", "optimize",
        "remove", "delete", "integrate", "connect", "setup", "configure",
        "add", "create", "generate", "build"
    ]
    words = msg_lower.split()
    action_word_count = sum(1 for w in words if w in action_words)
    
    vague_word_count = sum(1 for w in words if w in VAGUE_KEYWORDS)
    
    if vague_word_count >= 2 and action_word_count < MIN_ACTION_WORDS:
        return True, f"I need more specifics. '{msg}' is too generic. What exactly should be added/changed/created? Please mention the specific feature or functionality you want."
    
    if all(w in ["it", "this", "that", "them", "something", "anything", "everything", "nothing"] for w in words if len(w) > 2):
        return True, "Please describe what you want to build in detail. For example: 'Build a blog with user authentication and markdown support'."
    
    return False, ""


def _normalize_context_mode(context_mode: str) -> str:
    return context_mode if context_mode in ("auto", "lean", "full") else "auto"


def _normalize_run_mode(run_mode: str, project_id: str | None = None) -> str:
    if run_mode in ("generate", "modify", "approved"):
        return run_mode
    return "modify" if project_id else "generate"


def _extract_project_name(message: str, max_length: int = 32) -> str:
    """Extract a clean project name from the user's message description."""
    import re
    cleaned = message.strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    words = cleaned.split()
    name_parts = []
    for word in words:
        clean_word = re.sub(r'^[^a-zA-Z0-9]+', '', word)
        clean_word = re.sub(r'[^a-zA-Z0-9]+$', '', clean_word)
        if clean_word:
            name_parts.append(clean_word.lower())
    if not name_parts:
        return "untitled"
    result = '-'.join(name_parts[:8])
    if len(result) > max_length:
        result = result[:max_length].rstrip('-')
    return result or "untitled"


async def _resolve_project_message(project_id: str, fallback: str = "") -> str:
    if fallback.strip():
        return fallback

    project_state = await blackboard.get_project_state(project_id)
    if isinstance(project_state, dict):
        spec = project_state.get("spec")
        if isinstance(spec, dict):
            message = str(spec.get("message", "")).strip()
            if message:
                return message

    if getattr(database, "_pool", None):
        project = await database.get_project(project_id)
        if project and project.get("spec"):
            spec = project.get("spec")
            if isinstance(spec, str):
                try:
                    spec = json.loads(spec)
                except json.JSONDecodeError:
                    spec = {}
            if isinstance(spec, dict):
                message = str(spec.get("message", "")).strip()
                if message:
                    return message

    return fallback


def _row_to_json(row: dict) -> dict:
    result = dict(row)
    for key in ("metadata", "spec"):
        value = result.get(key)
        if isinstance(value, str):
            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    for key in ("created_at", "updated_at"):
        value = result.get(key)
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    from uuid import UUID
    for key in result:
        val = result[key]
        if isinstance(val, UUID):
            result[key] = str(val)
        elif hasattr(val, '__iter__') and not isinstance(val, (str, list, dict)):
            try:
                result[key] = str(val)
            except:
                pass
    return result


def _coerce_project_spec(project: dict | None) -> dict:
    if not project:
        return {}

    spec = project.get("spec", {})
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except json.JSONDecodeError:
            spec = {}

    return spec if isinstance(spec, dict) else {}


def _has_active_celery_worker() -> bool:
    try:
        from .worker import app as celery_app

        inspector = celery_app.control.inspect(timeout=0.5)
        active = inspector.ping()
        return bool(active)
    except Exception as exc:
        logger.warning(f"[celery] Worker health check failed: {exc}")
        return False


def _create_workspace_checkpoint(project_id: str, checkpoint_id: str) -> tuple[str, int, int]:
    workspace = WORKSPACE_BASE / project_id
    checkpoint_dir = CHECKPOINT_BASE / project_id
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = checkpoint_dir / f"{checkpoint_id}.zip"

    # Pre-flight disk space check — avoid writing a massive zip into a full tmpfs
    try:
        stat = os.statvfs(checkpoint_dir)
        avail_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
        if avail_mb < 100:
            logger.warning(
                "[checkpoint] Low disk space on checkpoint dir: %.1f MB available. "
                "Skipping checkpoint creation to avoid 'No space left on device'.",
                avail_mb,
            )
            return str(checkpoint_path), 0, 0
    except Exception:
        pass

    # Exclude directories that bloat checkpoints without adding value:
    # - .git          : version history, often 100x larger than source code
    # - node_modules  : dependency tree (not in workspace for this project, but
    #                   defensive for future stacks)
    # - .venv, venv   : Python virtual environments
    # - __pycache__   : compiled Python bytecode
    EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache"}
    file_count = 0
    with zipfile.ZipFile(checkpoint_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if workspace.exists():
            for file_path in workspace.rglob("*"):
                if not file_path.is_file():
                    continue
                # Skip zip files (packager output, previous checkpoints)
                if file_path.name.endswith(".zip"):
                    continue
                # Skip files inside excluded directories
                try:
                    rel_parts = file_path.relative_to(workspace).parts
                    if any(part in EXCLUDED_DIRS for part in rel_parts):
                        continue
                except ValueError:
                    continue
                zf.write(file_path, file_path.relative_to(workspace))
                file_count += 1

    size_bytes = checkpoint_path.stat().st_size if checkpoint_path.exists() else 0
    return str(checkpoint_path), file_count, size_bytes


def _safe_extract_checkpoint(snapshot_path: Path, workspace: Path):
    workspace_resolved = workspace.resolve(strict=False)
    with zipfile.ZipFile(snapshot_path, "r") as zf:
        for member in zf.infolist():
            target_path = (workspace / member.filename).resolve(strict=False)
            try:
                target_path.relative_to(workspace_resolved)
            except ValueError:
                raise PermissionError(f"Checkpoint entry escapes workspace: {member.filename}")
        zf.extractall(workspace)


async def create_project_checkpoint(
    project_id: str,
    label: str,
    run_mode: str,
    trigger_message: str,
    metadata: dict | None = None,
) -> str | None:
    if not getattr(database, "_pool", None):
        return None

    checkpoint_id = str(uuid.uuid4())
    try:
        local_snapshot_path = None

        # 1. Capture AI conversation context before creating checkpoint
        ai_context = await _capture_ai_context(project_id)

        # 2. Create local ZIP
        snapshot_path_str, file_count, size_bytes = _create_workspace_checkpoint(project_id, checkpoint_id)
        snapshot_path = Path(snapshot_path_str)
        local_snapshot_path = snapshot_path_str

        # 3. Upload to MinIO
        object_name = f"checkpoints/{project_id}/{checkpoint_id}.zip"
        await storage.upload_file(object_name, snapshot_path)
        logger.info(f"[checkpoint] Uploaded {checkpoint_id} to MinIO: {object_name}")

        # 4. Save to Database (using MinIO object name as snapshot_path for portability)
        checkpoint_metadata = {
            **(metadata or {}),
            "file_count": file_count,
            "size_bytes": size_bytes,
            "local_path": snapshot_path_str,
            "ai_context": ai_context,
        }
        await database.save_project_checkpoint(
            checkpoint_id=checkpoint_id,
            project_id=project_id,
            label=label,
            run_mode=run_mode,
            trigger_message=trigger_message,
            snapshot_path=object_name,
            metadata=checkpoint_metadata,
        )

        # 5. Clean up local checkpoint files to prevent tmpfs bloat.
        #    MinIO is the source of truth; local copies are ephemeral staging.
        _cleanup_old_local_checkpoints(project_id, keep_recent=3)

        return checkpoint_id
    except Exception as e:
        logger.warning(f"[checkpoint] Failed to create checkpoint for {project_id}: {e}")
        return None


def _cleanup_old_local_checkpoints(project_id: str, keep_recent: int = 3) -> None:
    """Delete local checkpoint ZIPs for a project, keeping only the N most recent.

    Local checkpoints are ephemeral staging copies. MinIO is the durable
    source of truth. This prevents the 256 MB tmpfs from filling up.
    """
    checkpoint_dir = CHECKPOINT_BASE / project_id
    if not checkpoint_dir.exists():
        return

    try:
        zips = sorted(
            (p for p in checkpoint_dir.glob("*.zip") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old_zip in zips[keep_recent:]:
            try:
                old_zip.unlink()
                logger.info("[checkpoint] Deleted old local checkpoint: %s", old_zip.name)
            except Exception:
                pass
    except Exception:
        pass


async def _capture_ai_context(project_id: str) -> dict:
    """Capture AI conversation context from context_summaries table."""
    context_data = {
        "agent_summaries": [],
        "conversation_history": [],
        "facts": {},
        "preserved_files": [],
    }

    if not getattr(database, "_pool", None):
        return context_data

    try:
        summaries = await database.list_context_summaries(project_id, limit=25)
        if summaries:
            for row in summaries:
                context_data["agent_summaries"].append({
                    "agent_name": row.get("agent_name"),
                    "summary": row.get("summary", ""),
                    "facts": row.get("facts", {}),
                    "preserved_files": row.get("preserved_files", []),
                    "source_event_count": row.get("source_event_count", 0),
                    "estimated_tokens": row.get("estimated_tokens", 0),
                    "created_at": str(row.get("created_at", "")),
                })

        messages = await database.get_chat_messages(project_id, limit=50)
        if messages:
            for msg in reversed(messages):
                context_data["conversation_history"].append({
                    "role": msg.get("role"),
                    "content": msg.get("content", "")[:500],
                    "created_at": str(msg.get("created_at", "")),
                })
    except Exception as e:
        logger.warning(f"[checkpoint] Failed to capture AI context: {e}")

    return context_data


async def ensure_workspace_is_warm(project_id: str):
    """Ensures the project workspace exists in /tmp, restoring from MinIO if necessary."""
    workspace = WORKSPACE_BASE / project_id
    if workspace.exists() and any(workspace.iterdir()):
        logger.info(f"[warmup] Workspace for {project_id} is already warm")
        return

    logger.info(f"[warmup] Workspace for {project_id} is cold or missing. Attempting restoration...")
    
    # 1. Find latest checkpoint
    checkpoints = await database.list_project_checkpoints(project_id, limit=1)
    if not checkpoints:
        logger.info(f"[warmup] No checkpoints found for {project_id}. Starting fresh.")
        workspace.mkdir(parents=True, exist_ok=True)
        return

    checkpoint = checkpoints[0]
    checkpoint_id = checkpoint["id"]
    object_name = checkpoint["snapshot_path"] # This is the MinIO object name
    
    # 2. Download from MinIO
    local_zip = CHECKPOINT_BASE / project_id / f"{checkpoint_id}_restore.zip"
    local_zip.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"[warmup] Downloading checkpoint {checkpoint_id} from MinIO...")
    await storage.download_file(object_name, local_zip)
    
    # 3. Extract to workspace
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"[warmup] Extracting {checkpoint_id} to {workspace}...")
    _safe_extract_checkpoint(local_zip, workspace)
    
    # 4. Cleanup temp zip
    if local_zip.exists():
        local_zip.unlink()
    
    logger.info(f"[warmup] Workspace for {project_id} restored successfully from checkpoint {checkpoint_id}")


async def start_swarm_background(
    project_id: str,
    user_message: str,
    context_mode: str = "auto",
    run_mode: str = "generate",
    ui_mode: str = "build",
):
    """Background task to run the swarm without blocking."""
    from .swarm.agents import AgentSwarm
    import hashlib
    import redis.asyncio as _redis

    is_modification = run_mode == "modify"

    # Ensure connections are active (especially for Celery workers)
    if not getattr(blackboard, "_redis", None):
        await blackboard.connect()
    if not getattr(database, "_pool", None):
        await database.connect()
        await database.init_schema()

    # --- Distributed lock: prevent concurrent swarms for the same project ---
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    lock_key = f"project:{project_id}:swarm_lock"
    lock_acquired = False
    r: _redis.Redis | None = None
    try:
        r = _redis.from_url(redis_url, decode_responses=True)
        lock_acquired = await r.set(lock_key, "1", nx=True)
        if not lock_acquired:
            logger.warning(f"[BG] Swarm already running for project {project_id} — skipping duplicate")
            await blackboard.publish_agent_event(
                project_id, "system", "warning",
                f"Swarm execution skipped: another instance is already running for this project.",
                {"reason": "duplicate_swarm_prevented"},
            )
            return
    except Exception as lock_err:
        logger.warning(f"[BG] Lock acquisition failed for {project_id}: {lock_err} — proceeding without lock")
    finally:
        if r is not None:
            await r.aclose()

    logger.info(f"[BG] Starting {run_mode} swarm for project: {project_id}")

    try:
        await ensure_workspace_is_warm(project_id)
    except Exception as e:
        logger.error(f"[BG] Failed to warm up workspace: {e}")

    spec_hash_before = None
    spec_path = WORKSPACE_BASE / project_id / "SPEC.md"
    if spec_path.exists():
        spec_hash_before = hashlib.sha256(spec_path.read_bytes()).hexdigest()[:16]
        logger.info(f"[BG] SPEC.md hash before: {spec_hash_before}")

    workspace = WORKSPACE_BASE / project_id
    
    if run_mode == "modify":
        base_tasks = f"Update the existing project specification for this modification: {user_message}"
        task_definitions = {
            "rootdep": [base_tasks],
            "backend": [f"Modify the existing backend for: {user_message}"],
            "frontend": [f"Modify the existing frontend for: {user_message}"],
            "devops": [f"Update deployment configuration only if needed for: {user_message}"],
            "packager": [f"Verify, repackage, and upload the modified project: {user_message}"],
        }
    elif run_mode == "approved":
        task_definitions = {
            "backend": [f"Implement backend from the approved SPEC.md for: {user_message}"],
            "frontend": [f"Implement frontend from the approved SPEC.md for: {user_message}"],
            "devops": [f"Create deployment configuration from the approved SPEC.md and generated manifests for: {user_message}"],
            "packager": [f"Verify, package, and upload the approved project build: {user_message}"],
        }
    else:
        base_tasks = f"Parse and analyze the project requirement: {user_message}"
        task_definitions = {
            "rootdep": [base_tasks],
            "backend": [f"Generate backend for: {user_message}"],
            "frontend": [f"Generate frontend for: {user_message}"],
            "devops": [f"Create Docker configuration for: {user_message}"],
            "packager": [f"Package the project: {user_message}"],
        }

    swarm = AgentSwarm(
        llm_provider="minimax",
        blackboard=blackboard,
        database=database,
        rag_pipeline=rag_pipeline,
        context_mode=context_mode,
    )

    try:
        await database.ensure_project(
            project_id,
            name=_extract_project_name(user_message),
            spec={"message": user_message, "run_mode": run_mode, "context_mode": context_mode},
            status="running",
        )
        if is_modification:
            await create_project_checkpoint(
                project_id,
                "Before modification",
                run_mode,
                user_message,
                {"phase": "before"},
            )

        await swarm.initialize(
            project_id,
            {
                "status": "running",
                "context_mode": context_mode,
                "run_mode": run_mode,
                "message": user_message,
            },
        )
        await database.update_project_status(project_id, "running")
        result = await swarm.execute_parallel(task_definitions)
        if isinstance(result, dict) and result.get("status") == "error":
            raise RuntimeError(result.get("error", "Swarm execution failed"))
        if isinstance(result, dict) and result.get("status") == "stopped":
            await database.update_project_status(project_id, "stopped")
            logger.info(f"[BG] Swarm stopped by user for project {project_id}")
            return
        await database.update_project_status(project_id, "complete")
        checkpoint_id = await create_project_checkpoint(
            project_id,
            "Modified project" if is_modification else "Generated project",
            run_mode,
            user_message,
            {"phase": "after", "result": result},
        )
        
        spec_hash_after = None
        if spec_path.exists():
            spec_hash_after = hashlib.sha256(spec_path.read_bytes()).hexdigest()[:16]
            logger.info(f"[BG] SPEC.md hash after: {spec_hash_after}")
        
        spec_changed = spec_hash_before and spec_hash_after and spec_hash_before != spec_hash_after
        if spec_changed:
            logger.info(f"[BG] SPEC.md changed during execution: {spec_hash_before} -> {spec_hash_after}")
            await database.save_chat_message(
                message_id=str(uuid.uuid4()),
                project_id=project_id,
                role="system",
                content=f"SPEC.md was modified during execution (hash: {spec_hash_before} -> {spec_hash_after})",
                metadata={"spec_hash_before": spec_hash_before, "spec_hash_after": spec_hash_after, "type": "spec_change_detected", "ui_mode": ui_mode},
            )

        await database.save_chat_message(
            message_id=str(uuid.uuid4()),
            project_id=project_id,
            role="assistant",
            content="Project modification finished" if is_modification else "Project generation finished",
            metadata={"run_mode": run_mode, "ui_mode": ui_mode, "checkpoint_id": checkpoint_id},
        )
        await blackboard.set_project_state(
            project_id,
            {
                "status": "complete",
                "context_mode": context_mode,
                "run_mode": run_mode,
                "checkpoint_id": checkpoint_id,
            },
        )
        await database.update_project_status(project_id, "complete")
        try:
            await database.create_project(
                project_id,
                _extract_project_name(user_message),
                {
                    "status": "complete",
                    "message": user_message,
                    "context_mode": context_mode,
                    "run_mode": run_mode,
                    "checkpoint_id": checkpoint_id,
                },
            )
        except Exception as sync_err:
            logger.warning(f"[BG] DB sync failed for {project_id}: {sync_err}")
        await blackboard.publish_agent_event(
            project_id,
            "system",
            "complete",
            "Project modification finished" if is_modification else "Project generation finished",
            {"run_mode": run_mode, "checkpoint_id": checkpoint_id},
        )
        logger.info(f"[BG] Swarm completed for project: {project_id}")
    except Exception as e:
        logger.error(f"[BG] Swarm error: {e}")
        try:
            await database.update_project_status(project_id, "error")
            await database.save_chat_message(
                message_id=str(uuid.uuid4()),
                project_id=project_id,
                role="assistant",
                content=str(e),
                metadata={"run_mode": run_mode, "ui_mode": ui_mode, "status": "error"},
            )
        except Exception as db_error:
            logger.warning(f"[BG] Failed to persist error state: {db_error}")
        await blackboard.set_project_state(project_id, {"status": "error", "error": str(e)})
        await blackboard.publish_agent_event(project_id, "system", "error", str(e))
    finally:
        await swarm.shutdown()
        # --- Release distributed lock ---
        if lock_acquired:
            try:
                r = _redis.from_url(redis_url, decode_responses=True)
                await r.delete(lock_key)
                await r.aclose()
                logger.info(f"[BG] Released swarm lock for project {project_id}")
            except Exception as unlock_err:
                logger.warning(f"[BG] Failed to release swarm lock for {project_id}: {unlock_err}")


async def start_plan_swarm_background(
    project_id: str,
    user_message: str,
    context_mode: str = "auto",
):
    """Background task to run ONLY RootDep for plan mode - does NOT run full swarm."""
    from .swarm.agents import AgentSwarm
    import redis.asyncio as _redis

    # Ensure connections are active (especially for Celery workers)
    if not getattr(blackboard, "_redis", None):
        await blackboard.connect()
    if not getattr(database, "_pool", None):
        await database.connect()
        await database.init_schema()

    # --- Distributed lock: prevent concurrent plan runs for the same project ---
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    lock_key = f"project:{project_id}:swarm_lock"
    lock_acquired = False
    r: _redis.Redis | None = None
    try:
        r = _redis.from_url(redis_url, decode_responses=True)
        lock_acquired = await r.set(lock_key, "1", nx=True)
        if not lock_acquired:
            logger.warning(f"[BG-PLAN] Plan already running for project {project_id} — skipping duplicate")
            await blackboard.publish_agent_event(
                project_id, "system", "warning",
                f"Plan execution skipped: another instance is already running for this project.",
                {"reason": "duplicate_plan_prevented"},
            )
            return
    except Exception as lock_err:
        logger.warning(f"[BG-PLAN] Lock acquisition failed for {project_id}: {lock_err} — proceeding without lock")
    finally:
        if r is not None:
            await r.aclose()

    logger.info(f"[BG-PLAN] Starting plan mode for project: {project_id}")

    try:
        await ensure_workspace_is_warm(project_id)
    except Exception as e:
        logger.error(f"[BG-PLAN] Failed to warm up workspace: {e}")

    workspace = WORKSPACE_BASE / project_id
    spec_path = workspace / "SPEC.md"

    task_definitions = {
        "rootdep": [f"Create a detailed SPEC.md for: {user_message}"],
    }

    swarm = AgentSwarm(
        llm_provider="minimax",
        blackboard=blackboard,
        database=database,
        rag_pipeline=rag_pipeline,
        context_mode=context_mode,
    )

    try:
        await database.ensure_project(
            project_id,
            name=_extract_project_name(user_message),
            spec={"message": user_message, "run_mode": "plan", "context_mode": context_mode},
            status="planning",
        )

        await swarm.initialize(
            project_id,
            {
                "status": "planning",
                "context_mode": context_mode,
                "run_mode": "plan",
                "message": user_message,
            },
        )
        await database.update_project_status(project_id, "planning")

        result = await swarm.execute_parallel(task_definitions)
        if isinstance(result, dict) and result.get("status") == "error":
            raise RuntimeError(result.get("error", "Plan generation failed"))

        spec_content = ""
        if spec_path.exists():
            spec_content = spec_path.read_text()

        current_project = await database.get_project(project_id)
        current_spec = _coerce_project_spec(current_project)
        current_spec.update(
            {
                "message": user_message,
                "run_mode": "plan",
                "context_mode": context_mode,
                "spec_content": spec_content,
            }
        )
        await database.update_project_spec(project_id, current_spec, status="plan_ready")
        await database.update_project_status(project_id, "plan_ready")

        await blackboard.publish_agent_event(
            project_id,
            "rootdep",
            "plan_ready",
            "Plan generation complete. Review and approve SPEC.md to continue.",
            {
                "spec_content": spec_content,
                "spec_length": len(spec_content),
                "run_mode": "plan",
            },
        )

        await blackboard.set_project_state(
            project_id,
            {
                "status": "plan_ready",
                "context_mode": context_mode,
                "run_mode": "plan",
                "spec_length": len(spec_content),
                "spec_content": spec_content,
            },
        )

        await database.save_chat_message(
            message_id=str(uuid.uuid4()),
            project_id=project_id,
            role="assistant",
            content="SPEC.md generated. Review and approve the plan to begin implementation.",
            metadata={"ui_mode": "plan", "type": "plan_ready"},
        )

        await blackboard.publish_agent_event(
            project_id,
            "system",
            "complete",
            "Plan generation finished. You can now review and approve the SPEC.md.",
            {"status": "plan_ready"}
        )

        logger.info(f"[BG-PLAN] Plan completed for project: {project_id}")
    except Exception as e:
        logger.error(f"[BG-PLAN] Plan swarm error: {e}")
        try:
            await database.update_project_status(project_id, "error")
        except Exception:
            pass
        await blackboard.set_project_state(project_id, {"status": "error", "error": str(e)})
        await blackboard.publish_agent_event(project_id, "system", "error", str(e))
    finally:
        await swarm.shutdown()
        # --- Release distributed lock ---
        if lock_acquired:
            try:
                r = _redis.from_url(redis_url, decode_responses=True)
                await r.delete(lock_key)
                await r.aclose()
                logger.info(f"[BG-PLAN] Released swarm lock for project {project_id}")
            except Exception as unlock_err:
                logger.warning(f"[BG-PLAN] Failed to release swarm lock for {project_id}: {unlock_err}")


async def event_generator(
    project_id: str,
    user_message: str,
    context_mode: str = "auto",
    run_mode: str = "generate",
    ui_mode: str = "build",
    since_event_id: int | None = None,
) -> AsyncGenerator[str, None]:
    logger.info(f"[SSE] Starting event generator for project: {project_id}")
    context_mode = _normalize_context_mode(context_mode)
    run_mode = _normalize_run_mode(run_mode, project_id)
    user_message = await _resolve_project_message(project_id, user_message)

    project_state = await blackboard.get_project_state(project_id)
    if project_state and project_state.get("status") == "complete" and run_mode != "modify":
        yield _sse_message({
            "type": "RunFinished",
            "content": "Project already completed",
            "timestamp": int(datetime.now().timestamp() * 1000),
            "data": {"status": "success", "project_id": project_id}
        })
        return

    if project_state and project_state.get("status") == "running":
        logger.info(f"[SSE] Project {project_id} already running, just listening")
        context_mode = project_state.get("context_mode", context_mode)
        run_mode = project_state.get("run_mode", run_mode)
    elif ui_mode == "plan":
        logger.info(f"[SSE] Plan mode - plan already started by /api/plan, just listening")
    else:
        if _has_active_celery_worker():
            from .worker import run_swarm_task

            logger.info(f"[SSE] Dispatching build task to Celery worker for project: {project_id}")
            run_swarm_task.delay(project_id, user_message, context_mode, run_mode, ui_mode)
        else:
            logger.warning(
                f"[SSE] No Celery worker detected for project {project_id}. "
                "Starting swarm in-process."
            )
            asyncio.create_task(
                start_swarm_background(
                    project_id=project_id,
                    user_message=user_message,
                    context_mode=context_mode,
                    run_mode=run_mode,
                    ui_mode=ui_mode,
                )
            )

    try:
        pubsub = blackboard._redis.pubsub()
        channel = f"project:{project_id}:events"
        await pubsub.subscribe(channel)

        replayed_running_events = False
        if since_event_id is not None:
            replayed_events = await get_project_events_since(
                blackboard._redis,
                project_id,
                after_event_id=since_event_id,
            )
            for replay_event in replayed_events:
                replayed_running_events = True
                yield _sse_message(replay_event)

        if not replayed_running_events and not (project_state and project_state.get("status") == "running") and ui_mode != "plan":
            yield _sse_message({
                "type": "RunStarted",
                "content": "Starting project modification" if run_mode == "modify" else "Starting project generation",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "data": {
                    "status": "started",
                    "project_id": project_id,
                    "context_mode": context_mode,
                    "run_mode": run_mode,
                }
            })

        async for message in pubsub.listen():
            if message["type"] == "message":
                data = json.loads(message["data"])
                event_type = data.get("type", "")
                agent_name = data.get("agent_name", "system")
                content = data.get("content", "")
                event_data = data.get("data", {})
                logger.info(
                    f"[SSE] Relaying event for {project_id}: "
                    f"type={event_type} agent={agent_name}"
                )

                if event_type in ("complete", "done"):
                    agent_name = data.get("agent_name", "")
                    if agent_name == "system":
                        yield _sse_message({
                            "type": "download_ready",
                            "agent_id": "system",
                            "agent_name": "system",
                            "content": "Project modification complete!" if run_mode == "modify" else "Project generation complete!",
                            "timestamp": int(datetime.now().timestamp() * 1000),
                            "data": {
                                "zip_url": f"/api/download/{project_id}/project.zip",
                                "download_url": f"/api/download/{project_id}/url",
                                "project_name": project_id[:8],
                                "project_id": project_id,
                            }
                        })

                        yield _sse_message({
                            "type": "RunFinished",
                            "content": "Project modification complete!" if run_mode == "modify" else "Project generation complete!",
                            "timestamp": int(datetime.now().timestamp() * 1000),
                            "data": {
                                "outcome": {"type": "success"},
                                "project_id": project_id,
                                "run_mode": run_mode,
                                "checkpoint_id": event_data.get("checkpoint_id"),
                            }
                        })
                        break
                    else:
                        yield _sse_message({
                            "type": "complete",
                            "agent_id": data.get("agent_id", "system"),
                            "agent_name": agent_name,
                            "content": content,
                            "timestamp": int(datetime.now().timestamp() * 1000),
                            "data": event_data
                        })
                        continue

                if event_type == "error":
                    yield _sse_message({
                        "type": "RunError",
                        "content": data.get("content", "Error occurred"),
                        "timestamp": int(datetime.now().timestamp() * 1000),
                    })
                    break

                if event_type == "plan_ready":
                    spec_content = event_data.get("spec_content", "")
                    logger.info(
                        f"[SSE] PlanReady for {project_id}: spec_length={len(spec_content)}"
                    )
                    yield _sse_message({
                        "type": "PlanReady",
                        "content": "SPEC.md generated. Review and approve to begin implementation.",
                        "timestamp": int(datetime.now().timestamp() * 1000),
                        "data": {
                            "spec_content": spec_content,
                            "spec_length": len(spec_content),
                            "project_id": project_id,
                            "project_status": "plan_ready",
                        }
                    })
                    continue

                if event_type == "text" and content:
                    try:
                        await database.save_chat_message(
                            message_id=str(uuid.uuid4()),
                            project_id=project_id,
                            role="assistant",
                            content=f"[{agent_name}]: {content}" if agent_name != "system" else content,
                            metadata={
                                "event_type": event_type,
                                "agent_name": agent_name,
                                "run_mode": run_mode,
                                "ui_mode": ui_mode,
                                "checkpoint_id": event_data.get("checkpoint_id"),
                            },
                        )
                    except Exception as save_err:
                        logger.warning(f"[SSE] Failed to persist message: {save_err}")

                yield _sse_message({
                    "type": event_type,
                    "agent_id": data.get("agent_id", "system"),
                    "agent_name": agent_name,
                    "content": content,
                    "timestamp": int(datetime.now().timestamp() * 1000),
                    "data": event_data
                })

    except asyncio.CancelledError:
        logger.info(f"[SSE] SSE connection cancelled")
    except Exception as e:
        logger.error(f"[SSE] Error: {e}")
        yield _sse_message({
            "type": "RunError",
            "content": str(e),
            "timestamp": int(datetime.now().timestamp() * 1000),
        })
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
    is_vague, clarification = _is_vague_request(request.message)
    if is_vague:
        return JSONResponse({
            "error": "vague_request",
            "message": "Please provide more specific project details.",
            "clarification": clarification,
        }, status_code=422)

    project_id = request.project_id or str(uuid.uuid4())
    context_mode = _normalize_context_mode(request.context_mode)
    run_mode = _normalize_run_mode(request.mode, request.project_id)

    try:
        project_name = _extract_project_name(request.message)
        await database.ensure_project(
            project_id,
            name=project_name,
            spec={
                "message": request.message,
                "run_mode": run_mode,
                "context_mode": context_mode,
                "ui_mode": request.ui_mode,
            },
            status="pending",
        )
        await database.save_chat_message(
            message_id=str(uuid.uuid4()),
            project_id=project_id,
            role="user",
            content=request.message,
            metadata={"run_mode": run_mode, "context_mode": context_mode, "ui_mode": request.ui_mode},
        )
    except Exception as e:
        logger.warning(f"[chat] Failed to persist chat request for {project_id}: {e}")

    return JSONResponse({
        "project_id": project_id,
        "context_mode": context_mode,
        "mode": run_mode,
        "message": (
            f"Starting modification for: {request.message[:50]}..."
            if run_mode == "modify"
            else f"Starting swarm execution for: {request.message[:50]}..."
        ),
    })


class PlanRequest(BaseModel):
    message: str
    project_id: str | None = None
    mode: str = "auto"


@app.post("/api/plan")
async def create_plan(request: PlanRequest):
    """Generate an implementation plan via RootDep AI agent (async).

    Plan mode:
    1. Starts RootDep in background to create SPEC.md
    2. Client listens to SSE stream for plan progress
    3. When plan_ready event received, SPEC.md is shown to user
    4. User can edit SPEC.md or click Approve
    5. On Approve → /api/chat runs full swarm
    """
    is_vague, clarification = _is_vague_request(request.message)
    if is_vague:
        return JSONResponse({
            "error": "vague_request",
            "message": "Please provide more specific project details.",
            "clarification": clarification,
        }, status_code=422)

    project_id = request.project_id or str(uuid.uuid4())

    try:
        project_name = _extract_project_name(request.message)
        await database.ensure_project(
            project_id,
            name=project_name,
            spec={
                "message": request.message,
                "mode": "plan",
                "run_mode": request.mode if request.mode in {"generate", "modify"} else ("modify" if request.project_id else "generate"),
                "context_mode": "auto",
                "ui_mode": "plan",
            },
            status="planning",
        )
        await database.save_chat_message(
            message_id=str(uuid.uuid4()),
            project_id=project_id,
            role="user",
            content=request.message,
            metadata={"mode": "plan"},
        )
    except Exception as e:
        logger.warning(f"[plan] Failed to persist plan request for {project_id}: {e}")

    if _has_active_celery_worker():
        from .worker import run_plan_task

        logger.info(f"[plan] Dispatching plan task to Celery worker for project: {project_id}")
        run_plan_task.delay(project_id, request.message, "auto")
    else:
        logger.warning(
            f"[plan] No Celery worker detected for project {project_id}. "
            "Starting plan generation in-process."
        )
        asyncio.create_task(
            start_plan_swarm_background(
                project_id=project_id,
                user_message=request.message,
                context_mode="auto",
            )
        )

    return JSONResponse({
        "project_id": project_id,
        "status": "planning",
        "mode": request.mode if request.mode in {"generate", "modify"} else ("modify" if request.project_id else "generate"),
        "context_mode": "auto",
        "message": "Plan generation started. Connect to SSE stream for updates.",
    })


class ApproveRequest(BaseModel):
    project_id: str
    message: str | None = None
    spec_content: str | None = None


@app.post("/api/approve")
async def approve_plan(request: ApproveRequest):
    """Approve a generated SPEC.md and start the full implementation swarm."""
    project_id = request.project_id
    
    # 1. Check if project exists and has a SPEC.md
    workspace = WORKSPACE_BASE / project_id
    spec_path = workspace / "SPEC.md"

    if request.spec_content and request.spec_content.strip():
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(request.spec_content)
        except Exception as e:
            return JSONResponse(
                {"error": f"Failed to save SPEC.md before approval: {e}"},
                status_code=500,
            )

    if not spec_path.exists():
        return JSONResponse(
            {"error": "No plan (SPEC.md) found for this project. Generate a plan first."},
            status_code=400
        )
    
    # 2. Get the original message if not provided
    user_message = request.message
    if not user_message:
        project = await database.get_project(project_id)
        if project and project.get("spec"):
            spec = project.get("spec")
            if isinstance(spec, str):
                spec = json.loads(spec)
            user_message = spec.get("message")
    
    if not user_message:
        user_message = "Implement the approved project specification"

    current_project = await database.get_project(project_id)
    current_spec = _coerce_project_spec(current_project)
    current_spec.update(
        {
            "message": user_message,
            "run_mode": "approved",
            "context_mode": "auto",
            "approved_spec_content": request.spec_content or current_spec.get("spec_content"),
        }
    )
    await database.update_project_spec(project_id, current_spec, status="pending")

    # 3. Update status to pending so event_generator can start it
    await database.update_project_status(project_id, "pending")
    await blackboard.set_project_state(
        project_id,
        {"status": "pending", "run_mode": "approved", "context_mode": "auto"},
    )

    # 4. Trigger the implementation swarm via Celery, or fall back in-process.
    if _has_active_celery_worker():
        from .worker import run_swarm_task

        logger.info(f"[approve] Dispatching build task to Celery worker for project: {project_id}")
        run_swarm_task.delay(
            project_id=project_id,
            user_message=user_message,
            context_mode="auto",
            run_mode="approved",
            ui_mode="build"
        )
    else:
        logger.warning(
            f"[approve] No Celery worker detected for project {project_id}. "
            "Starting approved build in-process."
        )
        asyncio.create_task(
            start_swarm_background(
                project_id=project_id,
                user_message=user_message,
                context_mode="auto",
                run_mode="approved",
                ui_mode="build",
            )
        )

    return JSONResponse({
        "project_id": project_id,
        "status": "starting",
        "mode": "approved",
        "context_mode": "auto",
        "message": "Plan approved. Implementation swarm started.",
    })


class AnswerRequest(BaseModel):
    question_id: str
    answers: list[str]
    questions: list[dict[str, Any]] | None = None
    ui_mode: str | None = None


class DirectiveRequest(BaseModel):
    agent: str  # backend | frontend | devops | packager
    message: str


@app.post("/api/projects/{project_id}/directive")
async def send_directive(project_id: str, request: DirectiveRequest):
    """Send a mid-run directive to a running specialist agent.

    The agent picks it up non-blocking at its next verify_progress checkpoint.
    Only one directive per agent is queued at a time; sending a new one
    overwrites any unread previous directive.
    """
    import redis.asyncio as _redis
    import os as _os
    from .swarm.tools.user_directive import directive_redis_key

    VALID_AGENTS = {"rootdep", "backend", "frontend", "devops", "packager"}
    if request.agent not in VALID_AGENTS:
        return JSONResponse(
            {"status": "error", "error": f"Unknown agent '{request.agent}'. Valid: {sorted(VALID_AGENTS)}"},
            status_code=400,
        )
    if not request.message.strip():
        return JSONResponse({"status": "error", "error": "message must not be empty"}, status_code=400)

    redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379")
    r: _redis.Redis | None = None
    try:
        r = _redis.from_url(redis_url, decode_responses=True)
        key = directive_redis_key(project_id, request.agent)
        # SETEX: overwrites any pending directive; 1h TTL so stale directives don't linger
        await r.setex(key, 3600, request.message.strip())

        # Publish SSE so the frontend can show "directive queued" immediately
        channel = f"project:{project_id}:events"
        event_payload = __import__("json").dumps({
            "type": "directive_queued",
            "data": {"agent": request.agent, "message": request.message.strip()},
        })
        await r.publish(channel, event_payload)
    finally:
        if r is not None:
            await r.aclose()

    return JSONResponse({"status": "queued", "agent": request.agent})


@app.post("/api/projects/{project_id}/swarm/stop")
async def stop_swarm(project_id: str):
    """Stop the entire swarm for a project.

    Sets a Redis flag that execute_parallel checks between agent steps and
    poll_user_directive checks inside any blocked pause loop.
    Works for both in-process and Celery execution paths.
    """
    import redis.asyncio as _redis
    import os as _os
    import json as _json
    from .swarm.tools.user_directive import swarm_stop_redis_key

    redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379")
    r: _redis.Redis | None = None
    try:
        r = _redis.from_url(redis_url, decode_responses=True)
        await r.setex(swarm_stop_redis_key(project_id), 86400, "1")
        channel = f"project:{project_id}:events"
        await r.publish(channel, _json.dumps({
            "type": "swarm_stop_requested",
            "data": {"project_id": project_id},
        }))
    finally:
        if r is not None:
            await r.aclose()

    return JSONResponse({"status": "stop_requested"})


class PauseRequest(BaseModel):
    message: str = ""


class ResumeRequest(BaseModel):
    message: str


VALID_PAUSABLE_AGENTS = {"backend", "frontend", "devops", "packager"}


@app.post("/api/projects/{project_id}/agents/{agent_name}/pause")
async def pause_agent(project_id: str, agent_name: str, request: PauseRequest):
    """Pause a running agent at its next checkpoint.

    The agent blocks until the user calls /resume or the pause times out (30 min).
    Sends a __PAUSE__ directive via the same Redis key as poll_user_directive.
    """
    import redis.asyncio as _redis
    import os as _os
    import json as _json
    from .swarm.tools.user_directive import directive_redis_key, PAUSE_PREFIX

    if agent_name not in VALID_PAUSABLE_AGENTS:
        return JSONResponse(
            {"status": "error", "error": f"Unknown agent '{agent_name}'"},
            status_code=400,
        )

    redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379")
    r: _redis.Redis | None = None
    try:
        r = _redis.from_url(redis_url, decode_responses=True)
        value = f"{PAUSE_PREFIX} {request.message.strip()}" if request.message.strip() else f"{PAUSE_PREFIX} User requested pause"
        await r.setex(directive_redis_key(project_id, agent_name), 3600, value)
        channel = f"project:{project_id}:events"
        await r.publish(channel, _json.dumps({
            "type": "pause_requested",
            "data": {"agent": agent_name, "message": request.message},
        }))
    finally:
        if r is not None:
            await r.aclose()

    return JSONResponse({"status": "pause_requested", "agent": agent_name})


@app.post("/api/projects/{project_id}/agents/{agent_name}/resume")
async def resume_agent(project_id: str, agent_name: str, request: ResumeRequest):
    """Resume a paused agent with optional user input.

    Writes to the resume key that poll_user_directive polls while blocked.
    The agent receives the user's input and continues its work.
    """
    import redis.asyncio as _redis
    import os as _os
    import json as _json
    from .swarm.tools.user_directive import resume_redis_key

    if agent_name not in VALID_PAUSABLE_AGENTS:
        return JSONResponse(
            {"status": "error", "error": f"Unknown agent '{agent_name}'"},
            status_code=400,
        )
    if not request.message.strip():
        return JSONResponse({"status": "error", "error": "message must not be empty"}, status_code=400)

    redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379")
    r: _redis.Redis | None = None
    try:
        r = _redis.from_url(redis_url, decode_responses=True)
        await r.setex(resume_redis_key(project_id, agent_name), 3600, request.message.strip())
        channel = f"project:{project_id}:events"
        await r.publish(channel, _json.dumps({
            "type": "resume_requested",
            "data": {"agent": agent_name, "message": request.message},
        }))
    finally:
        if r is not None:
            await r.aclose()

    return JSONResponse({"status": "resume_requested", "agent": agent_name})


@app.post("/api/projects/{project_id}/answer")
async def submit_answer(project_id: str, request: AnswerRequest):
    """Receive user answers for a pending ask_user() question from an agent.

    The agent polls the Redis key written here.  The key expires after 1 hour.
    """
    import json as _json
    import redis.asyncio as _redis
    import os as _os

    redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379")
    answer_key = f"project:{project_id}:questions:{request.question_id}:answers"

    r: _redis.Redis | None = None
    try:
        r = _redis.from_url(redis_url, decode_responses=True)
        await r.set(answer_key, _json.dumps(request.answers), ex=3600)
        try:
            answered = []
            for idx, answer in enumerate(request.answers):
                question = (request.questions or [])[idx] if request.questions and idx < len(request.questions) else {}
                answered.append({
                    "question": question.get("label") or question.get("question") or f"Question {idx + 1}",
                    "answer": answer,
                    "type": question.get("type") or "text",
                })
            await database.save_chat_message(
                message_id=str(uuid.uuid4()),
                project_id=project_id,
                role="user",
                content="\n".join(f"{item['question']}: {item['answer']}" for item in answered),
                metadata={
                    "type": "question_answers",
                    "question_id": request.question_id,
                    "ui_mode": request.ui_mode,
                    "answers": answered,
                },
            )
            current_project = await database.get_project(project_id)
            current_spec = _coerce_project_spec(current_project)
            preferences = current_spec.get("user_preferences")
            if not isinstance(preferences, list):
                preferences = []
            preferences.extend(answered)
            current_spec["user_preferences"] = preferences
            await database.update_project_spec(project_id, current_spec)
        except Exception as persist_error:
            logger.warning("[answer] Failed to persist answer metadata for %s: %s", project_id, persist_error)
    finally:
        if r is not None:
            await r.aclose()

    return JSONResponse({"status": "accepted"})


class DiscussRequest(BaseModel):
    message: str
    project_id: str | None = None


@app.post("/api/discuss")
async def discuss(request: DiscussRequest):
    """Discuss mode: Conversational AI with read-only tools.

    Discuss mode is a lightweight conversational mode that uses read-only tools:
    - read_file: Read files in the workspace
    - list_files: List files in workspace
    - web_search: Search the web for information
    - fetch_url: Fetch content from URLs

    No write, bash, or execute permissions - safe for exploration.
    """
    project_id = request.project_id or str(uuid.uuid4())

    try:
        project_name = _extract_project_name(request.message)
        await database.ensure_project(
            project_id,
            name=project_name,
            spec={
                "message": request.message,
                "mode": "discuss",
            },
            status="discussing",
        )
        await database.save_chat_message(
            message_id=str(uuid.uuid4()),
            project_id=project_id,
            role="user",
            content=request.message,
            metadata={"mode": "discuss"},
        )
    except Exception as e:
        logger.warning(f"[discuss] Failed to persist discuss request for {project_id}: {e}")

    async def discuss_event_generator():
        try:
            from .llm.minimax import get_llm
            from .swarm.tools.workspace_tools import read_file, list_files
            from .swarm.tools.web_search import web_search
            from .swarm.tools.fetch_url import fetch_url

            read_only_tools = [read_file, list_files, web_search, fetch_url]

            workspace = WORKSPACE_BASE / project_id
            spec_content = ""
            if (workspace / "SPEC.md").exists():
                spec_content = (workspace / "SPEC.md").read_text(errors="replace")

            existing_files = []
            if workspace.exists():
                for f in sorted(workspace.rglob("*"))[:90]:
                    if f.is_file() and not f.name.endswith(".zip"):
                        existing_files.append(str(f.relative_to(workspace)))

            llm = get_llm("minimax")

            tech_stack_line = (
                "Use the SPEC.md below to identify the exact tech stack for this project."
                if spec_content
                else "This appears to be a new project with no SPEC.md yet — ask the user what stack they want."
            )
            system_prompt = f"""You are a helpful architecture and development advisor.

Your role is to DISCUSS, CLARIFY, and RECOMMEND - not to write code or execute commands.

{tech_stack_line}

Guidelines:
- Ask clarifying questions to understand requirements better
- Explain architectural decisions and tradeoffs
- Suggest best practices for the tech stack defined in SPEC.md
- Discuss implementation approaches without implementing them
- You have read-only access to the project workspace

Available read-only tools: read_file, list_files, web_search, fetch_url

Current project workspace: {project_id}
Existing files: {existing_files[:60]}

{spec_content[:9000] if spec_content else '(No SPEC.md found - this appears to be a new project)'}

Remember: You are in DISCUSS mode. Do not write any code or suggest file modifications.
Focus on: understanding requirements, explaining architecture, recommending approaches, asking clarifying questions."""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.message}
            ]

            chat_llm = llm.bind_tools(read_only_tools, parallel_tool_calls=True)

            response = await llm.ainvoke([
                {"role": m["role"], "content": m["content"]}
                for m in messages
            ])

            if hasattr(response, "content") and response.content:
                try:
                    await database.save_chat_message(
                        message_id=str(uuid.uuid4()),
                        project_id=project_id,
                        role="assistant",
                        content=response.content,
                        metadata={"mode": "discuss"},
                    )
                except Exception as e:
                    logger.warning(f"[discuss] Failed to save assistant message: {e}")

                yield json.dumps({
                    "type": "text",
                    "content": response.content,
                    "agent_name": "discuss",
                    "timestamp": int(datetime.now().timestamp() * 1000),
                }) + "\n"

            if hasattr(response, "tool_calls") and response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})

                    yield json.dumps({
                        "type": "tool_call",
                        "tool": tool_name,
                        "agent_name": "discuss",
                        "timestamp": int(datetime.now().timestamp() * 1000),
                    }) + "\n"

                    try:
                        if tool_name == "read_file":
                            result = read_file(**tool_args)
                        elif tool_name == "list_files":
                            result = list_files(**tool_args)
                        elif tool_name == "web_search":
                            result = web_search(**tool_args)
                        elif tool_name == "fetch_url":
                            result = fetch_url(**tool_args)
                        else:
                            result = {"status": "error", "error": f"Unknown tool: {tool_name}"}

                        yield json.dumps({
                            "type": "tool_result",
                            "tool": tool_name,
                            "result": result,
                            "agent_name": "discuss",
                            "timestamp": int(datetime.now().timestamp() * 1000),
                        }) + "\n"

                        follow_up = await llm.ainvoke([
                            {"role": "user", "content": f"Tool {tool_name} returned: {json.dumps(result)}. Provide a helpful response."}
                        ])
                        if hasattr(follow_up, "content") and follow_up.content:
                            try:
                                await database.save_chat_message(
                                    message_id=str(uuid.uuid4()),
                                    project_id=project_id,
                                    role="assistant",
                                    content=follow_up.content,
                                    metadata={"mode": "discuss"},
                                )
                            except Exception as e:
                                logger.warning(f"[discuss] Failed to save follow-up message: {e}")

                            yield json.dumps({
                                "type": "text",
                                "content": follow_up.content,
                                "agent_name": "discuss",
                                "timestamp": int(datetime.now().timestamp() * 1000),
                            }) + "\n"
                    except Exception as e:
                        yield json.dumps({
                            "type": "error",
                            "content": f"Tool error: {str(e)}",
                            "agent_name": "discuss",
                            "timestamp": int(datetime.now().timestamp() * 1000),
                        }) + "\n"

            yield json.dumps({
                "type": "RunFinished",
                "content": "Discuss complete",
                "agent_name": "discuss",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "data": {"outcome": {"type": "success"}, "project_id": project_id}
            }) + "\n"

        except Exception as e:
            logger.error(f"[discuss] Error: {e}")
            yield json.dumps({
                "type": "error",
                "content": f"Discuss error: {str(e)}",
                "agent_name": "discuss",
                "timestamp": int(datetime.now().timestamp() * 1000),
            }) + "\n"
            yield json.dumps({
                "type": "RunFinished",
                "content": "Discuss ended with error",
                "agent_name": "discuss",
                "timestamp": int(datetime.now().timestamp() * 1000),
                "data": {"outcome": {"type": "error"}, "project_id": project_id}
            }) + "\n"

    return EventSourceResponse(discuss_event_generator())


@app.get("/api/stream/{project_id}")
async def stream(project_id: str, request: Request):
    user_message = request.query_params.get("message") or ""
    context_mode = request.query_params.get("context_mode") or "auto"
    context_mode = _normalize_context_mode(context_mode)
    run_mode = request.query_params.get("mode") or "generate"
    ui_mode = request.query_params.get("ui_mode") or "build"
    since_event_id = _parse_last_event_id(
        request.headers.get("last-event-id") or request.query_params.get("since_event_id")
    )

    async def event_generator_wrapper():
        async for event in event_generator(
            project_id,
            user_message,
            context_mode,
            run_mode,
            ui_mode,
            since_event_id=since_event_id,
        ):
            if await request.is_disconnected():
                break
            yield event

    return EventSourceResponse(
        event_generator_wrapper(),
        ping=15,
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@app.get("/api/status/{project_id}")
async def get_status(project_id: str):
    state = await blackboard.get_project_state(project_id)
    project = await database.get_project(project_id) if getattr(database, "_pool", None) else None

    if not state and not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    project_spec = _coerce_project_spec(project)
    workspace_spec_path = WORKSPACE_BASE / project_id / "SPEC.md"
    spec_content = project_spec.get("spec_content")
    if not spec_content and workspace_spec_path.exists():
        spec_content = workspace_spec_path.read_text(errors="replace")

    effective_status = (
        state.get("status")
        if isinstance(state, dict) and state.get("status")
        else (project.get("status", "unknown") if project else "unknown")
    )
    run_mode = (
        state.get("run_mode")
        if isinstance(state, dict) and state.get("run_mode")
        else project_spec.get("run_mode")
    )
    context_mode = (
        state.get("context_mode")
        if isinstance(state, dict) and state.get("context_mode")
        else project_spec.get("context_mode")
    )

    return JSONResponse({
        "project_id": project_id,
        "status": effective_status,
        "error": state.get("error") if isinstance(state, dict) else None,
        "run_mode": run_mode,
        "context_mode": context_mode,
        "checkpoint_id": (
            state.get("checkpoint_id")
            if isinstance(state, dict)
            else None
        ),
        "spec": project_spec,
        "spec_content": spec_content,
        "source": "blackboard" if state else "database",
    })


@app.get("/api/projects")
async def list_projects(limit: int = 50, offset: int = 0):
    try:
        rows = await database.list_projects(limit=limit, offset=offset)
        return JSONResponse({
            "projects": [_row_to_json(row) for row in rows],
            "count": len(rows),
            "limit": limit,
            "offset": offset
        })
    except Exception as e:
        logger.error(f"[projects] Failed to list: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


class ProjectCreateRequest(BaseModel):
    name: str | None = None
    message: str | None = None


@app.post("/api/projects")
async def create_project(request: ProjectCreateRequest):
    try:
        project_id = str(uuid.uuid4())
        project_name = request.name or _extract_project_name(request.message or "New Project")
        await database.ensure_project(
            project_id,
            name=project_name,
            spec={
                "message": request.message or "",
                "mode": "new",
            },
            status="pending",
        )
        return JSONResponse({
            "project_id": project_id,
            "name": project_name,
            "status": "pending",
        })
    except Exception as e:
        logger.error(f"[projects] Failed to create: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Completely delete a project and all associated data.

    Cleans up:
    - PostgreSQL: project, messages, checkpoints, context_summaries, agent_checkpoints
    - Redis: all project:* keys
    - Filesystem: workspace and checkpoint directories
    - MinIO: checkpoint objects
    """
    # 1. Reject if project is currently running
    state = await blackboard.get_project_state(project_id)
    if state and state.get("status") == "running":
        return JSONResponse(
            {"error": "Cannot delete a running project", "project_id": project_id},
            status_code=409,
        )

    deleted = {
        "database": False,
        "redis": 0,
        "filesystem_workspace": False,
        "filesystem_checkpoints": False,
        "minio": {},
    }

    try:
        # 2. Delete from PostgreSQL
        await database.delete_project(project_id)
        deleted["database"] = True
    except Exception as e:
        logger.error(f"[delete] Database cleanup failed for {project_id}: {e}")

    try:
        # 3. Delete all Redis keys for project
        redis_deleted = await blackboard.delete_project_keys(project_id)
        deleted["redis"] = redis_deleted
    except Exception as e:
        logger.error(f"[delete] Redis cleanup failed for {project_id}: {e}")

    try:
        # 4. Delete workspace directory
        workspace = WORKSPACE_BASE / project_id
        if workspace.exists():
            shutil.rmtree(workspace)
            deleted["filesystem_workspace"] = True
    except Exception as e:
        logger.error(f"[delete] Workspace cleanup failed for {project_id}: {e}")

    try:
        # 5. Delete local checkpoint directory
        checkpoint_dir = CHECKPOINT_BASE / project_id
        if checkpoint_dir.exists():
            shutil.rmtree(checkpoint_dir)
            deleted["filesystem_checkpoints"] = True
    except Exception as e:
        logger.error(f"[delete] Checkpoint cleanup failed for {project_id}: {e}")

    try:
        # 6. Delete MinIO objects
        minio_result = await storage.delete_objects_by_prefix(f"checkpoints/{project_id}/")
        deleted["minio"] = minio_result
    except Exception as e:
        logger.error(f"[delete] MinIO cleanup failed for {project_id}: {e}")

    logger.info(f"[delete] Project {project_id} deleted: {deleted}")
    return JSONResponse({
        "project_id": project_id,
        "deleted": deleted,
        "status": "deleted",
    })


@app.get("/api/projects/{project_id}/messages")
async def get_project_messages(project_id: str, limit: int = 500):
    try:
        rows = await database.get_chat_messages(project_id, limit=limit)
        return JSONResponse({
            "project_id": project_id,
            "messages": [_row_to_json(row) for row in reversed(rows)],
        })
    except Exception as e:
        logger.error(f"[messages] Failed for {project_id}: {e}")
        return JSONResponse({"error": str(e), "project_id": project_id}, status_code=500)


@app.get("/api/projects/{project_id}/checkpoints")
async def list_project_checkpoints(project_id: str, limit: int = 25):
    try:
        rows = await database.list_project_checkpoints(project_id, limit=limit)
        return JSONResponse({
            "project_id": project_id,
            "checkpoints": [_row_to_json(row) for row in rows],
        })
    except Exception as e:
        logger.error(f"[checkpoint] Failed to list for {project_id}: {e}")
        return JSONResponse({"error": str(e), "project_id": project_id}, status_code=500)


@app.post("/api/projects/{project_id}/restore/{checkpoint_id}")
async def restore_project_checkpoint(project_id: str, checkpoint_id: str):
    state = await blackboard.get_project_state(project_id)
    if state and state.get("status") == "running":
        return JSONResponse(
            {"error": "Cannot restore while project is running", "project_id": project_id},
            status_code=409,
        )

    try:
        checkpoint = await database.get_project_checkpoint(project_id, checkpoint_id)
        if not checkpoint:
            return JSONResponse(
                {"error": "Checkpoint not found", "project_id": project_id, "checkpoint_id": checkpoint_id},
                status_code=404,
            )

        snapshot_path_val = checkpoint["snapshot_path"]
        snapshot_path = Path(snapshot_path_val)
        
        # If the path doesn't exist locally, it might be a MinIO object name
        is_remote = not snapshot_path.exists()
        
        if is_remote:
            logger.info(f"[restore] Snapshot not found locally at {snapshot_path}. Downloading from MinIO...")
            temp_zip = CHECKPOINT_BASE / project_id / f"{checkpoint_id}_restore.zip"
            temp_zip.parent.mkdir(parents=True, exist_ok=True)
            await storage.download_file(snapshot_path_val, temp_zip)
            snapshot_path = temp_zip

        workspace = WORKSPACE_BASE / project_id
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True, exist_ok=True)

        _safe_extract_checkpoint(snapshot_path, workspace)
        
        if is_remote and snapshot_path.exists():
            snapshot_path.unlink()

        await database.update_project_status(project_id, "complete")
        await blackboard.set_project_state(
            project_id,
            {
                "status": "complete",
                "run_mode": "restore",
                "checkpoint_id": checkpoint_id,
            },
        )
        await database.save_chat_message(
            message_id=str(uuid.uuid4()),
            project_id=project_id,
            role="assistant",
            content=f"Restored checkpoint: {checkpoint.get('label', checkpoint_id)}",
            metadata={"checkpoint_id": checkpoint_id, "run_mode": "restore"},
        )
        return JSONResponse({
            "status": "restored",
            "project_id": project_id,
            "checkpoint": _row_to_json(checkpoint),
        })
    except Exception as e:
        logger.error(f"[checkpoint] Restore failed for {project_id}/{checkpoint_id}: {e}")
        return JSONResponse(
            {"error": str(e), "project_id": project_id, "checkpoint_id": checkpoint_id},
            status_code=500,
        )


def _get_checkpoint_zip_path(project_id: str, checkpoint_id: str) -> tuple[Path, bool]:
    """Get the path to a checkpoint zip, downloading from MinIO if needed.

    Returns (path, was_downloaded_from_minio)
    """
    checkpoint = None
    for row in []:
        pass

    local_path = CHECKPOINT_BASE / project_id / f"{checkpoint_id}.zip"
    if local_path.exists():
        return local_path, False

    checkpoint = None
    try:
        checkpoints = database.list_project_checkpoints(project_id, limit=1)
        if checkpoints and checkpoints[0]["id"] == checkpoint_id:
            checkpoint = checkpoints[0]
    except:
        pass

    if not checkpoint:
        for cp in database.list_project_checkpoints(project_id, limit=100):
            if cp["id"] == checkpoint_id:
                checkpoint = cp
                break

    if checkpoint:
        snapshot_path_val = checkpoint["snapshot_path"]
        if not snapshot_path_val.startswith("/"):
            temp_zip = CHECKPOINT_BASE / project_id / f"{checkpoint_id}_download.zip"
            temp_zip.parent.mkdir(parents=True, exist_ok=True)
            import asyncio
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(storage.download_file(snapshot_path_val, temp_zip))
            return temp_zip, True

    return local_path, False


@app.get("/api/checkpoints/{project_id}/{checkpoint_id}/files")
async def list_checkpoint_files(project_id: str, checkpoint_id: str):
    """List files in a checkpoint without restoring it.

    This allows previewing what files exist in a checkpoint before restoring.
    """
    try:
        checkpoint = await database.get_project_checkpoint(project_id, checkpoint_id)
        if not checkpoint:
            return JSONResponse(
                {"error": "Checkpoint not found"},
                status_code=404,
            )

        snapshot_path_val = checkpoint["snapshot_path"]
        snapshot_path = Path(snapshot_path_val)

        is_remote = not snapshot_path.exists()

        if is_remote:
            temp_zip = CHECKPOINT_BASE / project_id / f"{checkpoint_id}_preview.zip"
            if not temp_zip.exists():
                temp_zip.parent.mkdir(parents=True, exist_ok=True)
                await storage.download_file(snapshot_path_val, temp_zip)
            snapshot_path = temp_zip

        import zipfile
        files = []
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            for name in sorted(zf.namelist()):
                if not name.endswith("/") and not name.endswith(".zip"):
                    info = zf.getinfo(name)
                    files.append({
                        "name": name.split("/")[-1],
                        "path": name,
                        "type": "file",
                        "size": info.file_size,
                    })

        if is_remote and temp_zip.exists():
            temp_zip.unlink()

        return JSONResponse({
            "project_id": project_id,
            "checkpoint_id": checkpoint_id,
            "files": files,
            "count": len(files),
        })
    except Exception as e:
        logger.error(f"[checkpoint] Failed to list files for {project_id}/{checkpoint_id}: {e}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


@app.get("/api/checkpoints/{project_id}/{checkpoint_id}/read")
async def read_checkpoint_file(project_id: str, checkpoint_id: str, path: str):
    """Read a specific file from a checkpoint without restoring.

    This allows previewing file content before deciding to restore.
    """
    try:
        checkpoint = await database.get_project_checkpoint(project_id, checkpoint_id)
        if not checkpoint:
            return JSONResponse(
                {"error": "Checkpoint not found"},
                status_code=404,
            )

        snapshot_path_val = checkpoint["snapshot_path"]
        snapshot_path = Path(snapshot_path_val)

        is_remote = not snapshot_path.exists()

        if is_remote:
            temp_zip = CHECKPOINT_BASE / project_id / f"{checkpoint_id}_preview.zip"
            if not temp_zip.exists():
                temp_zip.parent.mkdir(parents=True, exist_ok=True)
                await storage.download_file(snapshot_path_val, temp_zip)
            snapshot_path = temp_zip

        import zipfile
        with zipfile.ZipFile(snapshot_path, "r") as zf:
            try:
                content = zf.read(path).decode("utf-8", errors="replace")
            except KeyError:
                return JSONResponse(
                    {"error": "File not found in checkpoint", "path": path},
                    status_code=404,
                )

        if is_remote and temp_zip.exists():
            temp_zip.unlink()

        return JSONResponse({
            "project_id": project_id,
            "checkpoint_id": checkpoint_id,
            "path": path,
            "content": content,
            "language": _get_language(path.split("/")[-1]),
        })
    except Exception as e:
        logger.error(f"[checkpoint] Failed to read file for {project_id}/{checkpoint_id}: {e}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


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


@app.get("/api/context/{project_id}")
async def list_context(project_id: str, limit: int = 25):
    try:
        rows = await database.list_context_summaries(project_id, limit=limit)
        return JSONResponse({
            "project_id": project_id,
            "summaries": [context_summary_to_json(row) for row in rows],
        })
    except Exception as e:
        logger.error(f"[context] Failed to list summaries for {project_id}: {e}")
        return JSONResponse({"error": str(e), "project_id": project_id}, status_code=500)


@app.get("/api/context/{project_id}/{agent_name}")
async def get_agent_context(project_id: str, agent_name: str, limit: int = 10):
    try:
        rows = await database.list_context_summaries(project_id, agent_name=agent_name, limit=limit)
        latest = rows[0] if rows else None
        return JSONResponse({
            "project_id": project_id,
            "agent_name": agent_name,
            "latest": context_summary_to_json(latest) if latest else None,
            "summaries": [context_summary_to_json(row) for row in rows],
        })
    except Exception as e:
        logger.error(f"[context] Failed to load summary for {project_id}/{agent_name}: {e}")
        return JSONResponse(
            {"error": str(e), "project_id": project_id, "agent_name": agent_name},
            status_code=500,
        )


@app.get("/api/download/{project_id}/project.zip")
async def download_project(project_id: str):
    from pathlib import Path

    await ensure_workspace_is_warm(project_id)

    workspace = WORKSPACE_BASE / project_id
    zip_path = workspace / f"{project_id}.zip"

    if not zip_path.exists():
        try:
            file_count = 0
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if workspace.exists():
                    for file_path in workspace.rglob("*"):
                        if file_path.is_file() and not file_path.name.endswith(".zip") and file_path.name != f"{project_id}.zip":
                            zf.write(file_path, file_path.relative_to(workspace))
                            file_count += 1
            logger.info(f"[download] Created ZIP for {project_id} with {file_count} files")
        except Exception as e:
            logger.error(f"[download] Failed to create ZIP for {project_id}: {e}")
            return JSONResponse({"error": f"Failed to create ZIP: {str(e)}"}, status_code=500)

    if not zip_path.exists():
        return JSONResponse({"error": "ZIP not found and could not be created"}, status_code=404)

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
    from .storage.minio_client import MinioStorage
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


def _build_file_tree(workspace: Path, base_path: Path | None = None) -> list[dict]:
    """Recursively build a file tree structure."""
    if base_path is None:
        base_path = workspace

    items = []
    try:
        for entry in sorted(workspace.iterdir()):
            if entry.name.endswith(".zip"):
                continue

            rel_path = entry.relative_to(base_path)
            if entry.is_dir():
                children = _build_file_tree(entry, base_path)
                items.append({
                    "name": entry.name,
                    "path": str(rel_path),
                    "type": "directory",
                    "children": children,
                })
            else:
                items.append({
                    "name": entry.name,
                    "path": str(rel_path),
                    "type": "file",
                })
    except PermissionError:
        pass

    return items


def _get_language(filename: str) -> str:
    """Map file extension to Monaco language."""
    parts = filename.split('.')
    ext = parts[-1].lower() if len(parts) > 1 else ''
    lang_map = {
        'java': 'java',
        'svelte': 'html',
        'ts': 'typescript',
        'tsx': 'typescript',
        'js': 'javascript',
        'jsx': 'javascript',
        'json': 'json',
        'yml': 'yaml',
        'yaml': 'yaml',
        'xml': 'xml',
        'properties': 'properties',
        'gradle': 'groovy',
        'md': 'markdown',
        'css': 'css',
        'html': 'html',
        'txt': 'plaintext',
        'py': 'python',
        'sh': 'shell',
        'bash': 'shell',
        'sql': 'sql',
        'dockerfile': 'dockerfile',
    }
    return lang_map.get(ext, 'plaintext')


@app.get("/api/workspace/{project_id}/files")
async def list_workspace_files(project_id: str):
    """List all files in a project workspace as a tree structure."""
    workspace = WORKSPACE_BASE / project_id

    if not workspace.exists():
        return JSONResponse({
            "project_id": project_id,
            "files": [],
            "message": "Workspace not found",
        })

    files = _build_file_tree(workspace)
    return JSONResponse({
        "project_id": project_id,
        "files": files,
        "count": sum(1 for _ in workspace.rglob("*") if _.is_file() and not _.name.endswith(".zip")),
    })


@app.post("/api/workspace/{project_id}/warmup")
async def warmup_workspace(project_id: str):
    """Warm up the workspace by restoring from latest checkpoint if needed.

    This ensures the workspace is ready to serve files before project select.
    Returns the workspace status after warmup.
    """
    workspace = WORKSPACE_BASE / project_id
    workspace_exists = workspace.exists() and any(workspace.iterdir())

    if workspace_exists:
        file_count = sum(1 for _ in workspace.rglob("*") if _.is_file() and not _.name.endswith(".zip"))
        return JSONResponse({
            "project_id": project_id,
            "status": "warm",
            "message": "Workspace already warm",
            "file_count": file_count,
        })

    await ensure_workspace_is_warm(project_id)

    workspace = WORKSPACE_BASE / project_id
    workspace_exists = workspace.exists() and any(workspace.iterdir())

    if not workspace_exists:
        project = await database.get_project(project_id) if getattr(database, "_pool", None) else None
        project_spec = _coerce_project_spec(project)
        spec_content = project_spec.get("spec_content")
        if project and project.get("status") == "plan_ready" and spec_content:
            workspace.mkdir(parents=True, exist_ok=True)
            (workspace / "SPEC.md").write_text(spec_content)
            workspace_exists = True

    if workspace_exists:
        file_count = sum(1 for _ in workspace.rglob("*") if _.is_file() and not _.name.endswith(".zip"))
        return JSONResponse({
            "project_id": project_id,
            "status": "warmed",
            "message": "Workspace restored from checkpoint" if file_count > 1 else "Workspace hydrated from saved SPEC.md",
            "file_count": file_count,
        })

    return JSONResponse({
        "project_id": project_id,
        "status": "cold",
        "message": "No checkpoint found, workspace empty",
        "file_count": 0,
    })


@app.get("/api/workspace/{project_id}/read")
async def read_workspace_file(project_id: str, path: str):
    """Read a specific file from the workspace."""
    workspace = WORKSPACE_BASE / project_id
    file_path = (workspace / path).resolve()

    if not file_path.exists():
        return JSONResponse(
            {"error": "File not found", "path": path, "project_id": project_id},
            status_code=404,
        )

    try:
        file_path.relative_to(workspace.resolve())
    except ValueError:
        return JSONResponse(
            {"error": "Path traversal detected", "path": path},
            status_code=400,
        )

    try:
        content = file_path.read_text(errors="replace")
        return JSONResponse({
            "project_id": project_id,
            "path": path,
            "content": content,
            "language": _get_language(file_path.name),
            "size": file_path.stat().st_size,
        })
    except Exception as e:
        return JSONResponse(
            {"error": f"Failed to read file: {str(e)}", "path": path},
            status_code=500,
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
