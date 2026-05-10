import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.swarm.claim_validators import (
    validate_backend_api_ready,
    validate_backend_runtime_ready,
    validate_deployment_ready,
    validate_evidence_files,
    validate_frontend_build_ready,
    validate_frontend_source_ready,
    validate_package_ready,
    validate_spec_ready,
)
from src.swarm.claims import ClaimType, build_claim_payload


def make_claim(claim_type, files=None, metadata=None):
    return build_claim_payload(
        project_id="project-1",
        claim_type=claim_type,
        producer_agent="tester",
        evidence={"files": files or [], "metadata": metadata or {}},
        now="2026-05-07T00:00:00Z",
    )


def write_minimal_pom(path: Path, java_version="21"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""
<project>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.5</version>
  </parent>
  <properties>
    <java.version>{java_version}</java.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
  </dependencies>
</project>
""".strip())


def write_frontend_package(path: Path, *, build=True, valid_json=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not valid_json:
        path.write_text("{ invalid")
        return
    scripts = '"scripts": {"build": "vite build"},' if build else '"scripts": {},'
    path.write_text(f"""{{
  {scripts}
  "dependencies": {{"@sveltejs/kit": "^2.0.0", "svelte": "^5.0.0"}}
}}""")


def test_validate_evidence_files_accepts_existing_file(tmp_path):
    (tmp_path / "SPEC.md").write_text("spec")

    result = validate_evidence_files(tmp_path, ["SPEC.md"])

    assert result["status"] == "valid"
    assert result["errors"] == []


def test_validate_evidence_files_rejects_missing_file(tmp_path):
    result = validate_evidence_files(tmp_path, ["missing.txt"])

    assert result["status"] == "invalid"
    assert "missing.txt" in result["errors"][0]


def test_validate_evidence_files_rejects_path_traversal(tmp_path):
    result = validate_evidence_files(tmp_path, ["../secret.txt"])

    assert result["status"] == "invalid"
    assert "escapes workspace" in result["errors"][0]


def test_validate_evidence_files_expands_glob_patterns(tmp_path):
    models_dir = tmp_path / "backend" / "internal" / "models"
    models_dir.mkdir(parents=True)
    (models_dir / "user.go").write_text("package models")

    result = validate_evidence_files(tmp_path, ["backend/internal/models/*.go"])

    assert result["status"] == "valid"
    assert "backend/internal/models/user.go" in result["checked_files"]


def test_validate_spec_ready_rejects_missing_spec(tmp_path):
    result = validate_spec_ready(tmp_path, make_claim(ClaimType.SPEC_READY))

    assert result["status"] == "invalid"
    assert "SPEC.md" in result["errors"][0]


def test_validate_spec_ready_rejects_empty_spec(tmp_path):
    (tmp_path / "SPEC.md").write_text("")

    result = validate_spec_ready(tmp_path, make_claim(ClaimType.SPEC_READY))

    assert result["status"] == "invalid"
    assert "empty" in result["errors"][0]


def test_validate_spec_ready_accepts_valid_spec(tmp_path):
    (tmp_path / "SPEC.md").write_text("# Spec")

    result = validate_spec_ready(tmp_path, make_claim(ClaimType.SPEC_READY))

    assert result["status"] == "valid"


def test_validate_backend_runtime_rejects_missing_pom(tmp_path):
    result = validate_backend_runtime_ready(
        tmp_path,
        make_claim(ClaimType.BACKEND_RUNTIME_READY),
    )

    assert result["status"] == "invalid"
    assert "backend" in result["errors"][0]


def test_validate_backend_runtime_accepts_valid_minimal_pom_and_source(tmp_path):
    write_minimal_pom(tmp_path / "backend" / "pom.xml")
    source = tmp_path / "backend" / "src" / "main" / "java" / "com" / "chatflow" / "App.java"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("class App {}")

    result = validate_backend_runtime_ready(
        tmp_path,
        make_claim(ClaimType.BACKEND_RUNTIME_READY, ["backend/pom.xml"]),
    )

    assert result["status"] == "valid"


def test_validate_backend_runtime_accepts_python_manifest_and_source(tmp_path):
    pyproject = tmp_path / "backend" / "pyproject.toml"
    pyproject.parent.mkdir(parents=True, exist_ok=True)
    pyproject.write_text("[project]\nname='test'\nversion='0.1.0'\n")
    source = tmp_path / "backend" / "src" / "app.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def app():\n    return 1\n")

    result = validate_backend_runtime_ready(
        tmp_path,
        make_claim(ClaimType.BACKEND_RUNTIME_READY, ["backend/pyproject.toml", "backend/src/*.py"]),
    )

    assert result["status"] == "valid"


def test_validate_backend_api_rejects_missing_api_manifest_and_controllers(tmp_path):
    result = validate_backend_api_ready(
        tmp_path,
        make_claim(ClaimType.BACKEND_API_READY),
    )

    assert result["status"] == "invalid"
    assert "API_MANIFEST" in result["errors"][0]


def test_validate_backend_api_accepts_api_manifest(tmp_path):
    manifest = tmp_path / "backend" / "API_MANIFEST.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{"endpoints": []}')

    result = validate_backend_api_ready(
        tmp_path,
        make_claim(ClaimType.BACKEND_API_READY, ["backend/API_MANIFEST.json"]),
    )

    assert result["status"] == "valid"


def test_validate_frontend_source_rejects_invalid_package_json(tmp_path):
    write_frontend_package(tmp_path / "frontend" / "package.json", valid_json=False)
    app_html = tmp_path / "frontend" / "src" / "app.html"
    app_html.parent.mkdir(parents=True, exist_ok=True)
    app_html.write_text("<div>%sveltekit.body%</div>")

    result = validate_frontend_source_ready(
        tmp_path,
        make_claim(ClaimType.FRONTEND_SOURCE_READY, ["frontend/package.json", "frontend/src/app.html"]),
    )

    assert result["status"] == "invalid"
    assert "invalid JSON" in result["errors"][0]


def test_validate_frontend_build_rejects_missing_build_script(tmp_path):
    write_frontend_package(tmp_path / "frontend" / "package.json", build=False)

    result = validate_frontend_build_ready(
        tmp_path,
        make_claim(ClaimType.FRONTEND_BUILD_READY, ["frontend/package.json"]),
    )

    assert result["status"] == "invalid"
    assert "build script" in result["errors"][0]


def test_validate_frontend_build_accepts_valid_manifest(tmp_path):
    write_frontend_package(tmp_path / "frontend" / "package.json")

    result = validate_frontend_build_ready(
        tmp_path,
        make_claim(ClaimType.FRONTEND_BUILD_READY, ["frontend/package.json"]),
    )

    assert result["status"] == "valid"


def test_validate_deployment_rejects_missing_compose(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "Dockerfile").write_text("FROM eclipse-temurin:21")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "Dockerfile").write_text("FROM node:22")

    result = validate_deployment_ready(
        tmp_path,
        make_claim(ClaimType.DEPLOYMENT_READY),
    )

    assert result["status"] == "invalid"
    assert any("docker-compose.yml" in error for error in result["errors"])


def test_validate_deployment_rejects_missing_dockerfile(tmp_path):
    (tmp_path / "docker-compose.yml").write_text("""
services:
  backend:
    build: ./backend
  frontend:
    build:
      context: ./frontend
""".strip())

    result = validate_deployment_ready(
        tmp_path,
        make_claim(ClaimType.DEPLOYMENT_READY),
    )

    assert result["status"] == "invalid"
    assert any("Dockerfile" in error for error in result["errors"])


def test_validate_deployment_accepts_valid_minimal_compose(tmp_path):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "Dockerfile").write_text("FROM eclipse-temurin:21")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "Dockerfile").write_text("FROM node:22")
    (tmp_path / "docker-compose.yml").write_text("""
services:
  backend:
    build: ./backend
  frontend:
    build:
      context: ./frontend
""".strip())

    result = validate_deployment_ready(
        tmp_path,
        make_claim(ClaimType.DEPLOYMENT_READY),
    )

    assert result["status"] == "valid"


def test_validate_package_rejects_missing_zip(tmp_path):
    result = validate_package_ready(
        tmp_path,
        make_claim(ClaimType.PACKAGE_READY, ["project-1.zip"]),
    )

    assert result["status"] == "invalid"
    assert "project-1.zip" in result["errors"][0]


def test_validate_package_rejects_empty_zip(tmp_path):
    (tmp_path / "project-1.zip").write_bytes(b"")

    result = validate_package_ready(
        tmp_path,
        make_claim(ClaimType.PACKAGE_READY, ["project-1.zip"]),
    )

    assert result["status"] == "invalid"
    assert "empty" in result["errors"][0]


def test_validate_package_accepts_non_empty_zip(tmp_path):
    with zipfile.ZipFile(tmp_path / "project-1.zip", "w") as archive:
        archive.writestr("README.md", "ready")

    result = validate_package_ready(
        tmp_path,
        make_claim(
            ClaimType.PACKAGE_READY,
            ["project-1.zip"],
            {"download_url": "https://storage.example/project-1.zip"},
        ),
    )

    assert result["status"] == "valid"
