"""Backend-frontend contract verification utility.

Provides automated cross-checks between backend API routes and frontend
service calls to detect contract mismatches before agents are spawned.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any

try:
    from langchain_core.tools import tool
except ImportError:
    def tool(name=None):  # type: ignore[no-redef]
        def decorator(func):
            func.__name__ = name or func.__name__
            return func
        return decorator


def _extract_go_routes(main_go_path: Path) -> tuple[str, List[str]]:
    """Extract route prefix and endpoints from a Go main.go file."""
    prefix = "/api"
    endpoints: List[str] = []

    if not main_go_path.exists():
        return prefix, endpoints

    content = main_go_path.read_text()

    # Find route group prefix, e.g. r.Group("/api/v1")
    group_match = re.search(r'\.Group\("([^"]+)"\)', content)
    if group_match:
        prefix = group_match.group(1)

    # Find route registrations: .GET("/path", ...), .POST("/path", ...)
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        pattern = re.compile(rf'\.{method}\s*\(\s*"([^"]+)"')
        for m in pattern.finditer(content):
            endpoints.append(f"{method} {m.group(1)}")

    return prefix, endpoints


def _extract_ts_api_calls(services_dir: Path) -> Dict[str, List[str]]:
    """Extract API endpoint calls from TypeScript service files."""
    calls: Dict[str, List[str]] = {}

    if not services_dir.exists():
        return calls

    for ts_file in services_dir.glob("*.ts"):
        content = ts_file.read_text()
        file_calls: List[str] = []

        # Match api.get('/path'), api.post('/path', ...), etc.
        pattern = re.compile(
            r'api\.(get|post|put|patch|delete)\s*\(\s*[`\'"]([^`\'"]+)[`\'"]'
        )
        for m in pattern.finditer(content):
            method = m.group(1).upper()
            path = m.group(2)
            file_calls.append(f"{method} {path}")

        # Match raw fetch('/api/path')
        fetch_pattern = re.compile(
            r'fetch\s*\(\s*[`\'"]([^`\'"]+)[`\'"]\s*\)'
        )
        for m in fetch_pattern.finditer(content):
            url = m.group(1)
            if url.startswith("/api"):
                file_calls.append(f"GET {url}")

        if file_calls:
            calls[ts_file.name] = file_calls

    return calls


def _extract_api_base_url(base_ts_path: Path) -> Optional[str]:
    """Extract API_BASE_URL from frontend base.ts."""
    if not base_ts_path.exists():
        return None

    content = base_ts_path.read_text()
    match = re.search(r'API_BASE_URL\s*=\s*["\']([^"\']+)["\']', content)
    return match.group(1) if match else None


def _check_response_wrapper(base_ts_path: Path) -> Optional[str]:
    """Check if frontend ApiClient unwraps backend response wrapper."""
    if not base_ts_path.exists():
        return None

    content = base_ts_path.read_text()
    has_unwrap = "'success' in body" in content or "body.data" in content or "body?.data" in content
    if has_unwrap:
        return None

    # Check if it returns raw response.json() without unwrapping
    if "return response.json()" in content and "body" not in content:
        return (
            "Frontend ApiClient returns raw response.json() without unwrapping. "
            "If backend wraps responses in {success, data, message}, all API calls will fail."
        )
    return None


def verify_contract(workspace_path: Path) -> Dict[str, Any]:
    """Run full backend-frontend contract verification.

    Returns a dict with:
    - status: "ok" | "warning" | "error"
    - issues: list of issue strings
    - details: dict with endpoint comparison, base_url, etc.
    """
    issues: List[str] = []
    details: Dict[str, Any] = {}

    backend_main = workspace_path / "backend" / "cmd" / "server" / "main.go"
    if not backend_main.exists():
        backend_main = workspace_path / "backend" / "main.go"
    if not backend_main.exists():
        backend_main = workspace_path / "backend" / "src" / "main.py"

    frontend_base = workspace_path / "frontend" / "src" / "lib" / "services" / "base.ts"
    frontend_services = workspace_path / "frontend" / "src" / "lib" / "services"

    # 1. API base URL comparison
    backend_prefix = "/api"
    if backend_main.exists():
        backend_prefix, backend_routes = _extract_go_routes(backend_main)
        details["backend_prefix"] = backend_prefix
        details["backend_routes"] = backend_routes
    else:
        issues.append("Backend main file not found — cannot verify routes")

    frontend_base_url = _extract_api_base_url(frontend_base)
    details["frontend_base_url"] = frontend_base_url

    if frontend_base_url and backend_prefix:
        if not frontend_base_url.startswith(backend_prefix):
            issues.append(
                f"API base URL mismatch: frontend uses '{frontend_base_url}' "
                f"but backend routes are under '{backend_prefix}'"
            )

    # 2. Response wrapper check
    wrapper_issue = _check_response_wrapper(frontend_base)
    if wrapper_issue:
        issues.append(wrapper_issue)

    # 3. Endpoint comparison
    if frontend_services.exists() and backend_main.exists():
        frontend_calls = _extract_ts_api_calls(frontend_services)
        details["frontend_calls"] = frontend_calls

        # Build set of backend endpoints (normalized)
        backend_set = set()
        for route in details.get("backend_routes", []):
            # Normalize: "GET /products/:id" → "GET /products/"
            method, path = route.split(" ", 1)
            # Remove parameter segments for fuzzy matching
            normalized = re.sub(r'/:\w+', '/', path).rstrip('/')
            backend_set.add(f"{method} {normalized}")

        for file_name, calls in frontend_calls.items():
            for call in calls:
                method, path = call.split(" ", 1)
                # Remove frontend base URL prefix
                if frontend_base_url and path.startswith(frontend_base_url):
                    path = path[len(frontend_base_url):]
                # Remove query strings
                path = path.split("?")[0]
                # Normalize parameter segments
                normalized = re.sub(r'/\$\{\w+\}|/:\w+', '/', path).rstrip('/')
                lookup = f"{method} {normalized}"

                # Fuzzy match against backend endpoints
                if lookup not in backend_set and not any(
                    lookup.startswith(b) or b.startswith(lookup)
                    for b in backend_set
                ):
                    issues.append(
                        f"Frontend calls endpoint that may not exist on backend: "
                        f"{method} {path} (in {file_name})"
                    )

    status = "error" if issues else "ok"
    if status == "ok" and (not backend_main.exists() or not frontend_base.exists()):
        status = "warning"

    return {
        "status": status,
        "issues": issues,
        "details": details,
    }


def format_contract_report(result: Dict[str, Any]) -> str:
    """Format verification result as human-readable text."""
    lines = [f"Contract verification: {result['status'].upper()}"]
    if result["issues"]:
        lines.append(f"Found {len(result['issues'])} issue(s):")
        for i, issue in enumerate(result["issues"], 1):
            lines.append(f"  {i}. {issue}")
    else:
        lines.append("No contract mismatches detected.")

    details = result.get("details", {})
    if details.get("backend_prefix"):
        lines.append(f"  Backend prefix: {details['backend_prefix']}")
    if details.get("frontend_base_url"):
        lines.append(f"  Frontend base URL: {details['frontend_base_url']}")

    return "\n".join(lines)


@tool("verify_contract")
def verify_contract_tool() -> str:
    """Verify backend-frontend API contract alignment.

    Scans the workspace for:
    1. Backend route prefix vs frontend API_BASE_URL mismatch
    2. Missing response wrapper unwrapping in frontend
    3. Frontend calling endpoints that don't exist on backend

    Returns a human-readable report of any mismatches found.
    Use this BEFORE selecting agents to confirm changes are actually needed.
    """
    try:
        from .workspace_tools import get_workspace
        workspace = get_workspace()
    except Exception as e:
        return f"verify_contract: unable to get workspace: {e}"

    if not workspace.exists():
        return "verify_contract: workspace does not exist — nothing to verify"

    result = verify_contract(workspace)
    return format_contract_report(result)
