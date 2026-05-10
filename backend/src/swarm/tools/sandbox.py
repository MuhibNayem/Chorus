import asyncio
import subprocess
import logging
import os
import platform
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger("sandbox")

class Sandbox:
    """
    Provides a secure execution environment for agents using OS-level sandboxing.
    Uses bubblewrap (bwrap) on Linux and Seatbelt (sandbox-exec) on macOS.
    """
    
    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path
        self.system = platform.system()
        self.workspace_path.mkdir(parents=True, exist_ok=True)

    async def execute(self, command: str, timeout: int = 300) -> Dict[str, Any]:
        """Execute a command within the sandbox."""
        if self.system == "Linux":
            return await self._execute_bwrap(command, timeout)
        elif self.system == "Darwin":
            return await self._execute_seatbelt(command, timeout)
        else:
            # Fallback for other systems
            return await self._execute_fallback(command, timeout)

    async def _execute_bwrap(self, command: str, timeout: int) -> Dict[str, Any]:
        """Execute using bubblewrap on Linux."""
        bwrap_cmd = [
            "bwrap",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--bind", str(self.workspace_path), str(self.workspace_path),
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--chdir", str(self.workspace_path),
            "--unshare-all",
            "--share-net",
            "bash", "-c", command
        ]
        
        if os.path.exists("/lib64"):
            bwrap_cmd.insert(7, "--ro-bind")
            bwrap_cmd.insert(8, "/lib64")
            bwrap_cmd.insert(9, "/lib64")

        try:
            # Check if bwrap actually works
            test_res = subprocess.run(["bwrap", "--version"], capture_output=True)
            if test_res.returncode != 0:
                raise Exception("bwrap not functional")
            
            logger.info(f"[Sandbox] Running bwrap: {command}")
            res = await self._run_subprocess(bwrap_cmd, timeout)
            if "Permission denied" in res.get("stderr", "") and "uid map" in res.get("stderr", ""):
                logger.warning("[Sandbox] bwrap failed with permission error, falling back to direct execution")
                return await self._execute_fallback(command, timeout)
            return res
        except Exception as e:
            logger.warning(f"[Sandbox] bwrap failed ({e}), falling back to direct execution")
            return await self._execute_fallback(command, timeout)

    async def _execute_seatbelt(self, command: str, timeout: int) -> Dict[str, Any]:
        """Execute using sandbox-exec on macOS."""
        # This is a simplified profile
        profile = f"""
(version 1)
(allow default)
(deny file-write*
    (subpath "/")
)
(allow file-write*
    (subpath "{self.workspace_path}")
    (subpath "/private/var")
    (subpath "/tmp")
)
"""
        profile_path = self.workspace_path / ".sandbox.sb"
        profile_path.write_text(profile)
        
        seatbelt_cmd = [
            "sandbox-exec", "-f", str(profile_path),
            "bash", "-c", f"cd {self.workspace_path} && {command}"
        ]
        
        logger.info(f"[Sandbox] Running seatbelt: {command}")
        return await self._run_subprocess(seatbelt_cmd, timeout)

    async def _execute_fallback(self, command: str, timeout: int) -> Dict[str, Any]:
        """Fallback execution without sandbox."""
        logger.warning(f"[Sandbox] No supported sandbox for {self.system}, falling back to direct execution")
        return await self._run_subprocess(["bash", "-c", f"cd {self.workspace_path} && {command}"], timeout)

    async def _run_subprocess(self, cmd_list: List[str], timeout: int) -> Dict[str, Any]:
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
                return {
                    "status": "success" if process.returncode == 0 else "failed",
                    "returncode": process.returncode,
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace")
                }
            except asyncio.TimeoutError:
                process.kill()
                return {"status": "error", "error": "Timeout exceeded"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
