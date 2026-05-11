"""Workspace evidence validators for swarm readiness claims."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .claims import ClaimType, claim_now_iso

_GLOB_CHARS = set("*?[]")

# ---------------------------------------------------------------------------
# Frontend Framework Detection (single source of truth)
# ---------------------------------------------------------------------------
# Maps framework key → (entry_point_candidates, config_file_candidates)
# Entry points: first existing file per group wins
# Config files: ALL existing files are included
_FRONTEND_FRAMEWORKS: dict[str, tuple[list[str], list[str]]] = {
    "sveltekit": (
        ["src/app.html", "src/routes/+page.svelte", "src/routes/+layout.svelte"],
        ["svelte.config.js", "svelte.config.ts", "vite.config.ts", "vite.config.js"],
    ),
    "svelte": (
        ["src/main.ts", "src/main.js", "src/App.svelte"],
        ["vite.config.ts", "vite.config.js"],
    ),
    "next": (
        ["app/page.tsx", "app/page.jsx", "pages/index.tsx", "pages/index.jsx", "pages/_app.tsx", "pages/_app.jsx"],
        ["next.config.js", "next.config.mjs", "next.config.ts"],
    ),
    "react": (
        ["src/main.tsx", "src/main.jsx", "src/App.tsx", "src/App.jsx"],
        ["vite.config.ts", "vite.config.js"],
    ),
    "vue": (
        ["src/main.ts", "src/main.js", "src/App.vue"],
        ["vite.config.ts", "vite.config.js"],
    ),
    "angular": (
        ["src/main.ts", "src/app/app.component.ts"],
        ["angular.json"],
    ),
    "nuxt": (
        ["app.vue", "pages/index.vue", "pages/index.tsx"],
        ["nuxt.config.ts", "nuxt.config.js"],
    ),
    "astro": (
        ["src/pages/index.astro", "src/pages/index.mdx", "src/content/config.ts"],
        ["astro.config.mjs", "astro.config.js"],
    ),
    "remix": (
        ["app/root.tsx", "app/root.jsx", "app/routes/_index.tsx"],
        ["remix.config.js", "vite.config.ts", "vite.config.js"],
    ),
    "solid": (
        ["src/app.tsx", "src/app.jsx", "src/entry-client.tsx"],
        ["vite.config.ts", "vite.config.js", "app.config.ts"],
    ),
    "qwik": (
        ["src/routes/index.tsx", "src/routes/layout.tsx"],
        ["vite.config.ts", "vite.config.js"],
    ),
    "gatsby": (
        ["src/pages/index.js", "src/pages/index.tsx"],
        ["gatsby-config.js", "gatsby-config.ts"],
    ),
    "ember": (
        ["app/app.js", "app/router.js"],
        ["ember-cli-build.js"],
    ),
}

# Framework dependency → framework key (order matters — most specific first)
_FRAMEWORK_DEPENDENCY_MAP: list[tuple[str, str]] = [
    ("@sveltejs/kit", "sveltekit"),
    ("@remix-run/react", "remix"),
    ("astro", "astro"),
    ("nuxt", "nuxt"),
    ("@builder.io/qwik", "qwik"),
    ("solid-js", "solid"),
    ("gatsby", "gatsby"),
    ("ember-source", "ember"),
    ("next", "next"),
    ("svelte", "svelte"),
    ("vue", "vue"),
    ("react", "react"),
    ("@angular/core", "angular"),
]

# Universal config files checked for ALL frameworks
_UNIVERSAL_CONFIGS: list[str] = [
    "package.json",
    "tsconfig.json",
    "jsconfig.json",
    "tailwind.config.js",
    "tailwind.config.ts",
    "postcss.config.js",
    "postcss.config.cjs",
    ".env",
    ".env.example",
]


def _detect_frontend_framework(package_json: dict[str, Any]) -> str:
    """Detect frontend framework from package.json dependencies."""
    deps = _package_dependencies(package_json)
    for dep, key in _FRAMEWORK_DEPENDENCY_MAP:
        if dep in deps:
            return key
    return ""


def _get_framework_entrypoints(frontend_dir: Path, framework: str) -> list[Path]:
    """Return existing entry-point files for the detected framework."""
    entrypoints, _ = _FRONTEND_FRAMEWORKS.get(framework, ([], []))
    matched: list[Path] = []
    for relative_path in entrypoints:
        path = frontend_dir / relative_path
        if path.exists() and path.is_file():
            matched.append(path)
    return matched


def _get_framework_configs(frontend_dir: Path, framework: str) -> list[Path]:
    """Return existing config files for the detected framework + universal configs."""
    _, configs = _FRONTEND_FRAMEWORKS.get(framework, ([], []))
    all_configs = list(configs) + _UNIVERSAL_CONFIGS
    matched: list[Path] = []
    seen: set[str] = set()
    for relative_path in all_configs:
        if relative_path in seen:
            continue
        seen.add(relative_path)
        path = frontend_dir / relative_path
        if path.exists() and path.is_file():
            matched.append(path)
    return matched


def make_validation_result(
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    **metadata: Any,
) -> dict[str, Any]:
    errors = errors or []
    warnings = warnings or []
    result = {
        "status": "valid" if not errors else "invalid",
        "validated_at": claim_now_iso(),
        "errors": errors,
        "warnings": warnings,
    }
    result.update(metadata)
    return result


def merge_validation_results(*results: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    merged: dict[str, Any] = {}

    for result in results:
        errors.extend(result.get("errors") or [])
        warnings.extend(result.get("warnings") or [])
        for key, value in result.items():
            if key not in {"status", "validated_at", "errors", "warnings"}:
                merged[key] = value

    return make_validation_result(errors, warnings, **merged)


def check_evidence_drift(
    workspace: str | Path,
    claim: dict[str, Any],
) -> dict[str, Any]:
    """Detect whether any evidence file was modified AFTER the claim was created.

    Returns an invalid result if drift is detected, otherwise valid.
    """
    workspace_path = Path(workspace).resolve(strict=False)
    claim_created_at = claim.get("created_at")
    if not claim_created_at:
        return make_validation_result()  # No timestamp to compare against

    try:
        from datetime import datetime, timezone
        # Parse ISO 8601 timestamp (handles both +00:00 and Z suffixes)
        ts = str(claim_created_at).replace("Z", "+00:00")
        claim_time = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return make_validation_result(warnings=[f"Cannot parse claim created_at: {claim_created_at}"])

    errors: list[str] = []
    warnings: list[str] = []
    evidence = claim.get("evidence")
    files = evidence.get("files") if isinstance(evidence, dict) else []

    for raw_file in files or []:
        relative_path = str(raw_file).strip()
        if not relative_path or Path(relative_path).is_absolute():
            continue
        full_path = (workspace_path / relative_path).resolve(strict=False)
        try:
            full_path.relative_to(workspace_path)
        except ValueError:
            continue
        if not full_path.exists() or not full_path.is_file():
            continue

        mtime = datetime.fromtimestamp(full_path.stat().st_mtime, tz=timezone.utc)
        if mtime > claim_time:
            errors.append(
                f"Evidence drift detected: {relative_path} was modified "
                f"after claim was published (mtime {mtime.isoformat()} > claim {claim_time.isoformat()})"
            )

    return make_validation_result(errors, warnings)


def validate_claim_evidence(workspace: str | Path, claim: dict[str, Any]) -> dict[str, Any]:
    workspace_path = Path(workspace)
    claim_type = str(claim.get("claim_type", ""))

    validators = {
        ClaimType.SPEC_READY.value: validate_spec_ready,
        ClaimType.BACKEND_RUNTIME_READY.value: validate_backend_runtime_ready,
        ClaimType.BACKEND_API_ENDPOINT.value: validate_backend_api_endpoint,
        ClaimType.BACKEND_API_READY.value: validate_backend_api_ready,
        ClaimType.FRONTEND_SOURCE_READY.value: validate_frontend_source_ready,
        ClaimType.FRONTEND_BUILD_READY.value: validate_frontend_build_ready,
        ClaimType.DEPLOYMENT_READY.value: validate_deployment_ready,
        ClaimType.PACKAGE_READY.value: validate_package_ready,
    }
    validator = validators.get(claim_type)
    if not validator:
        return make_validation_result([f"Unsupported claim type: {claim_type}"])

    typed_validation = validator(workspace_path, claim)
    drift_validation = check_evidence_drift(workspace_path, claim)
    return merge_validation_results(typed_validation, drift_validation)


def validate_evidence_files(
    workspace: str | Path,
    files: list[Any] | tuple[Any, ...] | None,
    *,
    allow_empty_files: bool = True,
) -> dict[str, Any]:
    workspace_path = Path(workspace).resolve(strict=False)
    errors: list[str] = []
    warnings: list[str] = []
    checked: list[str] = []

    for raw_file in files or []:
        relative_path = str(raw_file).strip()
        if not relative_path:
            errors.append("Evidence file path is empty")
            continue
        if Path(relative_path).is_absolute():
            errors.append(f"Evidence path must be relative: {relative_path}")
            continue

        matched_paths = _expand_workspace_matches(workspace_path, relative_path)
        if not matched_paths:
            errors.append(
                f"{'Evidence file pattern matched no files' if _has_glob(relative_path) else 'Evidence file is missing'}: {relative_path}"
            )
            continue

        for full_path in matched_paths:
            try:
                full_path.relative_to(workspace_path)
            except ValueError:
                errors.append(f"Evidence path escapes workspace: {relative_path}")
                continue

            checked.append(str(full_path.relative_to(workspace_path)).replace("\\", "/"))
            if not full_path.exists():
                errors.append(f"Evidence file is missing: {relative_path}")
                continue
            if not full_path.is_file():
                errors.append(f"Evidence path is not a regular file: {relative_path}")
                continue
            if full_path.stat().st_size == 0:
                message = f"Evidence file is empty: {relative_path}"
                if allow_empty_files:
                    warnings.append(message)
                else:
                    errors.append(message)

    return make_validation_result(errors, warnings, checked_files=checked)


def validate_spec_ready(workspace: str | Path, claim: dict[str, Any]) -> dict[str, Any]:
    return merge_validation_results(
        validate_evidence_files(workspace, ["SPEC.md"], allow_empty_files=False),
        validate_evidence_files(workspace, _claim_files(claim)),
    )


def validate_backend_runtime_ready(workspace: str | Path, claim: dict[str, Any]) -> dict[str, Any]:
    workspace_path = Path(workspace)
    errors: list[str] = []
    warnings: list[str] = []

    evidence = validate_evidence_files(workspace_path, _claim_files(claim))
    manifest_path = _detect_backend_manifest(workspace_path)
    if manifest_path is None:
        errors.append("Missing recognizable backend build manifest under backend/")
    elif manifest_path.name == "pom.xml":
        pom_result = _validate_spring_pom(manifest_path)
        errors.extend(pom_result["errors"])
        warnings.extend(pom_result["warnings"])

    source_files = _find_backend_source_files(workspace_path)
    if not source_files:
        errors.append("Missing backend source files under backend/")

    return merge_validation_results(
        evidence,
        make_validation_result(
            errors,
            warnings,
            backend_manifest=str(manifest_path.relative_to(workspace_path)).replace("\\", "/") if manifest_path else None,
            source_file_count=len(source_files),
        ),
    )


def validate_backend_api_endpoint(workspace: str | Path, claim: dict[str, Any]) -> dict[str, Any]:
    """Validate a single API endpoint claim.

    Evidence must include the file containing the endpoint and metadata
    with method and path.
    """
    workspace_path = Path(workspace)
    evidence = validate_evidence_files(workspace_path, _claim_files(claim))
    errors: list[str] = []
    warnings: list[str] = []

    meta = (claim.get("evidence") or {}).get("metadata") or {}
    method = meta.get("method", "")
    path = meta.get("path", "")

    if not method:
        errors.append("BACKEND_API_ENDPOINT claim missing metadata.method")
    if not path:
        errors.append("BACKEND_API_ENDPOINT claim missing metadata.path")

    return merge_validation_results(
        evidence,
        make_validation_result(errors, warnings, method=method, path=path),
    )


def validate_backend_api_ready(workspace: str | Path, claim: dict[str, Any]) -> dict[str, Any]:
    workspace_path = Path(workspace)
    evidence = validate_evidence_files(workspace_path, _claim_files(claim))
    errors: list[str] = []
    warnings: list[str] = []

    manifest = workspace_path / "backend" / "API_MANIFEST.json"
    api_files = _find_backend_api_files(workspace_path)

    if manifest.exists():
        try:
            parsed = json.loads(manifest.read_text())
            if not isinstance(parsed, dict):
                errors.append("backend/API_MANIFEST.json must contain a JSON object")
        except json.JSONDecodeError as exc:
            errors.append(f"backend/API_MANIFEST.json is invalid JSON: {exc.msg}")
    elif not api_files:
        errors.append("Missing backend API evidence: backend/API_MANIFEST.json or route/controller files")
    else:
        warnings.append("backend/API_MANIFEST.json missing; route/controller files used as API evidence")

    return merge_validation_results(
        evidence,
        make_validation_result(errors, warnings, controller_count=len(api_files)),
    )


def validate_frontend_source_ready(workspace: str | Path, claim: dict[str, Any]) -> dict[str, Any]:
    workspace_path = Path(workspace)
    evidence = validate_evidence_files(workspace_path, _claim_files(claim))
    package_result = _load_package_json(workspace_path)
    errors = list(package_result["errors"])
    warnings = list(package_result["warnings"])

    package_json = package_result.get("package_json") or {}
    dependencies = _package_dependencies(package_json)
    entry_files = _find_frontend_source_files(workspace_path)
    if not entry_files:
        errors.append("Missing recognizable frontend source entrypoint under frontend/")
    elif any(path.stat().st_size == 0 for path in entry_files):
        errors.append("Frontend source entrypoint is empty")

    if not dependencies:
        errors.append("frontend/package.json missing dependencies/devDependencies")

    return merge_validation_results(
        evidence,
        make_validation_result(
            errors,
            warnings,
            entrypoint_count=len(entry_files),
        ),
    )


def validate_frontend_build_ready(workspace: str | Path, claim: dict[str, Any]) -> dict[str, Any]:
    workspace_path = Path(workspace)
    evidence = validate_evidence_files(workspace_path, _claim_files(claim))
    package_result = _load_package_json(workspace_path)
    errors = list(package_result["errors"])
    warnings = list(package_result["warnings"])
    package_json = package_result.get("package_json") or {}

    scripts = package_json.get("scripts") if isinstance(package_json, dict) else {}
    if not isinstance(scripts, dict) or not scripts.get("build"):
        errors.append("frontend/package.json missing build script")

    return merge_validation_results(evidence, make_validation_result(errors, warnings))


def _validate_frontend_dockerfile(dockerfile_path: Path) -> dict[str, Any]:
    """Scan frontend/Dockerfile for common package-manager mistakes."""
    errors: list[str] = []
    warnings: list[str] = []
    if not dockerfile_path.exists() or not dockerfile_path.is_file():
        return make_validation_result(errors, warnings)

    content = dockerfile_path.read_text(errors="replace").lower()
    lines = content.splitlines()

    # Detect which package manager commands are used
    has_pnpm_cmd = "pnpm" in content
    has_yarn_cmd = "yarn" in content and "yarn.lock" not in content
    has_npm_ci = "npm ci" in content
    has_npm_install = "npm install" in content and "npm install -g" not in content

    # Detect which lockfiles are copied
    copies_pnpm_lock = "pnpm-lock.yaml" in content or "pnpm-lock.yml" in content
    copies_yarn_lock = "yarn.lock" in content
    copies_npm_lock = "package-lock.json" in content

    # Detect package manager installation
    installs_pnpm = "npm install -g pnpm" in content or "corepack enable" in content or "corepack prepare pnpm" in content
    installs_yarn = "npm install -g yarn" in content or "corepack enable" in content

    # Rule 1: pnpm used but not installed
    if has_pnpm_cmd and not installs_pnpm:
        errors.append(
            "frontend/Dockerfile uses pnpm but never installs it. "
            "Add: RUN npm install -g pnpm"
        )

    # Rule 2: yarn used but not installed
    if has_yarn_cmd and not installs_yarn:
        errors.append(
            "frontend/Dockerfile uses yarn but never installs it. "
            "Add: RUN npm install -g yarn"
        )

    # Rule 3: pnpm install --frozen-lockfile without copying pnpm-lock.yaml
    if "pnpm install" in content and not copies_pnpm_lock:
        errors.append(
            "frontend/Dockerfile runs pnpm install but does not COPY pnpm-lock.yaml. "
            "Add: COPY package.json pnpm-lock.yaml ./"
        )

    # Rule 4: yarn install --frozen-lockfile without copying yarn.lock
    if "yarn install" in content and not copies_yarn_lock:
        errors.append(
            "frontend/Dockerfile runs yarn install but does not COPY yarn.lock. "
            "Add: COPY package.json yarn.lock ./"
        )

    # Rule 5: npm ci without copying package-lock.json
    if has_npm_ci and not copies_npm_lock:
        errors.append(
            "frontend/Dockerfile runs npm ci but does not COPY package-lock.json. "
            "Add: COPY package.json package-lock.json ./"
        )

    # Rule 6: npm install (not ci) when a lockfile exists in workspace
    # We can't know for sure from Dockerfile alone, so just warn
    if has_npm_install and not has_npm_ci and not copies_npm_lock:
        warnings.append(
            "frontend/Dockerfile uses 'npm install' without a lockfile. "
            "If package-lock.json exists in the workspace, use 'npm ci' instead."
        )

    # Rule 7: No lockfile copied at all — suspicious
    if not copies_pnpm_lock and not copies_yarn_lock and not copies_npm_lock:
        if "copy package.json" in content:
            warnings.append(
                "frontend/Dockerfile copies package.json but no lockfile. "
                "Copy the lockfile (pnpm-lock.yaml / yarn.lock / package-lock.json) for reproducible builds."
            )

    return make_validation_result(errors, warnings)


def validate_deployment_ready(workspace: str | Path, claim: dict[str, Any]) -> dict[str, Any]:
    workspace_path = Path(workspace)
    evidence = validate_evidence_files(workspace_path, _claim_files(claim))
    required_files = [
        "backend/Dockerfile",
        "frontend/Dockerfile",
        "docker-compose.yml",
    ]
    required_result = validate_evidence_files(
        workspace_path,
        required_files,
        allow_empty_files=False,
    )
    errors: list[str] = []
    warnings: list[str] = []

    compose_path = workspace_path / "docker-compose.yml"
    if compose_path.exists() and compose_path.is_file():
        compose_text = compose_path.read_text(errors="replace")
        if not _compose_references_build_context(compose_text, "backend"):
            errors.append("docker-compose.yml missing backend build context")
        if not _compose_references_build_context(compose_text, "frontend"):
            errors.append("docker-compose.yml missing frontend build context")
    elif not compose_path.exists():
        errors.append("Missing docker-compose.yml")

    # Dockerfile sanity checks
    frontend_dockerfile = workspace_path / "frontend" / "Dockerfile"
    dockerfile_validation = _validate_frontend_dockerfile(frontend_dockerfile)

    return merge_validation_results(
        evidence, required_result, dockerfile_validation, make_validation_result(errors, warnings)
    )


def validate_package_ready(workspace: str | Path, claim: dict[str, Any]) -> dict[str, Any]:
    workspace_path = Path(workspace)
    errors: list[str] = []
    warnings: list[str] = []

    evidence = claim.get("evidence") if isinstance(claim.get("evidence"), dict) else {}
    files = evidence.get("files") or []
    zip_files = [str(path) for path in files if str(path).endswith(".zip")]
    if not zip_files:
        project_id = claim.get("project_id")
        if project_id:
            zip_files = [f"{project_id}.zip"]

    file_result = validate_evidence_files(
        workspace_path,
        zip_files,
        allow_empty_files=False,
    )

    for relative_path in zip_files:
        zip_path = (workspace_path / relative_path).resolve(strict=False)
        if zip_path.exists() and zip_path.is_file() and zip_path.stat().st_size > 0:
            if not zipfile.is_zipfile(zip_path):
                errors.append(f"Package file is not a valid zip archive: {relative_path}")

    metadata = evidence.get("metadata") if isinstance(evidence.get("metadata"), dict) else {}
    upload_keys = ("object_name", "download_url", "uploaded", "storage_url")
    if not any(metadata.get(key) for key in upload_keys):
        warnings.append("Package claim has no upload metadata")

    return merge_validation_results(file_result, make_validation_result(errors, warnings))


def _claim_files(claim: dict[str, Any]) -> list[Any]:
    evidence = claim.get("evidence")
    if not isinstance(evidence, dict):
        return []
    files = evidence.get("files")
    return files if isinstance(files, list) else []


def _has_glob(path: str) -> bool:
    return any(char in path for char in _GLOB_CHARS)


def _expand_workspace_matches(workspace: Path, relative_path: str) -> list[Path]:
    if _has_glob(relative_path):
        matches: list[Path] = []
        for candidate in workspace.glob(relative_path):
            resolved = candidate.resolve(strict=False)
            try:
                resolved.relative_to(workspace)
            except ValueError:
                continue
            matches.append(resolved)
        return sorted(matches)
    return [(workspace / relative_path).resolve(strict=False)]


def _detect_backend_manifest(workspace: Path) -> Path | None:
    backend_dir = workspace / "backend"
    candidates = [
        "pyproject.toml",
        "pom.xml",
        "go.mod",
        "package.json",
        "Cargo.toml",
        "build.gradle",
        "build.gradle.kts",
        "requirements.txt",
    ]
    for candidate in candidates:
        path = backend_dir / candidate
        if path.exists() and path.is_file():
            return path
    return None


def _find_backend_source_files(workspace: Path) -> list[Path]:
    backend_dir = workspace / "backend"
    extensions = ("*.py", "*.go", "*.java", "*.kt", "*.rs", "*.js", "*.ts")
    files: list[Path] = []
    for pattern in extensions:
        files.extend(backend_dir.rglob(pattern))
    return [path for path in files if path.is_file()]


def _find_backend_runtime_files(workspace: Path) -> list[Path]:
    files: list[Path] = []
    manifest = _detect_backend_manifest(workspace)
    if manifest and manifest.is_file():
        files.append(manifest)

    backend_dir = workspace / "backend"
    config_candidates = [
        "src/main/resources/application.yml",
        "src/main/resources/application.yaml",
        "src/main/resources/application.properties",
        ".env",
        ".env.example",
        "config.py",
    ]
    for relative_path in config_candidates:
        path = backend_dir / relative_path
        if path.exists() and path.is_file():
            files.append(path)
    return list(dict.fromkeys(files))


def _find_backend_api_files(workspace: Path) -> list[Path]:
    backend_dir = workspace / "backend"
    patterns = (
        "*Controller.java",
        "*Router.go",
        "*Handler.go",
        "*routes.py",
        "*router.py",
        "*views.py",
        "*controller.py",
        "*routes.ts",
        "*routes.js",
        "*controller.ts",
        "*controller.js",
    )
    files: list[Path] = []
    for pattern in patterns:
        files.extend(backend_dir.rglob(pattern))
    return [path for path in files if path.is_file()]


def _validate_spring_pom(pom_path: Path) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        root = ElementTree.parse(pom_path).getroot()
    except ElementTree.ParseError as exc:
        return {"errors": [f"backend/pom.xml is invalid XML: {exc}"], "warnings": []}

    text = ElementTree.tostring(root, encoding="unicode").lower()
    if "spring-boot" not in text:
        errors.append("backend/pom.xml missing Spring Boot dependency or parent")
    if "<java.version>" in text:
        match = re.search(r"<java\.version>\s*([^<]+)\s*</java\.version>", text)
        if match and not _is_supported_java_version(match.group(1)):
            errors.append(f"Unsupported Java version in backend/pom.xml: {match.group(1)}")
    else:
        warnings.append("backend/pom.xml does not declare java.version")

    return {"errors": errors, "warnings": warnings}


def _is_supported_java_version(value: str) -> bool:
    normalized = value.strip()
    return normalized.isdigit() and int(normalized) >= 17


def _load_package_json(workspace: Path) -> dict[str, Any]:
    path = workspace / "frontend" / "package.json"
    if not path.exists():
        return {"errors": ["Missing frontend/package.json"], "warnings": [], "package_json": {}}
    if not path.is_file():
        return {"errors": ["frontend/package.json is not a regular file"], "warnings": [], "package_json": {}}
    try:
        parsed = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return {
            "errors": [f"frontend/package.json is invalid JSON: {exc.msg}"],
            "warnings": [],
            "package_json": {},
        }
    if not isinstance(parsed, dict):
        return {"errors": ["frontend/package.json must contain a JSON object"], "warnings": [], "package_json": {}}
    return {"errors": [], "warnings": [], "package_json": parsed}


def _package_dependencies(package_json: dict[str, Any]) -> dict[str, Any]:
    dependencies: dict[str, Any] = {}
    for section in ("dependencies", "devDependencies"):
        values = package_json.get(section)
        if isinstance(values, dict):
            dependencies.update(values)
    return dependencies


def _find_frontend_source_files(workspace: Path) -> list[Path]:
    """Discover key frontend source + config files for evidence claims.

    Returns a bounded list of entry points and config files.
    NEVER rglobs all source files — that creates unclaimable evidence sets.
    """
    frontend_dir = workspace / "frontend"
    if not frontend_dir.exists():
        return []

    package_result = _load_package_json(workspace)
    package_json = package_result.get("package_json") or {}
    framework = _detect_frontend_framework(package_json)

    # Framework-specific entry points + universal configs
    files: list[Path] = []
    seen: set[str] = set()

    # 1. Entry points for detected framework
    if framework:
        for path in _get_framework_entrypoints(frontend_dir, framework):
            key = str(path)
            if key not in seen:
                seen.add(key)
                files.append(path)
    else:
        # No framework detected — probe universal entry points
        universal_entrypoints = [
            "index.html",
            "src/app.html",
            "src/main.ts",
            "src/main.js",
            "src/main.tsx",
            "src/main.jsx",
            "src/App.svelte",
            "src/App.tsx",
            "src/App.jsx",
            "src/App.vue",
            "app/page.tsx",
            "app/page.jsx",
            "pages/index.tsx",
            "pages/index.jsx",
            "app.vue",
        ]
        for rel in universal_entrypoints:
            path = frontend_dir / rel
            if path.exists() and path.is_file():
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    files.append(path)

    # 2. Config files (framework-specific + universal)
    configs = _get_framework_configs(frontend_dir, framework)
    for path in configs:
        key = str(path)
        if key not in seen:
            seen.add(key)
            files.append(path)

    return files


def _compose_references_build_context(compose_text: str, context: str) -> bool:
    patterns = [
        rf"context\s*:\s*\.?/{re.escape(context)}\b",
        rf"build\s*:\s*\.?/{re.escape(context)}\b",
    ]
    return any(re.search(pattern, compose_text) for pattern in patterns)


# ---------------------------------------------------------------------------
# Phase 3: Adversarial Evidence Derivation
# ---------------------------------------------------------------------------


def _derive_spec_evidence(workspace: Path) -> dict[str, Any]:
    """Re-derive SPEC_READY evidence from workspace without trusting the agent."""
    spec_path = workspace / "SPEC.md"
    files = ["SPEC.md"] if spec_path.exists() and spec_path.is_file() else []
    return {
        "files": files,
        "metadata": {"spec_exists": bool(files)},
    }


def _derive_backend_runtime_evidence(workspace: Path) -> dict[str, Any]:
    """Re-derive BACKEND_RUNTIME_READY evidence from workspace."""
    files = [
        str(path.relative_to(workspace)).replace("\\", "/")
        for path in _find_backend_runtime_files(workspace)
    ]
    manifest = _detect_backend_manifest(workspace)
    source_files = _find_backend_source_files(workspace)
    return {
        "files": files,
        "metadata": {
            "backend_manifest": str(manifest.relative_to(workspace)).replace("\\", "/") if manifest else None,
            "source_file_count": len(source_files),
            "java_source_count": len([path for path in source_files if path.suffix == ".java"]),
        },
    }


def _derive_backend_api_evidence(workspace: Path) -> dict[str, Any]:
    """Re-derive BACKEND_API_READY evidence from workspace."""
    manifest = workspace / "backend" / "API_MANIFEST.json"
    api_files = _find_backend_api_files(workspace)
    files: list[str] = []
    if manifest.exists() and manifest.is_file():
        files.append("backend/API_MANIFEST.json")
    return {
        "files": files,
        "metadata": {
            "manifest_exists": manifest.exists(),
            "controller_count": len(api_files),
        },
    }


def _derive_frontend_source_evidence(workspace: Path) -> dict[str, Any]:
    """Re-derive FRONTEND_SOURCE_READY evidence from workspace."""
    # _find_frontend_source_files already returns entry points + configs
    # via the unified framework detection system.
    files = [
        str(path.relative_to(workspace)).replace("\\", "/")
        for path in _find_frontend_source_files(workspace)
    ]
    pkg = workspace / "frontend" / "package.json"
    return {
        "files": files,
        "metadata": {
            "package_json_exists": pkg.exists(),
            "entrypoint_count": len(files),
        },
    }


def _derive_frontend_build_evidence(workspace: Path) -> dict[str, Any]:
    """Re-derive FRONTEND_BUILD_READY evidence from workspace."""
    pkg = workspace / "frontend" / "package.json"
    files: list[str] = []
    if pkg.exists() and pkg.is_file():
        files.append("frontend/package.json")
    return {
        "files": files,
        "metadata": {"package_json_exists": pkg.exists()},
    }


def _derive_deployment_evidence(workspace: Path) -> dict[str, Any]:
    """Re-derive DEPLOYMENT_READY evidence from workspace."""
    files: list[str] = []
    for path in [
        "docker-compose.yml",
        "backend/Dockerfile",
        "frontend/Dockerfile",
    ]:
        full = workspace / path
        if full.exists() and full.is_file():
            files.append(path)
    return {
        "files": files,
        "metadata": {"artifact_count": len(files)},
    }


def _derive_package_evidence(workspace: Path) -> dict[str, Any]:
    """Re-derive PACKAGE_READY evidence from workspace."""
    # Package claim typically references the project zip; we can't derive the
    # exact filename without project_id, so we check for any non-empty zip.
    zips = [str(p.relative_to(workspace)) for p in workspace.rglob("*.zip") if p.stat().st_size > 0]
    return {
        "files": zips,
        "metadata": {"zip_count": len(zips)},
    }


_DERIVATION_DISPATCH: dict[str, Any] = {
    ClaimType.SPEC_READY.value: _derive_spec_evidence,
    ClaimType.BACKEND_RUNTIME_READY.value: _derive_backend_runtime_evidence,
    ClaimType.BACKEND_API_READY.value: _derive_backend_api_evidence,
    ClaimType.FRONTEND_SOURCE_READY.value: _derive_frontend_source_evidence,
    ClaimType.FRONTEND_BUILD_READY.value: _derive_frontend_build_evidence,
    ClaimType.DEPLOYMENT_READY.value: _derive_deployment_evidence,
    ClaimType.PACKAGE_READY.value: _derive_package_evidence,
}


def _derive_evidence_for_claim_type(workspace: Path, claim_type: str) -> dict[str, Any]:
    """Return the evidence that *should* exist for this claim type, derived from workspace."""
    deriver = _DERIVATION_DISPATCH.get(claim_type)
    if not deriver:
        return {"files": [], "metadata": {}}
    return deriver(workspace)


def _compare_evidence(
    claimed: dict[str, Any],
    derived: dict[str, Any],
) -> dict[str, Any]:
    """Compare claimed evidence against independently derived evidence.

    Returns a validation result with mismatch errors/warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []

    claimed_files = set(str(f).strip().lstrip("./") for f in claimed.get("files") or [])
    derived_files = set(str(f).strip().lstrip("./") for f in derived.get("files") or [])

    missing = derived_files - claimed_files
    extra = claimed_files - derived_files

    if missing:
        errors.append(
            f"Evidence mismatch: agent did not claim files that exist in workspace: {sorted(missing)}"
        )
    if extra:
        warnings.append(
            f"Evidence mismatch: agent claimed files not found in workspace: {sorted(extra)}"
        )

    return make_validation_result(errors, warnings, adversarial=True)


def _materialize_claim_files(workspace: Path, claimed: dict[str, Any]) -> dict[str, Any]:
    files = claimed.get("files") or []
    materialized: list[str] = []
    for raw_file in files:
        relative_path = str(raw_file).strip()
        if not relative_path:
            continue
        matches = _expand_workspace_matches(workspace, relative_path)
        if matches:
            materialized.extend(
                str(path.relative_to(workspace)).replace("\\", "/")
                for path in matches
                if path.exists() and path.is_file()
            )
        else:
            materialized.append(relative_path)
    return {
        **claimed,
        "files": list(dict.fromkeys(materialized)),
    }


def verify_claim_adversarially(
    workspace: str | Path,
    claim: dict[str, Any],
) -> dict[str, Any]:
    """Verify a claim by re-deriving its evidence from the workspace without trusting the agent.

    Runs three checks:
    1. Type-specific validator (existing)
    2. Evidence drift detection (existing)
    3. Adversarial evidence comparison (new — derived vs claimed)

    Returns merged validation result.
    """
    workspace_path = Path(workspace).resolve(strict=False)
    claim_type = str(claim.get("claim_type", ""))

    # 1. Existing type-specific validation
    typed_validation = validate_claim_evidence(workspace_path, claim)

    # 2. Adversarial evidence derivation and comparison
    derived = _derive_evidence_for_claim_type(workspace_path, claim_type)
    claimed = _materialize_claim_files(workspace_path, claim.get("evidence") or {})
    adversarial = _compare_evidence(claimed, derived)

    # 3. Also run the type-specific validator against DERIVED evidence to catch
    # workspace issues the agent may have hidden.
    if derived.get("files"):
        synthetic_claim = dict(claim)
        synthetic_claim["evidence"] = derived
        derived_validation = validate_claim_evidence(workspace_path, synthetic_claim)
        # Only keep errors that are NOT already in typed_validation
        existing_errors = set(typed_validation.get("errors") or [])
        new_errors = [e for e in (derived_validation.get("errors") or []) if e not in existing_errors]
        if new_errors:
            adversarial["errors"] = list(adversarial.get("errors") or []) + new_errors
            adversarial["status"] = "invalid"

    return merge_validation_results(typed_validation, adversarial)


__all__ = [
    "make_validation_result",
    "merge_validation_results",
    "validate_claim_evidence",
    "validate_evidence_files",
    "validate_spec_ready",
    "validate_backend_runtime_ready",
    "validate_backend_api_ready",
    "validate_frontend_source_ready",
    "validate_frontend_build_ready",
    "validate_deployment_ready",
    "validate_package_ready",
    "verify_claim_adversarially",
    "_derive_evidence_for_claim_type",
    "_compare_evidence",
    "_derive_spec_evidence",
    "_derive_backend_runtime_evidence",
    "_derive_backend_api_evidence",
    "_derive_frontend_source_evidence",
    "_derive_frontend_build_evidence",
    "_derive_deployment_evidence",
    "_derive_package_evidence",
]
