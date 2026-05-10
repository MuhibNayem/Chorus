"""LangChain tools and coordinator helpers for swarm readiness claims."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from ..claim_store import ClaimNotFoundError, ClaimStore
from ..claim_validators import merge_validation_results, validate_claim_evidence
from ..claims import ClaimStatus, ClaimType, build_claim_payload, claim_now_iso, get_claim_dependents, get_claim_producer
from .todo_tools import get_agent_name, get_agent_todos
from . import workspace_tools
from .workspace_tools import get_project_id, get_workspace, snapshot_workspace

logger = logging.getLogger("claim_tools")

DEFAULT_WAIT_TIMEOUT_SECONDS = 3600
DEFAULT_WAIT_POLL_SECONDS = 1.0
# Tolerance for the publish_claim tool's own start/end events plus the agent's
# completion event.  Claims with a seq difference <= this are not auto-marked
# stale purely based on event sequence.
EVENT_SEQ_TOLERANCE = 2

# Max output length returned to the agent on verification failure.
MAX_VERIFY_OUTPUT_CHARS = 8000
VERIFY_EXECUTOR_MODE = os.environ.get("SWARM_VERIFY_EXECUTOR", "auto").lower()
VERIFY_DOCKER_WORKDIR = "/workspace"
VERIFY_DOCKER_IMAGES = {
    "python": os.environ.get("SWARM_VERIFY_IMAGE_PYTHON", "python:3.12-slim"),
    "go": os.environ.get("SWARM_VERIFY_IMAGE_GO", "golang:1.24"),
    "java": os.environ.get("SWARM_VERIFY_IMAGE_JAVA", "maven:3.9.9-eclipse-temurin-21"),
    "gradle": os.environ.get("SWARM_VERIFY_IMAGE_GRADLE", "gradle:8.5-jdk21"),
    "node": os.environ.get("SWARM_VERIFY_IMAGE_NODE", "node:20-bookworm"),
    "rust": os.environ.get("SWARM_VERIFY_IMAGE_RUST", "rust:1.75"),
}


# ---------------------------------------------------------------------------
# Phase 2: Sandbox Feedback Loop — Verification Commands
# ---------------------------------------------------------------------------

_VERIFICATION_COMMANDS: dict[tuple[str, str], list[str]] = {
    # frontend claims
    ("frontend", "FRONTEND_BUILD_READY"): ["cd frontend && npm run build"],
    # devops claims
    ("devops", "DEPLOYMENT_READY"): ["docker compose config > /dev/null"],
}

_PROGRESS_VERIFICATION_COMMANDS: dict[str, list[str]] = {
    "devops": ["docker compose config > /dev/null"],
}

_GLOB_CHARS = set("*?[]")


def _has_glob(path: str) -> bool:
    return any(char in path for char in _GLOB_CHARS)


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _detect_backend_command(workspace: Path) -> list[str] | None:
    backend_dir = workspace / "backend"
    if not backend_dir.exists():
        return None

    if (backend_dir / "pyproject.toml").exists() or (backend_dir / "requirements.txt").exists():
        install_cmd = "pip install -r requirements.txt 2>/dev/null || pip install -e . 2>/dev/null || true"
        if (backend_dir / "src").exists():
            return [f"cd backend && ({install_cmd}) && python -m compileall src"]
        return [f"cd backend && ({install_cmd}) && python -m compileall ."]

    if (backend_dir / "go.mod").exists():
        return ["cd backend && go build ./..."]

    if (backend_dir / "pom.xml").exists():
        return ["cd backend && mvn compile -q"]

    if (backend_dir / "build.gradle").exists() or (backend_dir / "build.gradle.kts").exists():
        return ["cd backend && ./gradlew compileJava 2>/dev/null || gradle compileJava"]

    if (backend_dir / "Cargo.toml").exists():
        return ["cd backend && cargo check"]

    if (backend_dir / "package.json").exists():
        package_json = _load_json_file(backend_dir / "package.json")
        scripts = package_json.get("scripts") if isinstance(package_json, dict) else {}
        if isinstance(scripts, dict):
            if scripts.get("check"):
                return _node_backend_command(backend_dir, "check")
            if scripts.get("build"):
                return _node_backend_command(backend_dir, "build")
        return _node_backend_command(backend_dir, None)

    return None


def _node_pm_command(package_dir: Path) -> tuple[str, str]:
    """Return (install_cmd, run_cmd) for the detected package manager."""
    if (package_dir / "pnpm-lock.yaml").exists():
        return "pnpm install", "pnpm run"
    if (package_dir / "yarn.lock").exists():
        return "yarn install", "yarn run"
    return "npm install", "npm run"


def _node_install_command(directory: str, package_dir: Path) -> str:
    """Return the correct install command based on lockfile presence."""
    install_cmd, _ = _node_pm_command(package_dir)
    if install_cmd == "pnpm install":
        return f"cd {directory} && npm install -g pnpm && {install_cmd}"
    if install_cmd == "yarn install":
        return f"cd {directory} && npm install -g yarn && {install_cmd}"
    return f"cd {directory} && {install_cmd}"


def _node_backend_command(backend_dir: Path, script: str | None) -> list[str]:
    install = _node_install_command("backend", backend_dir)
    _, run_cmd = _node_pm_command(backend_dir)
    if not script:
        return [f"{install} && {run_cmd} build"]
    return [f"{install} && {run_cmd} {script}"]


def _node_frontend_command(frontend_dir: Path, script: str | None) -> list[str]:
    install = _node_install_command("frontend", frontend_dir)
    _, run_cmd = _node_pm_command(frontend_dir)
    if not script:
        return [f"{install} && {run_cmd} build"]
    return [f"{install} && {run_cmd} {script}"]


def _detect_frontend_command(workspace: Path, *, prefer_check: bool) -> list[str] | None:
    frontend_dir = workspace / "frontend"
    package_path = frontend_dir / "package.json"
    if not package_path.exists():
        return None

    package_json = _load_json_file(package_path)
    scripts = package_json.get("scripts") if isinstance(package_json, dict) else {}
    if isinstance(scripts, dict):
        if prefer_check and scripts.get("check"):
            return _node_frontend_command(frontend_dir, "check")
        if scripts.get("build"):
            return _node_frontend_command(frontend_dir, "build")
        if scripts.get("check"):
            return _node_frontend_command(frontend_dir, "check")

    return _node_frontend_command(frontend_dir, None)


def _verification_command_for(
    producer_agent: str,
    claim_type: str,
    *,
    workspace: Path | None = None,
    progress: bool = False,
) -> list[str] | None:
    """Return the shell verification command for this agent + claim type, or None."""
    workspace = workspace or Path(get_workspace())

    if producer_agent == "backend" and claim_type in {"BACKEND_RUNTIME_READY", "BACKEND_API_READY"}:
        return _detect_backend_command(workspace)

    if producer_agent == "frontend":
        if progress or claim_type == "FRONTEND_SOURCE_READY":
            return _detect_frontend_command(workspace, prefer_check=True)
        if claim_type == "FRONTEND_BUILD_READY":
            return _detect_frontend_command(workspace, prefer_check=False)

    if progress:
        return _PROGRESS_VERIFICATION_COMMANDS.get(producer_agent)
    return _VERIFICATION_COMMANDS.get((producer_agent, claim_type))


def _build_tool_available(command: list[str]) -> bool:
    """Check whether the primary build tool for a command is on PATH."""
    if not command:
        return False
    first = command[0]
    # Extract the tool name from something like "cd backend && mvn compile -q"
    for token in first.replace("&&", " ").split():
        if token in {"mvn", "npm", "docker", "pnpm", "yarn", "gradle", "python", "python3", "go"}:
            return shutil.which(token) is not None
    return True  # No known tool — assume shell builtins are fine


def _detect_verification_stack(
    workspace: Path,
    producer_agent: str,
    claim_type: str,
    cmd_str: str,
) -> str | None:
    backend_dir = workspace / "backend"
    frontend_dir = workspace / "frontend"
    lowered = cmd_str.lower()

    # Frontend claims are always Node-based
    if producer_agent == "frontend" or claim_type.startswith("FRONTEND_"):
        return "node"

    # Backend claims: detect by manifest files first, then by command contents
    if backend_dir.joinpath("pyproject.toml").exists() or backend_dir.joinpath("requirements.txt").exists() or "python" in lowered:
        return "python"
    if backend_dir.joinpath("go.mod").exists() or " go " in f" {lowered} ":
        return "go"
    if backend_dir.joinpath("pom.xml").exists() or "mvn" in lowered:
        return "java"
    if backend_dir.joinpath("build.gradle").exists() or backend_dir.joinpath("build.gradle.kts").exists() or "gradle" in lowered:
        return "gradle"
    if backend_dir.joinpath("Cargo.toml").exists() or "cargo" in lowered:
        return "rust"
    if backend_dir.joinpath("package.json").exists() or "npm" in lowered or "yarn" in lowered or "pnpm" in lowered:
        return "node"

    # Fallback: if the project has a frontend but no recognizable backend stack,
    # assume Node (for frontend-only or full-stack projects)
    if frontend_dir.joinpath("package.json").exists():
        return "node"

    return None


async def _ensure_docker_image(image: str, timeout: int = 120) -> bool:
    """Ensure a Docker image is available locally, pulling it if necessary.

    Returns True if the image is available (already present or successfully
    pulled), False if the pull failed or timed out.
    """
    # Fast-path: image already present locally
    check_proc = await asyncio.create_subprocess_exec(
        "docker", "images", "--format", "{{.Repository}}:{{.Tag}}", image,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(check_proc.communicate(), timeout=15)
        if image in stdout.decode(errors="replace"):
            return True
    except asyncio.TimeoutError:
        logger.warning("[_ensure_docker_image] Image check timed out for %s", image)

    # Pull the image with a bounded timeout
    logger.info("[_ensure_docker_image] Pulling Docker image %s ...", image)
    pull_proc = await asyncio.create_subprocess_exec(
        "docker", "pull", image,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(pull_proc.communicate(), timeout=timeout)
        if pull_proc.returncode == 0:
            logger.info("[_ensure_docker_image] %s pulled successfully", image)
            return True
        logger.warning("[_ensure_docker_image] docker pull %s exited with code %s", image, pull_proc.returncode)
        return False
    except asyncio.TimeoutError:
        logger.warning("[_ensure_docker_image] docker pull %s timed out after %ss", image, timeout)
        return False


def _docker_available() -> bool:
    """Return True only if the docker binary exists AND the daemon is reachable."""
    if shutil.which("docker") is None:
        return False
    # When DOCKER_HOST is set the user has a remote/custom daemon — trust the binary check.
    if os.environ.get("DOCKER_HOST"):
        return True
    # Default: Unix socket. Check existence without a subprocess round-trip.
    docker_sock = Path(os.environ.get("DOCKER_SOCKET_PATH", "/var/run/docker.sock"))
    return docker_sock.exists()


def _docker_image_for_stack(stack: str | None) -> str | None:
    if not stack:
        return None
    return VERIFY_DOCKER_IMAGES.get(stack)


def _should_try_docker(
    *,
    local_tool_available: bool,
    stack: str | None,
    producer_agent: str,
    claim_type: str,
) -> bool:
    if producer_agent == "devops" or claim_type == "DEPLOYMENT_READY":
        return False
    if VERIFY_EXECUTOR_MODE == "host":
        return False
    if VERIFY_EXECUTOR_MODE == "docker":
        return True
    return not local_tool_available and stack is not None


def _copy_workspace_for_verification(workspace: Path) -> tempfile.TemporaryDirectory[str]:
    temp_dir = tempfile.TemporaryDirectory(prefix="swarm-verify-")
    snapshot_root = Path(temp_dir.name) / "workspace"
    ignore = shutil.ignore_patterns(
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".svelte-kit",
        "dist",
        "build",
        "node_modules",
        ".venv",
        "venv",
        "*.egg-info",
        ".gradle",
        "target",
    )
    shutil.copytree(workspace, snapshot_root, dirs_exist_ok=True, ignore=ignore)
    return temp_dir


async def _run_verification(
    workspace: Path,
    producer_agent: str,
    claim_type: str,
    timeout: int = 300,
    *,
    build_command: str | None = None,
    progress: bool = False,
) -> dict[str, Any]:
    """Run the build verification command and return structured result.

    If *build_command* is supplied (from evidence metadata) it takes priority
    over the built-in _VERIFICATION_COMMANDS table.  For user-supplied commands
    we log a warning when the primary tool is not on PATH but still attempt
    execution — the user chose the command, so we honour it.

    Returns:
        {"status": "success", "stdout": ..., "stderr": ..., "duration_ms": ...}
        or
        {"status": "failed", "command": ..., "exit_code": ..., "output": ..., "duration_ms": ...}
        or
        {"status": "skipped", "reason": ...}  # when no command is available
    """
    local_tool_available = True
    tool_check_cmd: list[str] | None = None
    if build_command:
        # User-supplied command takes precedence.
        cmd_str = build_command
        # Informational only — do NOT skip if tool is absent.
        tool_check_cmd = [build_command]
        local_tool_available = _build_tool_available(tool_check_cmd)
        if not local_tool_available:
            logger.warning(
                "[_run_verification] Primary tool for custom build_command '%s' not found on PATH; attempting anyway",
                build_command,
            )
    else:
        command = _verification_command_for(
            producer_agent,
            claim_type,
            workspace=workspace,
            progress=progress,
        )
        if command is None:
            return {"status": "skipped", "reason": f"No verification command for {producer_agent}/{claim_type}"}

        local_tool_available = _build_tool_available(command)
        if not local_tool_available:
            logger.warning(
                "[_run_verification] Build tool not available on host for %s/%s; evaluating Docker fallback",
                producer_agent,
                claim_type,
            )

        cmd_str = " && ".join(command) if len(command) > 1 else command[0]
    stack = _detect_verification_stack(workspace, producer_agent, claim_type, cmd_str)
    docker_image = _docker_image_for_stack(stack)
    use_docker = _should_try_docker(
        local_tool_available=local_tool_available,
        stack=stack,
        producer_agent=producer_agent,
        claim_type=claim_type,
    )

    # node_modules is stripped from the Docker snapshot, so Node builds must reinstall deps.
    if use_docker and stack == "node" and "npm install" not in cmd_str:
        parts = cmd_str.split(" && ", 1)
        if len(parts) == 2 and parts[0].startswith("cd "):
            cmd_str = f"{parts[0]} && npm install && {parts[1]}"
        elif not cmd_str.startswith("npm install"):
            cmd_str = f"npm install && {cmd_str}"

    if not local_tool_available and not use_docker:
        reason = f"Build tool not available for {producer_agent}/{claim_type}"
        logger.warning("[_run_verification] %s", reason)
        return {"status": "skipped", "reason": reason}

    if use_docker and not _docker_available():
        reason = (
            f"Verification requires Docker fallback for {producer_agent}/{claim_type}, "
            "but docker is not available on the host"
        )
        logger.warning("[_run_verification] %s", reason)
        return {"status": "skipped", "reason": reason}

    if use_docker and not docker_image:
        reason = f"No Docker verification image configured for {producer_agent}/{claim_type}"
        logger.warning("[_run_verification] %s", reason)
        return {"status": "skipped", "reason": reason}

    execution_label = f"docker:{docker_image}" if use_docker else "host"
    logger.info("[_run_verification] Running via %s: %s", execution_label, cmd_str)

    import time
    start = time.time()
    proc = None
    temp_snapshot: tempfile.TemporaryDirectory[str] | None = None
    container_name: str | None = None

    async def _cleanup_container(name: str) -> None:
        cleanup = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await cleanup.communicate()

    try:
        if use_docker:
            temp_snapshot = _copy_workspace_for_verification(workspace)
            snapshot_path = str((Path(temp_snapshot.name) / "workspace").resolve())
            container_name = f"swarm-verify-{int(time.time())}-{uuid.uuid4().hex[:8]}"

            # Step 0: Ensure the image is available (pull if missing)
            if not await _ensure_docker_image(docker_image, timeout=min(120, timeout)):
                return {
                    "status": "skipped",
                    "command": cmd_str,
                    "reason": f"infrastructure_unavailable: Docker image {docker_image} could not be pulled — claim published without runtime verification",
                    "duration_ms": int((time.time() - start) * 1000),
                    "executor": execution_label,
                }

            # Step 1: Start a long-running container
            create_proc = await asyncio.create_subprocess_exec(
                "docker", "run", "-d",
                "--memory=2g", "--cpus=1.0", "--pids-limit=100",
                "--name", container_name,
                docker_image, "sleep", "300",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(create_proc.communicate(), timeout=60)
            except asyncio.TimeoutError:
                await _cleanup_container(container_name)
                return {
                    "status": "skipped",
                    "command": cmd_str,
                    "reason": f"infrastructure_unavailable: Docker container creation timed out after 60s (image {docker_image}) — claim published without runtime verification",
                    "duration_ms": int((time.time() - start) * 1000),
                    "executor": execution_label,
                }
            if create_proc.returncode != 0:
                await _cleanup_container(container_name)
                return {
                    "status": "skipped",
                    "command": cmd_str,
                    "reason": f"infrastructure_unavailable: Docker container could not be started (image {docker_image}): {stderr.decode(errors='replace')} — claim published without runtime verification",
                    "duration_ms": int((time.time() - start) * 1000),
                    "executor": execution_label,
                }

            # Step 2: Copy snapshot into container (avoids host path sharing issues)
            copy_proc = await asyncio.create_subprocess_exec(
                "docker", "cp", f"{snapshot_path}/.", f"{container_name}:{VERIFY_DOCKER_WORKDIR}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await copy_proc.communicate()

            # Step 3: Execute build inside container.
            # Use -c (not -lc): login shell (-l) resets PATH from /etc/profile,
            # discarding Docker image ENV PATH entries (e.g. /usr/local/go/bin,
            # /usr/local/cargo/bin, JAVA_HOME/bin).  Plain -c inherits the
            # container's ENV, so all language runtimes are found correctly.
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", "--workdir", VERIFY_DOCKER_WORKDIR,
                container_name,
                "/bin/sh", "-c", cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", cmd_str,
                cwd=workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        duration_ms = int((time.time() - start) * 1000)
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        if proc.returncode == 0:
            return {
                "status": "success",
                "exit_code": 0,
                "stdout": stdout,
                "stderr": stderr,
                "duration_ms": duration_ms,
                "executor": execution_label,
            }

        output = stdout + "\n" + stderr
        if len(output) > MAX_VERIFY_OUTPUT_CHARS:
            half = MAX_VERIFY_OUTPUT_CHARS // 2
            output = output[:half] + "\n... [truncated] ...\n" + output[-half:]

        return {
            "status": "failed",
            "command": cmd_str,
            "exit_code": proc.returncode,
            "output": output,
            "duration_ms": duration_ms,
            "executor": execution_label,
        }
    except asyncio.TimeoutError:
        if container_name:
            await _cleanup_container(container_name)
        elif proc is not None:
            proc.kill()
            await proc.wait()
        return {
            "status": "failed",
            "command": cmd_str,
            "exit_code": -1,
            "output": f"Verification timed out after {timeout}s",
            "duration_ms": timeout * 1000,
            "executor": execution_label,
        }
    except Exception as exc:
        if container_name:
            await _cleanup_container(container_name)
        return {
            "status": "failed",
            "command": cmd_str,
            "exit_code": -1,
            "output": str(exc),
            "duration_ms": int((time.time() - start) * 1000),
            "executor": execution_label,
        }
    finally:
        if container_name:
            await _cleanup_container(container_name)
        if temp_snapshot is not None:
            temp_snapshot.cleanup()


def _normalize_evidence_files(workspace: Path, files: list[Any] | tuple[Any, ...] | None) -> list[str]:
    normalized: list[str] = []
    for raw_file in files or []:
        relative_path = str(raw_file).strip()
        if not relative_path:
            continue
        if Path(relative_path).is_absolute():
            normalized.append(relative_path)
            continue
        if _has_glob(relative_path):
            matches = sorted(
                path for path in workspace.glob(relative_path)
                if path.is_file()
            )
            if matches:
                normalized.extend(
                    str(path.relative_to(workspace)).replace("\\", "/")
                    for path in matches
                )
                continue
        normalized.append(relative_path)
    return list(dict.fromkeys(normalized))


def _normalize_claim_evidence(workspace: Path, evidence: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(evidence or {})
    normalized["files"] = _normalize_evidence_files(workspace, normalized.get("files"))
    normalized.setdefault("metadata", {})
    return normalized


def _workspace_for_project(project_id: str) -> Path:
    try:
        return Path(get_workspace())
    except Exception:
        workspace = workspace_tools.WORKSPACE_BASE / project_id
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace


async def verify_and_publish_claim_record(
    *,
    project_id: str,
    producer_agent: str,
    claim_type: str,
    evidence: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
    store: ClaimStore | None = None,
) -> dict[str, Any]:
    """Run build verification, then publish the claim if the build passes.

    If the build fails, return the FULL compiler output so the agent can self-correct.
    This is the Tier 1 sandbox feedback loop.
    """
    workspace = _workspace_for_project(project_id)
    normalized_evidence = _normalize_claim_evidence(workspace, evidence)
    build_command = normalized_evidence.get("metadata", {}).get("build_command") or None
    verification = await _run_verification(
        workspace, producer_agent, claim_type, build_command=build_command
    )
    owns_store = store is None
    claim_store = store or ClaimStore()

    # Graceful degradation: if verification was skipped, publish anyway
    if verification["status"] == "skipped":
        logger.warning(
            "[verify_and_publish_claim] Verification skipped for %s/%s: %s",
            producer_agent, claim_type, verification.get("reason"),
        )
        result = await publish_claim_record(
            project_id=project_id,
            producer_agent=producer_agent,
            claim_type=claim_type,
            evidence=normalized_evidence,
            depends_on=depends_on,
            store=claim_store,
        )
        # publish_claim_record can return todo_incomplete without a "claim" key
        if result.get("status") != "success":
            logger.warning(
                "[verify_and_publish_claim] publish_claim_record returned %s for %s/%s",
                result.get("status"), producer_agent, claim_type,
            )
            if owns_store:
                await claim_store.close()
            return result

        result["verification_skipped"] = True
        result["verification_reason"] = verification.get("reason")
        # Phase 5: Publish verification_skipped event
        await claim_store.publish_claim_event(
            project_id,
            "verification_skipped",
            result["claim"],
            {
                "reason": verification.get("reason"),
                "command": verification.get("command"),
            },
        )
        if owns_store:
            await claim_store.close()
        return result

    # Build failed → return teachable error to agent + publish event
    if verification["status"] == "failed":
        output_preview = verification.get("output", "")[:500]
        # Phase 5: Publish verification_failed event
        dummy_claim = build_claim_payload(
            project_id=project_id,
            claim_type=claim_type,
            producer_agent=producer_agent,
            evidence=normalized_evidence,
        )
        await claim_store.publish_claim_event(
            project_id,
            "verification_failed",
            dummy_claim,
            {
                "command": verification.get("command"),
                "exit_code": verification.get("exit_code"),
                "output_preview": output_preview,
                "duration_ms": verification.get("duration_ms"),
            },
        )
        if owns_store:
            await claim_store.close()
        return {
            "status": "verification_failed",
            "error": f"Build verification failed for {claim_type}",
            "command": verification.get("command"),
            "exit_code": verification.get("exit_code"),
            "output": verification.get("output"),
            "hint": (
                "Fix the compilation/test errors above, then call "
                "verify_and_publish_claim again. Repeat until the build passes."
            ),
        }

    # Build passed → enrich evidence with verification metadata and publish
    enriched_evidence = dict(normalized_evidence)
    enriched_evidence.setdefault("metadata", {})
    enriched_evidence["metadata"]["verification"] = {
        "command": verification.get("command"),
        "exit_code": 0,
        "output_sha256": hashlib.sha256(
            (verification.get("stdout", "") + verification.get("stderr", "")).encode()
        ).hexdigest()[:16],
        "duration_ms": verification.get("duration_ms"),
    }

    result = await publish_claim_record(
        project_id=project_id,
        producer_agent=producer_agent,
        claim_type=claim_type,
        evidence=enriched_evidence,
        depends_on=depends_on,
        store=claim_store,
    )
    if owns_store:
        await claim_store.close()
    return result


@tool("verify_progress")
async def verify_progress(stage: str = "", build_command: str | None = None) -> dict[str, Any]:
    """Run a lightweight compile/check step during implementation without publishing a claim."""
    context = get_claim_context()
    producer_agent = context["agent_name"]
    workspace = Path(get_workspace())
    claim_type = "BACKEND_RUNTIME_READY" if producer_agent == "backend" else "FRONTEND_SOURCE_READY"
    verification = await _run_verification(
        workspace,
        producer_agent,
        claim_type,
        build_command=build_command,
        progress=True,
    )

    if verification["status"] == "failed":
        return {
            "status": "verification_failed",
            "error": f"Progress verification failed for {producer_agent}",
            "command": verification.get("command"),
            "exit_code": verification.get("exit_code"),
            "output": verification.get("output"),
            "stage": stage,
            "hint": "Fix the errors above, then call verify_progress again before continuing.",
        }

    if verification["status"] == "skipped":
        return {
            "status": "skipped",
            "reason": verification.get("reason"),
            "stage": stage,
        }

    return {
        "status": "success",
        "command": verification.get("command"),
        "stdout": verification.get("stdout"),
        "stderr": verification.get("stderr"),
        "duration_ms": verification.get("duration_ms"),
        "stage": stage,
    }


def get_claim_context() -> dict[str, str]:
    """Return the current project and agent context for claim tools."""
    return {
        "project_id": get_project_id(),
        "agent_name": get_agent_name(),
    }


async def _get_current_producer_event_seq(
    project_id: str, producer_agent: str, store: ClaimStore | None = None
) -> int | None:
    """Read the producer's latest event sequence from the claim store."""
    owns_store = store is None
    claim_store = store or ClaimStore()
    try:
        return await claim_store.get_agent_event_seq(project_id, producer_agent)
    finally:
        if owns_store:
            await claim_store.close()


async def _cascade_staleness(
    project_id: str,
    source_claim_type: str,
    reason: str,
    store: ClaimStore,
    visited: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Mark all valid claims that depend on *source_claim_type* as stale.

    Returns the list of claims that were affected.
    """
    if visited is None:
        visited = set()
    if source_claim_type in visited:
        return []
    visited.add(source_claim_type)

    affected: list[dict[str, Any]] = []
    for dependent_type in get_claim_dependents(source_claim_type):
        dependent_claim = await store.get_latest_claim(project_id, dependent_type)
        if dependent_claim and dependent_claim.get("status") == ClaimStatus.VALID.value:
            updated = await store.update_claim_status(
                project_id,
                dependent_claim["id"],
                ClaimStatus.STALE,
                reason=f"Dependency {source_claim_type} became stale: {reason}",
            )
            await store.publish_claim_event(
                project_id,
                "claim_stale",
                updated,
                {"reason": reason, "source_claim_type": source_claim_type},
            )
            affected.append(updated)
            affected.extend(
                await _cascade_staleness(
                    project_id, dependent_type, reason, store, visited
                )
            )
    return affected


async def _check_todos_complete(project_id: str, agent_name: str) -> dict[str, Any]:
    """Verify that all todos for this agent are marked completed.

    Returns a dict with 'status': 'complete' if all done, or 'status': 'incomplete'
    with a list of unfinished todos.
    """
    try:
        todos = await get_agent_todos(project_id, agent_name)
        if not todos:
            return {"status": "complete"}
        incomplete = [
            t.get("content", f"Task {i + 1}")
            for i, t in enumerate(todos)
            if t.get("status") != "completed"
        ]
        if incomplete:
            return {
                "status": "incomplete",
                "error": f"Cannot publish claim with {len(incomplete)} unfinished todo(s)",
                "incomplete_todos": incomplete,
                "hint": "Call update_todo_status for each completed task, then retry.",
            }
    except Exception as exc:
        logger.warning("[_check_todos_complete] Failed to check todos: %s", exc)
    return {"status": "complete"}


async def publish_claim_record(
    *,
    project_id: str,
    producer_agent: str,
    claim_type: str,
    evidence: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
    store: ClaimStore | None = None,
) -> dict[str, Any]:
    owns_store = store is None
    claim_store = store or ClaimStore()
    try:
        # Enforce: all todos must be completed before publishing a claim.
        todo_check = await _check_todos_complete(project_id, producer_agent)
        if todo_check.get("status") != "complete":
            logger.warning(
                "[publish_claim] Blocked %s from publishing %s: %s",
                producer_agent, claim_type, todo_check.get("error"),
            )
            if owns_store:
                await claim_store.close()
            return {
                "status": "todo_incomplete",
                **todo_check,
            }

        # Capture the producer's current event sequence at claim time.
        producer_event_seq = await claim_store.get_agent_event_seq(project_id, producer_agent)

        # Phase 1: Snapshot workspace before claiming
        git_hash = snapshot_workspace(project_id, f"{claim_type}-{producer_agent}")

        # Enrich evidence with workspace revision
        enriched_evidence = _normalize_claim_evidence(_workspace_for_project(project_id), evidence)
        if git_hash:
            enriched_evidence.setdefault("metadata", {})
            enriched_evidence["metadata"]["workspace_revision"] = git_hash

        claim = build_claim_payload(
            project_id=project_id,
            claim_type=claim_type,
            producer_agent=producer_agent,
            evidence=enriched_evidence,
            depends_on=depends_on,
            producer_event_seq=producer_event_seq,
            workspace_revision=git_hash,
        )

        # Task 7.3: Mark any previous claim of the same type stale before saving
        # the new one.
        previous = await claim_store.get_latest_claim(project_id, claim_type)
        if previous and previous.get("id") != claim["id"]:
            await claim_store.update_claim_status(
                project_id,
                previous["id"],
                ClaimStatus.STALE,
                reason="Superseded by newer claim of the same type",
            )
            await claim_store.publish_claim_event(
                project_id,
                "claim_stale",
                previous,
                {
                    "reason": "Superseded by newer claim of the same type",
                    "new_claim_id": claim["id"],
                },
            )
            await _cascade_staleness(
                project_id,
                claim_type,
                "Superseded by newer claim",
                claim_store,
            )

        await claim_store.save_claim(project_id, claim)
        event = await claim_store.publish_claim_event(project_id, "claim_published", claim)
        logger.info(
            "[publish_claim] %s published %s for project %s (seq=%s)",
            producer_agent,
            claim_type,
            project_id,
            producer_event_seq,
        )
        return {"status": "success", "claim": claim, "event": event}
    finally:
        if owns_store:
            await claim_store.close()


async def _get_selected_agents(project_id: str, claim_store: ClaimStore) -> list[str]:
    """Read selected agents from the project state stored in Redis."""
    try:
        if claim_store._redis is not None:
            state_raw = await claim_store._redis.get(f"project:{project_id}:state")
            if state_raw:
                state = json.loads(state_raw)
                return state.get("selected_agents", [])
    except Exception:
        pass
    return []


async def wait_for_claim_record(
    *,
    project_id: str,
    claim_type: str,
    timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
    poll_interval_seconds: float = DEFAULT_WAIT_POLL_SECONDS,
    store: ClaimStore | None = None,
) -> dict[str, Any]:
    owns_store = store is None
    claim_store = store or ClaimStore()
    deadline = asyncio.get_running_loop().time() + max(0, timeout_seconds)
    terminal_blocking_statuses = {
        ClaimStatus.REVOKED.value,
    }
    latest_nonvalid_claim: dict[str, Any] | None = None

    try:
        # Check if the producer agent is scheduled in the current run.
        # If not, return immediately — no need to wait for a claim that
        # will never be published in this swarm execution.
        producer = get_claim_producer(claim_type)
        if producer:
            selected_agents = await _get_selected_agents(project_id, claim_store)
            if selected_agents and producer not in selected_agents:
                claim = await claim_store.get_latest_claim(project_id, claim_type)
                if claim and claim.get("status") == ClaimStatus.VALID.value:
                    return {
                        "status": "success",
                        "claim": claim,
                        "source": "existing",
                        "hint": f"{producer} is not scheduled — using existing valid claim.",
                    }
                return {
                    "status": "skipped",
                    "error": f"{producer} is not scheduled in this run — no new {claim_type} will be published",
                    "hint": "Proceed with your work using existing workspace state.",
                    "claim_type": claim_type,
                }

        while True:
            claim = await claim_store.get_latest_claim(project_id, claim_type)
            if claim:
                status = str(claim.get("status", ""))
                if status == ClaimStatus.VALID.value:
                    return {"status": "success", "claim": claim}
                latest_nonvalid_claim = claim
                if status in terminal_blocking_statuses:
                    return {
                        "status": "error",
                        "error": f"Claim {claim_type} is {status}",
                        "claim": claim,
                    }

            now = asyncio.get_running_loop().time()
            if now >= deadline:
                if latest_nonvalid_claim:
                    latest_status = str(latest_nonvalid_claim.get("status", "missing"))
                    return {
                        "status": "error",
                        "error": f"Timed out waiting for valid claim {claim_type}; latest status is {latest_status}",
                        "claim": latest_nonvalid_claim,
                        "claim_type": claim_type,
                    }
                return {
                    "status": "error",
                    "error": f"Timed out waiting for valid claim {claim_type}",
                    "claim_type": claim_type,
                }
            await asyncio.sleep(min(poll_interval_seconds, deadline - now))
    finally:
        if owns_store:
            await claim_store.close()


async def validate_dependencies(
    project_id: str,
    claim: dict[str, Any],
    *,
    store: ClaimStore | None = None,
) -> dict[str, Any]:
    owns_store = store is None
    claim_store = store or ClaimStore()
    errors: list[str] = []
    warnings: list[str] = []
    dependencies: list[dict[str, Any]] = []

    try:
        for dependency_type in claim.get("depends_on") or []:
            dependency = await claim_store.get_latest_claim(project_id, str(dependency_type))
            if not dependency:
                errors.append(f"Missing dependency claim: {dependency_type}")
                dependencies.append({
                    "claim_type": dependency_type,
                    "status": "missing",
                    "claim_id": None,
                })
                continue

            dependency_status = str(dependency.get("status", ""))
            dependencies.append({
                "claim_type": dependency_type,
                "status": dependency_status,
                "claim_id": dependency.get("id"),
            })
            if dependency_status != ClaimStatus.VALID.value:
                errors.append(
                    f"Dependency {dependency_type} is {dependency_status}; expected valid"
                )

        return {
            "status": "valid" if not errors else "invalid",
            "validated_at": claim_now_iso(),
            "errors": errors,
            "warnings": warnings,
            "dependencies": dependencies,
        }
    finally:
        if owns_store:
            await claim_store.close()


async def validate_claim(
    project_id: str,
    claim_id: str,
    *,
    store: ClaimStore | None = None,
    workspace: str | None = None,
) -> dict[str, Any]:
    """Validate a claim's dependencies and workspace evidence without LLM involvement."""
    owns_store = store is None
    claim_store = store or ClaimStore()
    try:
        claim = await claim_store.get_claim(project_id, claim_id)

        dependency_validation = await validate_dependencies(project_id, claim, store=claim_store)
        workspace_path = workspace or get_workspace()
        evidence_validation = validate_claim_evidence(workspace_path, claim)

        # Task 7.1: Detect post-claim producer activity.
        # Event-seq is used as a coarse warning signal; evidence drift
        # (file mtime vs claim created_at) is the authoritative staleness trigger.
        stored_seq = claim.get("producer_event_seq")
        current_seq = await claim_store.get_agent_event_seq(
            project_id, claim["producer_agent"]
        )
        event_seq_warnings: list[str] = []
        if (
            stored_seq is not None
            and current_seq is not None
            and (current_seq - stored_seq) > EVENT_SEQ_TOLERANCE
        ):
            event_seq_warnings.append(
                f"Producer activity detected after claim "
                f"(seq {stored_seq} -> {current_seq})"
            )

        # Inject event-seq warnings into the merged validation.
        if event_seq_warnings:
            evidence_validation.setdefault("warnings", [])
            evidence_validation["warnings"].extend(event_seq_warnings)

        validation = merge_validation_results(dependency_validation, evidence_validation)

        # If evidence drift was detected, mark the claim stale and cascade.
        drift_errors = [
            e for e in (validation.get("errors") or [])
            if "Evidence drift detected" in e
        ]
        if drift_errors:
            stale_reason = drift_errors[0]
            updated = await claim_store.update_claim_status(
                project_id,
                claim_id,
                ClaimStatus.STALE,
                reason=stale_reason,
            )
            await claim_store.publish_claim_event(
                project_id, "claim_stale", updated, {"reason": stale_reason}
            )
            await _cascade_staleness(
                project_id, claim["claim_type"], stale_reason, claim_store
            )
            return {
                "status": "stale",
                "claim": updated,
                "validation": {
                    "status": "stale",
                    "validated_at": claim_now_iso(),
                    "errors": drift_errors,
                    "warnings": validation.get("warnings") or [],
                },
            }

        next_status = (
            ClaimStatus.VALID.value
            if validation["status"] == "valid"
            else ClaimStatus.INVALID.value
        )
        updated = await claim_store.update_claim_status(
            project_id,
            claim_id,
            next_status,
            validation,
        )
        await claim_store.publish_claim_event(project_id, "claim_validated", updated)

        # If the claim ended up stale (should not happen via this path, but be safe),
        # cascade to dependents.
        if updated.get("status") == ClaimStatus.STALE.value:
            await _cascade_staleness(
                project_id,
                claim["claim_type"],
                "Validation resulted in stale status",
                claim_store,
            )

        return {"status": validation["status"], "claim": updated, "validation": validation}
    except ClaimNotFoundError as exc:
        return {"status": "error", "error": str(exc), "claim_id": claim_id}
    finally:
        if owns_store:
            await claim_store.close()


async def revoke_claim(
    project_id: str,
    claim_id: str,
    reason: str,
    *,
    store: ClaimStore | None = None,
) -> dict[str, Any]:
    owns_store = store is None
    claim_store = store or ClaimStore()
    try:
        claim = await claim_store.get_claim(project_id, claim_id)
        validation = {
            "status": "revoked",
            "validated_at": claim_now_iso(),
            "errors": [reason] if reason else [],
            "warnings": [],
        }
        updated = await claim_store.update_claim_status(
            project_id,
            claim_id,
            ClaimStatus.REVOKED,
            validation,
        )
        await claim_store.publish_claim_event(
            project_id,
            "claim_revoked",
            updated,
            {"reason": reason},
        )
        # Task 7.2: Cascade staleness to all dependent claims.
        await _cascade_staleness(
            project_id,
            claim["claim_type"],
            reason or "Claim revoked",
            claim_store,
        )
        return {"status": "success", "claim": updated}
    except ClaimNotFoundError as exc:
        return {"status": "error", "error": str(exc), "claim_id": claim_id}
    finally:
        if owns_store:
            await claim_store.close()


@tool("publish_claim")
async def publish_claim(
    claim_type: str,
    evidence: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    """Publish an evidence-backed readiness claim for the current agent.

    Args:
        claim_type: Readiness claim type, e.g. BACKEND_API_READY.
        evidence: Optional evidence object with files, ports, commands, metadata.
        depends_on: Optional list of claim types that must be valid before this claim validates.
    """
    context = get_claim_context()

    # Enforce build verification for build/runtime claims so agents cannot
    # bypass the sandbox by calling publish_claim instead of verify_and_publish_claim.
    BUILD_CLAIMS = {
        ClaimType.FRONTEND_BUILD_READY.value,
        ClaimType.BACKEND_RUNTIME_READY.value,
        ClaimType.BACKEND_API_READY.value,
    }
    if claim_type in BUILD_CLAIMS:
        return await verify_and_publish_claim_record(
            project_id=context["project_id"],
            producer_agent=context["agent_name"],
            claim_type=claim_type,
            evidence=evidence,
            depends_on=depends_on,
        )

    return await publish_claim_record(
        project_id=context["project_id"],
        producer_agent=context["agent_name"],
        claim_type=claim_type,
        evidence=evidence,
        depends_on=depends_on,
    )


@tool("verify_and_publish_claim")
async def verify_and_publish_claim(
    claim_type: str,
    evidence: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    """Verify workspace state by running the actual build/test, then publish claim.

    If the build fails, the FULL compiler output is returned so the agent can fix it.
    The agent should call this tool repeatedly until the build passes.

    Args:
        claim_type: Readiness claim type, e.g. BACKEND_API_READY.
        evidence: Optional evidence object with files, ports, commands, metadata.
        depends_on: Optional list of claim types that must be valid before this claim validates.
    """
    context = get_claim_context()
    return await verify_and_publish_claim_record(
        project_id=context["project_id"],
        producer_agent=context["agent_name"],
        claim_type=claim_type,
        evidence=evidence,
        depends_on=depends_on,
    )


@tool("wait_for_claim")
async def wait_for_claim(
    claim_type: str,
    timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Wait until the latest claim of a type is valid, or fail if it is invalid.

    Args:
        claim_type: Readiness claim type to wait for, e.g. BACKEND_API_READY.
        timeout_seconds: Maximum seconds to wait before returning an error.
    """
    context = get_claim_context()
    return await wait_for_claim_record(
        project_id=context["project_id"],
        claim_type=claim_type,
        timeout_seconds=timeout_seconds,
    )


async def verify_claim_adversarially_record(
    project_id: str,
    claim_id: str,
    *,
    store: ClaimStore | None = None,
) -> dict[str, Any]:
    """Coordinator-owned adversarial verification: re-derive evidence from workspace.

    Loads the claim from the store, inspects the workspace independently,
    and returns a validation result.
    """
    owns_store = store is None
    claim_store = store or ClaimStore()
    try:
        claim = await claim_store.get_claim(project_id, claim_id)
        workspace = get_workspace()
        from ..claim_validators import verify_claim_adversarially
        result = verify_claim_adversarially(workspace, claim)
        return {"status": result["status"], "claim": claim, "validation": result}
    except ClaimNotFoundError as exc:
        return {"status": "error", "error": str(exc), "claim_id": claim_id}
    finally:
        if owns_store:
            await claim_store.close()


__all__ = [
    "publish_claim",
    "wait_for_claim",
    "verify_and_publish_claim",
    "verify_progress",
    "publish_claim_record",
    "wait_for_claim_record",
    "verify_and_publish_claim_record",
    "verify_claim_adversarially_record",
    "validate_dependencies",
    "validate_claim",
    "revoke_claim",
    "get_claim_context",
    "_cascade_staleness",
    "_get_current_producer_event_seq",
    "_verification_command_for",
    "_run_verification",
]
