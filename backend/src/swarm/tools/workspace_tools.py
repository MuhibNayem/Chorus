import os
import logging
import zipfile
import asyncio
import shutil
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
from langchain_core.tools import tool
from contextvars import ContextVar

logger = logging.getLogger("tools")

WORKSPACE_BASE = "/tmp/deepseek/workspaces"
WORKSPACE_MAX_AGE_HOURS = int(os.environ.get("WORKSPACE_MAX_AGE_HOURS", "24"))

# Thread-safe project context
_project_id_var: ContextVar[Optional[str]] = ContextVar("project_id", default=None)


def _validate_workspace_path(workspace: Path, relative_path: str) -> Path:
    """Ensure a relative path stays within the workspace. Blocks path traversal attacks."""
    # Normalize the path — resolve '..' and symlinks
    full_path = (workspace / relative_path).resolve(strict=False)
    workspace_resolved = workspace.resolve(strict=False)

    # Check that the resolved path is inside (or equal to) the workspace
    try:
        full_path.relative_to(workspace_resolved)
    except ValueError:
        raise PermissionError(f"Path escapes workspace: {relative_path}")

    return full_path


def cleanup_old_workspaces():
    """Delete workspace directories older than WORKSPACE_MAX_AGE_HOURS."""
    base = Path(WORKSPACE_BASE)
    if not base.exists():
        return

    cutoff = datetime.now() - timedelta(hours=WORKSPACE_MAX_AGE_HOURS)
    deleted = 0

    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime)
            if mtime < cutoff:
                shutil.rmtree(entry)
                deleted += 1
                logger.info(f"[cleanup] Deleted old workspace: {entry.name} (mtime: {mtime.isoformat()})")
        except Exception as e:
            logger.warning(f"[cleanup] Failed to delete {entry}: {e}")

    if deleted:
        logger.info(f"[cleanup] Deleted {deleted} old workspace(s)")


def _run_async(coro):
    """Run async coroutine properly in any thread context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def set_project_context(project_id: str):
    _project_id_var.set(project_id)


def get_project_id() -> str:
    pid = _project_id_var.get()
    if not pid:
        raise ValueError("Project context not set")
    return pid


def get_workspace() -> Path:
    workspace = Path(WORKSPACE_BASE) / get_project_id()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def get_storage():
    """Get MinIO storage instance."""
    from src.storage.minio_client import MinioStorage
    return MinioStorage()


@tool("create_project_zip")
def create_project_zip() -> Dict[str, Any]:
    """Create a ZIP archive of the entire project workspace.

    Returns:
        Path to the created ZIP file and its size
    """
    try:
        workspace = get_workspace()
        zip_path = workspace / f"{get_project_id()}.zip"

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_path in workspace.rglob("*"):
                if file_path.is_file() and not file_path.name.endswith(".zip"):
                    arcname = file_path.relative_to(workspace)
                    zf.write(file_path, arcname)

        zip_size = zip_path.stat().st_size
        logger.info(f"[create_project_zip] Created {zip_path} ({zip_size} bytes)")

        return {
            "status": "success",
            "zip_path": str(zip_path),
            "size_bytes": zip_size,
        }
    except Exception as e:
        logger.error(f"[create_project_zip] Failed: {e}")
        return {"status": "error", "error": str(e)}


@tool("upload_project_to_storage")
def upload_project_to_storage() -> Dict[str, Any]:
    """Upload the project ZIP to MinIO storage.

    Returns:
        MinIO object path and presigned download URL
    """
    try:
        workspace = get_workspace()
        zip_path = workspace / f"{get_project_id()}.zip"

        if not zip_path.exists():
            return {"status": "error", "error": "ZIP file not found. Run create_project_zip first."}

        storage = get_storage()
        _run_async(storage.connect())

        object_name = f"projects/{get_project_id()}/{get_project_id()}.zip"
        result = _run_async(storage.upload_file(
            object_name,
            zip_path,
            content_type="application/zip",
        ))

        if result.get("status") == "success":
            url = _run_async(storage.get_presigned_url(object_name, expires_seconds=3600))
            logger.info(f"[upload_project_to_storage] Uploaded, URL: {url[:50]}...")

            return {
                "status": "success",
                "object_name": object_name,
                "download_url": url,
                "size_bytes": zip_path.stat().st_size,
            }
        else:
            return result

    except Exception as e:
        logger.error(f"[upload_project_to_storage] Failed: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}


@tool("get_project_download_url")
def get_project_download_url(expires_seconds: int = 3600) -> Dict[str, Any]:
    """Get a presigned URL to download the project ZIP from MinIO.

    Args:
        expires_seconds: URL expiration time (default 3600)
    """
    try:
        storage = get_storage()
        _run_async(storage.connect())

        object_name = f"projects/{get_project_id()}/{get_project_id()}.zip"

        if not _run_async(storage.object_exists(object_name)):
            return {"status": "error", "error": "Project not found in storage. Run upload_project_to_storage first."}

        url = _run_async(storage.get_presigned_url(object_name, expires_seconds))
        logger.info(f"[get_project_download_url] Generated URL: {url[:50]}...")

        return {
            "status": "success",
            "download_url": url,
            "expires_seconds": expires_seconds,
        }
    except Exception as e:
        logger.error(f"[get_project_download_url] Failed: {e}")
        return {"status": "error", "error": str(e)}


@tool("build_docker_image")
def build_docker_image(project_name: str) -> Dict[str, Any]:
    """Build a Docker image for the project.

    Args:
        project_name: Name of the project (used as image name)

    Returns:
        Status and image name/tag
    """
    import subprocess
    try:
        workspace = get_workspace()
        backend_path = workspace / project_name

        if not (backend_path / "Dockerfile").exists():
            return {"status": "error", "error": "Dockerfile not found"}

        image_name = f"deepseek-{project_name}:latest"

        result = subprocess.run(
            ["docker", "build", "-t", image_name, "-f", str(backend_path / "Dockerfile"), str(backend_path)],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            logger.info(f"[build_docker_image] Built {image_name}")
            return {
                "status": "success",
                "image_name": image_name,
                "message": "Docker image built successfully",
            }
        else:
            logger.error(f"[build_docker_image] Failed: {result.stderr}")
            return {"status": "error", "error": result.stderr}
    except subprocess.TimeoutExpired:
        logger.error("[build_docker_image] Timeout during docker build")
        return {"status": "error", "error": "Docker build timed out"}
    except FileNotFoundError:
        logger.error("[build_docker_image] Docker not found")
        return {"status": "error", "error": "Docker not installed or not in PATH"}
    except Exception as e:
        logger.error(f"[build_docker_image] Failed: {e}")
        return {"status": "error", "error": str(e)}


@tool("run_docker_container")
def run_docker_container(image_name: str, port: int = 8080) -> Dict[str, Any]:
    """Run a Docker container from the built image.

    Args:
        image_name: Name of the Docker image to run
        port: Host port to expose (default 8080)

    Returns:
        Container ID and status
    """
    import subprocess
    try:
        container_id = subprocess.run(
            ["docker", "run", "-d", "-p", f"{port}:8080", "--name", f"deepseek-{image_name.replace(':', '-')}", image_name],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()

        if container_id:
            logger.info(f"[run_docker_container] Started {container_id}")
            return {
                "status": "success",
                "container_id": container_id,
                "port": port,
            }
        else:
            return {"status": "error", "error": "Failed to start container"}
    except Exception as e:
        logger.error(f"[run_docker_container] Failed: {e}")
        return {"status": "error", "error": str(e)}


@tool("write_file")
def write_file(file_path: str, content: str) -> Dict[str, Any]:
    """Write content to a file in the project workspace.

    Args:
        file_path: Relative path from workspace root
        content: The content to write
    """
    try:
        workspace = get_workspace()
        full_path = _validate_workspace_path(workspace, file_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
        logger.info(f"[write_file] Created: {file_path}")
        return {
            "status": "success",
            "file_path": file_path,
            "bytes_written": len(content),
        }
    except PermissionError as e:
        logger.error(f"[write_file] Blocked path traversal: {file_path}")
        return {"status": "error", "file_path": file_path, "error": str(e)}
    except Exception as e:
        logger.error(f"[write_file] Failed to write {file_path}: {e}")
        return {"status": "error", "file_path": file_path, "error": str(e)}


@tool("read_file")
def read_file(file_path: str) -> Dict[str, Any]:
    """Read content from a file in the project workspace.

    Args:
        file_path: Relative path from workspace root
    """
    try:
        workspace = get_workspace()
        full_path = _validate_workspace_path(workspace, file_path)
        if not full_path.exists():
            return {"status": "error", "file_path": file_path, "error": "File not found"}
        content = full_path.read_text()
        logger.info(f"[read_file] Read: {file_path} ({len(content)} bytes)")
        return {
            "status": "success",
            "file_path": file_path,
            "content": content,
        }
    except PermissionError as e:
        logger.error(f"[read_file] Blocked path traversal: {file_path}")
        return {"status": "error", "file_path": file_path, "error": str(e)}
    except Exception as e:
        logger.error(f"[read_file] Failed to read {file_path}: {e}")
        return {"status": "error", "file_path": file_path, "error": str(e)}


@tool("list_files")
def list_files(directory: str = "") -> Dict[str, Any]:
    """List all files in a directory recursively.

    Args:
        directory: Relative path from workspace root (empty = entire workspace)
    """
    try:
        workspace = get_workspace()
        dir_path = _validate_workspace_path(workspace, directory) if directory else workspace
        if not dir_path.exists():
            return {"status": "error", "directory": directory, "error": "Directory not found"}

        files = []
        for f in dir_path.rglob("*"):
            if f.is_file():
                rel_path = f.relative_to(workspace)
                files.append(str(rel_path))

        logger.info(f"[list_files] Listed {len(files)} files in {directory or 'workspace'}")
        return {
            "status": "success",
            "directory": directory or "workspace",
            "files": files,
        }
    except PermissionError as e:
        logger.error(f"[list_files] Blocked path traversal: {directory}")
        return {"status": "error", "directory": directory, "error": str(e)}
    except Exception as e:
        logger.error(f"[list_files] Failed to list {directory}: {e}")
        return {"status": "error", "directory": directory, "error": str(e)}


@tool("execute_command")
def execute_command(command: str, timeout: int = 60) -> Dict[str, Any]:
    """Execute a shell command in the project workspace (sandboxed via bubblewrap).

    Args:
        command: The shell command to execute
        timeout: Maximum execution time in seconds (default 60)
    """
    try:
        workspace = get_workspace()
        logger.info(f"[execute_command] Running: {command}")

        from .sandbox import Sandbox
        sandbox = Sandbox(workspace)
        result = sandbox.execute(command, timeout)

        # Truncate stdout/stderr to avoid flooding the LLM context
        if result.get("status") == "success" or result.get("status") == "failed":
            result["stdout"] = result.get("stdout", "")[:5000]
            result["stderr"] = result.get("stderr", "")[:5000]

        return result
    except Exception as e:
        logger.error(f"[execute_command] Failed: {command} - {e}")
        return {"status": "error", "command": command, "error": str(e)}


@tool("create_directory")
def create_directory(directory: str) -> Dict[str, Any]:
    """Create a directory in the project workspace.

    Args:
        directory: Relative path from workspace root
    """
    try:
        workspace = get_workspace()
        dir_path = _validate_workspace_path(workspace, directory)
        dir_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"[create_directory] Created: {directory}")
        return {"status": "success", "directory": directory}
    except PermissionError as e:
        logger.error(f"[create_directory] Blocked path traversal: {directory}")
        return {"status": "error", "directory": directory, "error": str(e)}
    except Exception as e:
        logger.error(f"[create_directory] Failed to create {directory}: {e}")
        return {"status": "error", "directory": directory, "error": str(e)}


@tool("delete_file")
def delete_file(file_path: str) -> Dict[str, Any]:
    """Delete a file from the project workspace.

    Args:
        file_path: Relative path from workspace root
    """
    try:
        workspace = get_workspace()
        full_path = _validate_workspace_path(workspace, file_path)
        if full_path.exists():
            full_path.unlink()
            logger.info(f"[delete_file] Deleted: {file_path}")
            return {"status": "success", "file_path": file_path}
        return {"status": "error", "file_path": file_path, "error": "File not found"}
    except PermissionError as e:
        logger.error(f"[delete_file] Blocked path traversal: {file_path}")
        return {"status": "error", "file_path": file_path, "error": str(e)}
    except Exception as e:
        logger.error(f"[delete_file] Failed to delete {file_path}: {e}")
        return {"status": "error", "file_path": file_path, "error": str(e)}


def get_generic_tools(project_id: str):
    """Get all generic filesystem tools for an agent."""
    set_project_context(project_id)
    return [
        write_file,
        read_file,
        list_files,
        execute_command,
        create_directory,
        delete_file,
    ]


TOOLS_REGISTRY = {
    "write_file": write_file,
    "read_file": read_file,
    "list_files": list_files,
    "execute_command": execute_command,
    "create_directory": create_directory,
    "delete_file": delete_file,
    "create_project_zip": create_project_zip,
    "upload_project_to_storage": upload_project_to_storage,
    "get_project_download_url": get_project_download_url,
    "build_docker_image": build_docker_image,
    "run_docker_container": run_docker_container,
}