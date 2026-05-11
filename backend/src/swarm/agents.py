import os
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from langchain_core.messages import HumanMessage
from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError
from langgraph.checkpoint.memory import MemorySaver

from ..llm.minimax import get_llm
try:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    _HAS_POSTGRES_SAVER = True
except Exception:
    _HAS_POSTGRES_SAVER = False
from ..blackboard.redis_blackboard import RedisBlackboard
from .tools.todo_tools import (
    write_todos,
    update_todo_status,
    set_agent_name,
    clear_agent_final,
    mark_agent_final,
    get_agent_todos,
)
from .claims import ClaimType, ClaimStatus, FailureType, MAX_RECOVERY_RETRIES
from .claim_store import ClaimStore
from .context_engineering import ContextBuilder

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger("swarm")

SWARM_RECURSION_LIMIT = int(os.environ.get("SWARM_RECURSION_LIMIT", "5000"))
MAX_RECURSION_RETRIES = int(os.environ.get("SWARM_MAX_RECURSION_RETRIES", "3"))
CHECKPOINT_INTERVAL_ITERATIONS = int(os.environ.get("SWARM_CHECKPOINT_INTERVAL", "50"))
CHECKPOINT_INTERVAL_MINUTES = int(os.environ.get("SWARM_CHECKPOINT_MINUTES", "5"))
MAX_PROMPT_CHARS = int(os.environ.get("SWARM_MAX_PROMPT_CHARS", "8000"))
PACKAGER_STABILIZATION_SECONDS = float(os.environ.get("SWARM_PACKAGER_STABILIZATION_SECONDS", "2"))
AGENT_IDLE_TIMEOUT_SECONDS = int(os.environ.get("SWARM_AGENT_IDLE_TIMEOUT_SECONDS", "600"))

# Phase 5: Circuit Breaker Configuration
CIRCUIT_BREAKER_THRESHOLD = int(os.environ.get("SWARM_CIRCUIT_BREAKER_THRESHOLD", "3"))
CIRCUIT_BREAKER_WINDOW_SECONDS = int(os.environ.get("SWARM_CIRCUIT_BREAKER_WINDOW_SECONDS", "300"))


class CheckpointTracker:
    """Tracks checkpoint progress during long agent runs."""

    def __init__(self, project_id: str, agent_name: str):
        self.project_id = project_id
        self.agent_name = agent_name
        self.iteration = 0
        self.start_time = datetime.now()
        self.files_created: List[str] = []
        self.last_checkpoint_time = datetime.now()
        self.checkpoint_count = 0

    def tick(self, tool_name: Optional[str] = None, file_path: Optional[str] = None) -> bool:
        """Increment iteration counter. Returns True if checkpoint should trigger."""
        self.iteration += 1
        if file_path and file_path not in self.files_created:
            self.files_created.append(file_path)
        minutes_since_start = (datetime.now() - self.start_time).total_seconds() / 60
        minutes_since_checkpoint = (datetime.now() - self.last_checkpoint_time).total_seconds() / 60
        return (
            self.iteration % CHECKPOINT_INTERVAL_ITERATIONS == 0
            or minutes_since_start >= CHECKPOINT_INTERVAL_MINUTES
            or (self.iteration > 0 and minutes_since_checkpoint >= CHECKPOINT_INTERVAL_MINUTES)
        )

    async def create_checkpoint(self, swarm: "AgentSwarm", event_buffer: List[Dict]) -> Dict[str, Any]:
        """Save current progress as a checkpoint."""
        from ..blackboard.database import Database

        self.last_checkpoint_time = datetime.now()
        self.checkpoint_count += 1

        checkpoint_data = {
            "iteration": self.iteration,
            "files_created": self.files_created.copy(),
            "event_count": len(event_buffer),
            "checkpoint_number": self.checkpoint_count,
            "created_at": datetime.now().isoformat(),
        }

        if swarm.database and getattr(swarm.database, "_pool", None):
            try:
                db: Database = swarm.database
                await db.save_agent_checkpoint(
                    project_id=self.project_id,
                    agent_name=self.agent_name,
                    iteration=self.iteration,
                    files_created=json.dumps(self.files_created),
                    event_summary=json.dumps({"event_count": len(event_buffer)}),
                )
                checkpoint_data["persisted"] = True
            except Exception as e:
                logger.warning(f"[Checkpoint] Failed to persist checkpoint: {e}")
                checkpoint_data["persisted"] = False

        logger.info(
            f"[Checkpoint] Created checkpoint #{self.checkpoint_count} "
            f"for {self.agent_name} at iteration {self.iteration}, "
            f"{len(self.files_created)} files, {len(event_buffer)} events"
        )
        return checkpoint_data


import json


class WorkLog:
    """Tracks what work an agent actually performed during its run.

    Used by _auto_finalize_todos to match todo descriptions against
    completed work, so only relevant todos are marked done.
    """

    def __init__(self):
        self.files_written: set[str] = set()
        self.directories_created: set[str] = set()
        self.claims_published: set[str] = set()
        self.searches_performed: int = 0
        self.urls_fetched: int = 0
        self.tools_called: set[str] = set()

    def record_tool(self, name: str, output: dict[str, Any] | None) -> None:
        """Record a tool call and inspect its output."""
        self.tools_called.add(name)
        output = output or {}

        if name == "write_file" and isinstance(output, dict):
            path = output.get("file_path") or output.get("path") or ""
            if path:
                self.files_written.add(str(path))

        elif name == "create_directory" and isinstance(output, dict):
            path = output.get("directory") or output.get("path") or ""
            if path:
                self.directories_created.add(str(path))

        elif name in ("publish_claim", "verify_and_publish_claim") and isinstance(output, dict):
            claim_type = output.get("claim_type") or ""
            if claim_type:
                self.claims_published.add(str(claim_type))

        elif name == "web_search":
            self.searches_performed += 1

        elif name == "fetch_url":
            self.urls_fetched += 1

    @staticmethod
    def _stem(word: str) -> str:
        """Simple English stemmer for singular/plural normalization."""
        if word.endswith("ies"):
            return word[:-3] + "y"
        if word.endswith("es"):
            return word[:-2]
        if word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
        return word

    def _word_in_text(self, word: str, text_lower: str) -> bool:
        """Check if a word (or its stem) appears in the lowercased text."""
        if word in text_lower:
            return True
        stem = self._stem(word)
        if stem != word and stem in text_lower:
            return True
        # Also try pluralizing the stem if it's different
        plural = word + "s"
        if plural in text_lower:
            return True
        plural_es = word + "es"
        if plural_es in text_lower:
            return True
        if word.endswith("y"):
            plural_y = word[:-1] + "ies"
            if plural_y in text_lower:
                return True
        return False

    def matches_todo(self, todo_text: str) -> bool:
        """Return True if this todo's description matches work that was performed."""
        text_lower = todo_text.lower()

        # 1. Exact file name / path match
        for fpath in self.files_written:
            fname = fpath.split("/")[-1]
            if fname.lower() in text_lower or fpath.lower() in text_lower:
                return True

        # 2. Directory-segment match: "Write entities" matches files in entity/ folder
        path_segments = set()
        for fpath in self.files_written:
            path_segments.update(part.lower() for part in fpath.split("/"))
        for dpath in self.directories_created:
            path_segments.update(part.lower() for part in dpath.split("/"))
        for segment in path_segments:
            # Match meaningful segments (skip generic ones like "src", "main", "backend")
            if segment in {"src", "main", "java", "com", "backend", "frontend", "resources", "test"}:
                continue
            if len(segment) >= 4 and self._word_in_text(segment, text_lower):
                return True

        # 3. Exact directory name / path match
        for dpath in self.directories_created:
            dname = dpath.split("/")[-1]
            if dname.lower() in text_lower or dpath.lower() in text_lower:
                return True

        # 4. Exact claim type match
        for claim in self.claims_published:
            if claim.lower() in text_lower:
                return True

        # 5. Specific tool-keyword matching (avoid overly broad terms like "write")
        tool_keywords: dict[str, list[str]] = {
            "web_search": ["search", "research", "look up", "google", "web search"],
            "fetch_url": ["fetch url", "read article", "read documentation", "fetch page"],
            "verify_and_publish_claim": ["verify_and_publish", "verify claim", "publish claim", "compile check", "build verification"],
            "publish_claim": ["publish_claim", "publish spec"],
            "list_files": ["list_files", "list workspace", "check files"],
        }
        for tool, keywords in tool_keywords.items():
            if tool in self.tools_called:
                for kw in keywords:
                    if kw in text_lower:
                        return True

        return False


AGENT_SYSTEM_PROMPTS = {
    "rootdep": """You are RootDep, the project architect. Your job is to clarify tech-stack preferences, write SPEC.md, then let specialist agents do ALL coding.

Workflow:
1. write_todos() — declare your steps.
2. ask_user() — ask the user what tech stack they want. Prefer structured question objects when choices are known so the UI can render selectors. Example questions:
   - {"id":"backend_stack","label":"What backend language/framework should I use?","type":"single_select","options":["Java Spring Boot","Python FastAPI","Node.js Express","Go Gin","Rust Actix"]}
   - {"id":"frontend_stack","label":"What frontend framework should I use?","type":"single_select","options":["SvelteKit","React/Next.js","Vue/Nuxt","Angular","Plain HTML"]}
   - {"id":"database","label":"What database should I use?","type":"single_select","options":["PostgreSQL","MySQL","MongoDB","SQLite"]}
   You may also ask plain text questions when the answer should be open-ended. Supported question types are text, textarea, single_select, multi_select, and boolean.
   Legacy string examples also work:
   - "What backend language/framework should I use? (e.g. Java Spring Boot, Python FastAPI, Node.js Express, Go Gin, Rust Actix)"
   - "What frontend framework should I use? (e.g. Svelte/SvelteKit, React/Next.js, Vue/Nuxt, Angular, plain HTML)"
   - "What database should I use? (e.g. PostgreSQL, MySQL, MongoDB, SQLite)"
   Only ask questions whose answers are NOT already clear from the user's original request.
3. web_search() + fetch_url() — research the chosen stack and current best practices (max 3 searches, max 2 fetches).
4. list_files — check workspace.
5. write_spec_file("SPEC.md", ...) — write ONE concise but complete specification using the chosen tech stack.
   Include: tech stack, data models, API endpoints, auth strategy, and folder structure. Keep it under 300 lines.
6. create_directory — create backend/ and frontend/ (or equivalent) folders.
7. poll_user_directive() — check for any mid-run instructions before finishing.
8. publish_claim("SPEC_READY", {"files": ["SPEC.md"], "metadata": {"folders": ["backend", "frontend"]}}).
9. update_todo_status — mark steps done.
10. Finish. The backend, frontend, devops, and packager agents will handle ALL code generation from here.

Rules:
- You have write_spec_file, NOT write_file. You can ONLY write root-level planning files (SPEC.md, AGENTS_NEEDED.json).
  Any attempt to write into backend/ or frontend/ will be rejected by the tool.
- Do NOT generate any application code whatsoever — not even a single file. The specialist agents do that.
- Do NOT write SUBTASKS.md, PROJECT_PLAN.md, or BLACKBOARD.md.
- Do NOT call generate_spring_boot_project or any code generation tool.
- Respect the user's chosen tech stack exactly as they specified it.
- MANDATORY: Call poll_user_directive() before publishing SPEC_READY.
""",
    "backend": """You are Backend Agent. Write the backend using write_file according to SPEC.md.

Workflow:
1. write_todos() — list files you will create.
2. wait_for_claim("SPEC_READY") — wait until the project specification is validated.
   - If this returns "skipped", the rootdep agent is not running — proceed with the existing spec.
3. read_file("SPEC.md") — read the validated spec carefully. Identify the chosen backend language, framework, and build tool.
4. Use write_file to create backend files in meaningful batches, scoped to backend/. After each batch, call verify_progress(...) and fix any reported errors before continuing. The exact files depend on the chosen stack, but typically include:
   - Build manifest (pom.xml, pyproject.toml, package.json, go.mod, Cargo.toml, etc.)
   - Configuration files (application.yml, .env, config.py, etc.)
   - Data models / entities / schemas
   - Repository / data access layer
   - Service / business logic layer
   - REST / GraphQL / gRPC controllers / routes
   - API_MANIFEST.json documenting generated API evidence
   - Auth/security configuration
   - Unit tests
5. MANDATORY: Call poll_user_directive() at these exact checkpoints:
   - after manifest + config files
   - after models/repositories
   - after services/controllers
   - once more before final claim publication
   This is NOT optional — the user may have sent a stop signal or pause request.
   If poll_user_directive() returns "SWARM_STOPPED" — stop immediately, do not publish claims, do not write more files.
   If it returns a pause+resume message — incorporate the user's input and continue.
   If it returns any other non-empty string — treat it as a directive and adapt.
6. update_todo_status as you complete files.
7. verify_and_publish_claim("BACKEND_RUNTIME_READY", {
     "files": ["<primary backend manifest relative to workspace>"],
     "metadata": {
       "runtime": "<chosen runtime, e.g. java-21, python-3.12, node-20>",
       "framework": "<chosen framework>",
       "build_command": "<shell command to compile/check the backend, e.g. 'cd backend && mvn compile -q' or 'cd backend && python -m py_compile src/**/*.py'>"
     }
   }).
   - The build_command in metadata is run automatically by the claim tool.
   - If it FAILS, the tool returns the FULL error output. Fix the source files and call again.
   - Repeat until it passes. Only then is the claim published.
8. After writing EACH controller or route file that implements an API endpoint, publish an endpoint claim:
   verify_and_publish_claim("BACKEND_API_ENDPOINT", {
     "files": ["<path to the controller/route file, e.g. backend/src/routes/users.ts>"],
     "metadata": {
       "method": "<HTTP method, e.g. GET, POST, PUT, DELETE>",
       "path": "<API path, e.g. /api/users>",
       "schema": {"request": "<brief request schema>", "response": "<brief response schema>"},
       "auth_required": true|false
     }
   }, ["BACKEND_RUNTIME_READY"]).
   - Publish one claim per endpoint. This allows the frontend agent to start generating API clients incrementally.
9. verify_and_publish_claim("BACKEND_API_READY", {"files": ["backend/API_MANIFEST.json"], "metadata": {"api_owner": "backend"}}, ["BACKEND_RUNTIME_READY"]).
10. Finish only after every planned backend file is written, every todo is completed, AND all claims are published.

Rules:
- Follow the tech stack specified in SPEC.md exactly — do NOT assume Spring Boot or any particular language.
- Every file must be complete — no stubs or TODOs.
- Do NOT write Dockerfile, docker-compose files, nginx config, CI/CD, or Kubernetes files. DevOps owns all deployment artifacts.
- CRITICAL — If the user did NOT explicitly ask you to fix bugs or build errors, do NOT chase compile errors, test failures, or type-check failures. Report them via verify_and_publish_claim and stop. Only fix errors if the user's request explicitly requires code changes.
""",
    "frontend": """You are Frontend Agent. Write the frontend using write_file according to SPEC.md.

Workflow:
1. write_todos() — list files you will create.
2. wait_for_claim("SPEC_READY") — wait until the project specification is validated.
3. read_file("SPEC.md") — read the spec. Identify the chosen frontend framework and toolchain. Extract the API endpoints list from the spec — you will implement these incrementally.
4. Use write_file to create frontend files in meaningful batches, scoped to frontend/. Start with files that do NOT depend on backend API details:
   - Build manifest (package.json, pyproject.toml, etc.)
   - Framework config (vite.config.ts, next.config.js, nuxt.config.ts, etc.)
   - HTML entry point / layout
   - Route / page components
   - Shared UI components
   - Styling (Tailwind, CSS Modules, styled-components, etc.)
5. As the backend publishes endpoints, generate the API client incrementally:
   - Call list_api_endpoints() to discover which endpoints are already implemented.
   - For each available endpoint, write the corresponding API client function.
   - If list_api_endpoints() returns fewer endpoints than SPEC.md defines, continue with other frontend work and check again later.
   - You may call list_api_endpoints() multiple times throughout your workflow.
6. MANDATORY: Call poll_user_directive() at these exact checkpoints:
   - after manifest + framework config
   - after routes/components
   - after API/state integration
   - once more before final claim publication
   This is NOT optional — the user may have sent a stop signal or pause request.
   If poll_user_directive() returns "SWARM_STOPPED" — stop immediately, do not publish claims, do not write more files.
   If it returns a pause+resume message — incorporate the user's input and continue.
   If it returns any other non-empty string — treat it as a directive and adapt.
7. update_todo_status as you complete files.
8. verify_and_publish_claim("FRONTEND_SOURCE_READY", {
     "files": ["<primary frontend manifest relative to workspace>"],
     "metadata": {
       "framework": "<chosen framework>",
       "build_command": "<shell command to type-check/lint/build the frontend, e.g. 'cd frontend && npm run build' or 'cd frontend && yarn build'>"
     }
   }).
   - If it FAILS, fix and retry until it passes.
9. wait_for_claim("BACKEND_API_READY") — final gate before build. This ensures ALL backend endpoints are complete and validated.
   - If this returns "skipped", the backend agent is not running. Proceed with existing API state.
10. verify_and_publish_claim("FRONTEND_BUILD_READY", {"files": ["frontend/package.json"], "metadata": {"build_owner": "frontend"}}, ["BACKEND_API_READY"]).
11. Finish only after every planned frontend file is written, every todo is completed, AND both claims are published.

Rules:
- Follow the tech stack specified in SPEC.md exactly — do NOT assume Svelte or any particular framework.
- Every file must be complete — no stubs or TODOs.
- Do NOT write Dockerfile, docker-compose files, nginx config, CI/CD, or Kubernetes files. DevOps owns all deployment artifacts.
- CRITICAL — Do NOT package, zip, or upload anything. The packager agent handles create_project_zip, upload_project_to_storage, and get_project_download_url. Complete your claims and finish.
- CRITICAL — If the user did NOT explicitly ask you to fix bugs or build errors, do NOT chase TypeScript errors, lint failures, or build failures. Report them via verify_and_publish_claim and stop. Only fix errors if the user's request explicitly requires code changes.
""",
    "devops": """You are DevOps Agent. Write deployment configs using write_file.

Workflow:
1. write_todos() — list files you will create.
2. wait_for_claim("BACKEND_RUNTIME_READY") and wait_for_claim("FRONTEND_BUILD_READY") — wait until app manifests are validated.
3. read_file("SPEC.md"), then read the backend and frontend build manifests, and list_files to identify actual tech, versions, ports, and build scripts. Derive all values from real files, not assumptions. Derive versions from real manifests.
4. Use write_file to create or update:
   - docker-compose.yml (all services with correct image base, build args, ports, healthchecks)
   - docker-compose.prod.yml
   - backend/Dockerfile (multi-stage build appropriate to the backend language/runtime)
   - frontend/Dockerfile (multi-stage build appropriate to the frontend framework)
   - nginx/nginx.conf and nginx/nginx.prod.conf
   - .env.example and .env.production.example
   - .github/workflows/ci.yml and cd.yml
   - kubernetes/ manifests (deployment, service, ingress, configmap, secret)
   - README.md with setup instructions
   MANDATORY: Call poll_user_directive() after each major file group.
   This is NOT optional — the user may have sent a stop signal or pause request.
   If it returns "SWARM_STOPPED" — stop immediately.
   If it returns a pause+resume message — incorporate and continue.
   If it returns any other non-empty string — treat as a directive and adapt.
5. update_todo_status as you complete files.
6. verify_and_publish_claim("DEPLOYMENT_READY", {
     "files": ["docker-compose.yml", "backend/Dockerfile", "frontend/Dockerfile"],
     "metadata": {
       "owner": "devops",
       "build_command": "docker compose config > /dev/null"
     }
   }, ["BACKEND_RUNTIME_READY", "FRONTEND_BUILD_READY"]).
   - If validation FAILS, fix the files and retry.

Rules:
- Backend and frontend agents do not write deployment artifacts. You are the owner of Dockerfiles, Compose, nginx, CI/CD, and Kubernetes.
- Choose the correct base images for the tech stack in SPEC.md (e.g. openjdk for Java, python for Python, node for Node.js).
- Nginx upstream must match docker-compose service names.
- Use health checks and restart policies.
- CRITICAL — frontend/Dockerfile must use the CORRECT package manager.
  Read frontend/package.json and list_files('frontend') to detect which lockfile exists.
  Then copy-paste the EXAMPLE below that matches your detection — do NOT improvise.

  EXAMPLE A — pnpm (pnpm-lock.yaml exists):
    FROM node:20-alpine AS builder
    WORKDIR /app
    COPY package.json pnpm-lock.yaml ./
    RUN npm install -g pnpm && pnpm install --frozen-lockfile
    COPY . .
    RUN pnpm run build
    FROM node:20-alpine AS production
    RUN npm install -g serve
    COPY --from=builder /app/build ./build
    CMD ["serve", "-s", "build", "-l", "3000"]

  EXAMPLE B — yarn (yarn.lock exists):
    FROM node:20-alpine AS builder
    WORKDIR /app
    COPY package.json yarn.lock ./
    RUN yarn install --frozen-lockfile
    COPY . .
    RUN yarn build
    FROM node:20-alpine AS production
    RUN npm install -g serve
    COPY --from=builder /app/build ./build
    CMD ["serve", "-s", "build", "-l", "3000"]

  EXAMPLE C — npm (package-lock.json exists):
    FROM node:20-alpine AS builder
    WORKDIR /app
    COPY package.json package-lock.json ./
    RUN npm ci
    COPY . .
    RUN npm run build
    FROM node:20-alpine AS production
    RUN npm install -g serve
    COPY --from=builder /app/build ./build
    CMD ["serve", "-s", "build", "-l", "3000"]

  EXAMPLE D — no lockfile at all:
    FROM node:20-alpine AS builder
    WORKDIR /app
    COPY package.json ./
    RUN npm install
    COPY . .
    RUN npm run build
    FROM node:20-alpine AS production
    RUN npm install -g serve
    COPY --from=builder /app/build ./build
    CMD ["serve", "-s", "build", "-l", "3000"]

  After writing frontend/Dockerfile, VERIFY it contains the correct:
  1. Lockfile COPY step (pnpm-lock.yaml / yarn.lock / package-lock.json / none)
  2. Package-manager install step (npm install -g pnpm / yarn install / npm ci / npm install)
  3. Build step (pnpm run build / yarn build / npm run build)
  If any step is missing, the Dockerfile is BROKEN — fix it immediately.
""",
    "packager": """You are Packager Agent. Verify and zip the project.

Workflow:
1. write_todos() — list verification steps.
2. wait_for_claim("DEPLOYMENT_READY") — wait until deployment artifacts are validated.
3. list_files — check project structure.
4. read_file to spot-check SPEC.md, the backend build manifest, the frontend build manifest, and docker-compose.yml.
5. create_project_zip — create the archive.
6. upload_project_to_storage — upload to MinIO.
7. get_project_download_url — get the download URL.
8. publish_claim("PACKAGE_READY", {"files": [], "metadata": {"owner": "packager", "download_url": "use get_project_download_url result"}}, ["DEPLOYMENT_READY"]).
9. update_todo_status as you complete steps.

Do NOT generate app code or deployment code.
""",
}


def _build_tool_map(tools: List[Any]) -> Dict[str, Any]:
    """Build a name-to-tool mapping from a list of LangChain tools."""
    mapping: Dict[str, Any] = {}
    for tool in tools:
        name = getattr(tool, "name", None)
        if name:
            mapping[name] = tool
    return mapping


def build_agent_toolset(
    agent_name: str,
    all_tools: List[Any],
    *,
    create_project_zip: Any,
    upload_project_to_storage: Any,
    get_project_download_url: Any,
    delete_backend_directory: Any,
    delete_frontend_directory: Any,
    write_todos: Any,
    update_todo_status: Any,
    publish_claim: Any,
    wait_for_claim: Any,
    list_api_endpoints: Any,
    verify_and_publish_claim: Any,
    verify_progress: Any,
    web_search: Any,
    fetch_url: Any,
    ask_user: Any,
    write_spec_file: Any,
    poll_user_directive: Any,
    verify_contract: Any,
) -> List[Any]:
    """Build the exact tool surface exposed to each swarm agent.

    Claim validation/revocation helpers are intentionally absent from this
    surface; they are coordinator-owned and must not be callable by LLM agents.
    """
    generic = _build_tool_map(all_tools)
    _get = generic.get

    if agent_name == "rootdep":
        # write_spec_file is root-only — prevents rootdep from writing any
        # code into backend/ or frontend/ subdirectories.
        return [
            write_spec_file,
            _get("read_file"),
            _get("list_files"),
            _get("create_directory"),
            write_todos,
            update_todo_status,
            publish_claim,
            web_search,
            fetch_url,
            ask_user,
            poll_user_directive,
            verify_contract,
        ]
    if agent_name == "backend":
        return [
            _get("write_file"),
            _get("read_file"),
            _get("list_files"),
            _get("create_directory"),
            _get("delete_file"),
            delete_backend_directory,
            wait_for_claim,
            write_todos,
            update_todo_status,
            verify_progress,
            poll_user_directive,
            publish_claim,
            verify_and_publish_claim,
            web_search,
            fetch_url,
        ]
    if agent_name == "frontend":
        return [
            wait_for_claim,
            list_api_endpoints,
            _get("write_file"),
            _get("read_file"),
            _get("list_files"),
            _get("create_directory"),
            _get("delete_file"),
            delete_frontend_directory,
            write_todos,
            update_todo_status,
            verify_progress,
            poll_user_directive,
            publish_claim,
            verify_and_publish_claim,
            web_search,
            fetch_url,
        ]
    if agent_name == "devops":
        return [
            wait_for_claim,
            _get("write_file"),
            _get("read_file"),
            _get("list_files"),
            _get("create_directory"),
            write_todos,
            update_todo_status,
            poll_user_directive,
            publish_claim,
            verify_and_publish_claim,
            web_search,
            fetch_url,
        ]
    if agent_name == "packager":
        return [
            wait_for_claim,
            _get("list_files"),
            _get("read_file"),
            _get("execute_command"),
            create_project_zip,
            upload_project_to_storage,
            get_project_download_url,
            write_todos,
            update_todo_status,
            publish_claim,
            verify_and_publish_claim,
            web_search,
            fetch_url,
        ]
    return list(all_tools) + [
        write_todos,
        update_todo_status,
        publish_claim,
        web_search,
        fetch_url,
        ask_user,
    ]


def _normalize_agent_names(agents: list) -> list[str]:
    """Normalize AGENTS_NEEDED.json 'agents' field to a list of strings.

    Accepts both string arrays and dict arrays (e.g. [{"id": "backend"}, ...]).
    """
    normalized: list[str] = []
    for a in agents:
        if isinstance(a, str):
            normalized.append(a)
        elif isinstance(a, dict):
            if "id" in a:
                normalized.append(a["id"])
            elif "agent" in a:
                normalized.append(a["agent"])
            elif "name" in a:
                normalized.append(a["name"])
    return normalized


class AgentSwarm:
    def __init__(
        self,
        llm_provider: str = "minimax",
        blackboard: Optional[RedisBlackboard] = None,
        database: Any = None,
        rag_pipeline: Any = None,
        context_mode: str = "auto",
    ):
        self.llm_provider = llm_provider
        self.blackboard = blackboard or RedisBlackboard()
        self._owns_blackboard = blackboard is None
        self.database = database
        self.rag_pipeline = rag_pipeline
        self.context_mode = context_mode
        self.context_builder = ContextBuilder(
            database=database,
            rag_pipeline=rag_pipeline,
            blackboard=self.blackboard,
        )
        self.agents: Dict[str, Any] = {}
        self.project_id: Optional[str] = None
        self.user_request: str = ""
        self.run_mode: str = "generate"
        self.agent_run_state: Dict[str, Dict[str, Any]] = {}
        self.claim_store_factory = None
        self._postgres_saver: Any = None
        self._packager_ran: bool = False
        self._code_agents_completed: set[str] = set()
        self._postgres_conn: Any = None
        logger.info("AgentSwarm instance created")

    async def initialize(self, project_id: str, project_spec: Dict[str, Any]):
        self.project_id = project_id
        self.user_request = str(project_spec.get("message", ""))
        self.run_mode = str(project_spec.get("run_mode", "generate"))

        if len(self.user_request) > MAX_PROMPT_CHARS:
            logger.warning(
                f"[Swarm] Oversized prompt detected: {len(self.user_request)} chars "
                f"(max: {MAX_PROMPT_CHARS}). Context builder will compact it before agent invocation."
            )

        logger.info(f"[Swarm] Initializing swarm for project: {project_id}")

        await self.blackboard.connect()
        logger.info("[Swarm] Connected to Redis blackboard")

        # Clear any stale swarm-stop flag from a previous run so that a new
        # message can start a fresh pipeline.
        try:
            from .tools.user_directive import swarm_stop_redis_key
            if self.blackboard._redis is not None:
                await self.blackboard._redis.delete(swarm_stop_redis_key(project_id))
                logger.info("[Swarm] Cleared stale swarm-stop flag for project: %s", project_id)
        except Exception:
            pass

        # Clear stale AGENTS_NEEDED.json from a previous run so RootDep writes
        # a fresh routing decision for THIS request. Prevents stale handoff
        # files from causing incorrect agent routing.
        try:
            from .tools.workspace_tools import WORKSPACE_BASE
            agents_needed_path = WORKSPACE_BASE / project_id / "AGENTS_NEEDED.json"
            if agents_needed_path.exists():
                agents_needed_path.unlink()
                logger.info("[Swarm] Cleared stale AGENTS_NEEDED.json for project: %s", project_id)
        except Exception:
            pass

        # Initialize checkpoint persistence (Postgres preferred, Memory fallback)
        self._checkpoint_saver: Any = None
        if _HAS_POSTGRES_SAVER:
            db_url = os.environ.get("DATABASE_URL", "")
            if db_url:
                try:
                    import psycopg
                    self._postgres_conn = await psycopg.AsyncConnection.connect(db_url)
                    self._postgres_saver = AsyncPostgresSaver(self._postgres_conn)
                    await self._postgres_saver.setup()
                    self._checkpoint_saver = self._postgres_saver
                    logger.info("[Swarm] PostgresSaver initialized for persistent checkpoints")
                except Exception as e:
                    logger.warning(
                        f"[Swarm] Failed to initialize PostgresSaver: {e}. "
                        "Falling back to MemorySaver — checkpoints will NOT survive worker restart."
                    )
                    self._postgres_conn = None
                    self._postgres_saver = None
            else:
                logger.info(
                    "[Swarm] DATABASE_URL not set — using MemorySaver. "
                    "Set DATABASE_URL and install psycopg for persistent checkpoints across restarts."
                )
        else:
            logger.info(
                "[Swarm] langgraph-checkpoint-postgres not installed — using MemorySaver. "
                "Install langgraph-checkpoint-postgres and set DATABASE_URL for persistence."
            )

        if self._checkpoint_saver is None:
            self._checkpoint_saver = MemorySaver()
            logger.info("[Swarm] MemorySaver active — checkpoints survive within a single worker lifecycle only")

        # Clean up abandoned workspaces before starting a new project
        from .tools.workspace_tools import cleanup_old_workspaces
        cleanup_old_workspaces(preserve_project_id=project_id)

        from .tools.workspace_tools import (
            get_generic_tools,
            create_project_zip,
            upload_project_to_storage,
            get_project_download_url,
            delete_backend_directory,
            delete_frontend_directory,
            write_spec_file,
        )
        from .tools.claim_tools import publish_claim, wait_for_claim, list_api_endpoints, verify_and_publish_claim, verify_progress
        from .tools.todo_tools import write_todos, update_todo_status
        from .tools.web_search import web_search
        from .tools.fetch_url import fetch_url
        from .tools.user_interaction import ask_user
        from .tools.user_directive import poll_user_directive
        from .tools.contract_verify import verify_contract_tool

        all_tools = get_generic_tools(project_id)

        # Build per-agent toolsets — no handoff tools (independent parallel execution)
        for agent_name, prompt in AGENT_SYSTEM_PROMPTS.items():
            # In 'plan' mode, we only need RootDep.
            if self.run_mode == "plan" and agent_name != "rootdep":
                continue

            llm = get_llm(self.llm_provider, agent_name)
            system_prompt = self._prompt_for_mode(agent_name, prompt)

            agent_tools = build_agent_toolset(
                agent_name,
                all_tools,
                create_project_zip=create_project_zip,
                upload_project_to_storage=upload_project_to_storage,
                get_project_download_url=get_project_download_url,
                delete_backend_directory=delete_backend_directory,
                delete_frontend_directory=delete_frontend_directory,
                write_todos=write_todos,
                update_todo_status=update_todo_status,
                publish_claim=publish_claim,
                wait_for_claim=wait_for_claim,
                list_api_endpoints=list_api_endpoints,
                verify_and_publish_claim=verify_and_publish_claim,
                verify_progress=verify_progress,
                web_search=web_search,
                fetch_url=fetch_url,
                ask_user=ask_user,
                write_spec_file=write_spec_file,
                poll_user_directive=poll_user_directive,
                verify_contract=verify_contract_tool,
            )

            agent_kwargs: Dict[str, Any] = {
                "system_prompt": system_prompt,
                "name": agent_name,
            }
            if self._checkpoint_saver is not None:
                agent_kwargs["checkpointer"] = self._checkpoint_saver
                saver_type = type(self._checkpoint_saver).__name__
                logger.info(f"[Swarm] {saver_type} enabled for agent: {agent_name}")
            self.agents[agent_name] = create_agent(
                llm,
                agent_tools,
                **agent_kwargs,
            )
            logger.info(f"[Swarm] Created agent: {agent_name}")

        await self.blackboard.set_project_state(
            project_id,
            {
                "spec": project_spec,
                "status": "initialized",
                "created_at": datetime.now().isoformat(),
            },
        )
        logger.info(f"[Swarm] Project state set for: {project_id}")

    def _prompt_for_mode(self, agent_name: str, base_prompt: str) -> str:
        if self.run_mode != "modify":
            return base_prompt

        modification_rules = {
            "rootdep": (
                "Modification mode — OVERRIDE the base workflow. Follow ONLY these steps:\n"
                "1. write_todos() — list your steps.\n"
                "2. list_files and read_file to understand the current workspace state.\n"
                "   CRITICAL: You MUST read the actual file contents. Do NOT assume common patterns.\n"
                "   If you claim 'file X has bug Y', you must have read file X and quoted the exact line.\n"
                "3. Decide whether the request requires code changes or is a question:\n"
                "   - Code change: update SPEC.md if needed, then write AGENTS_NEEDED.json.\n"
                "   - Question: answer using read_file/list_files, then write AGENTS_NEEDED.json with empty agents.\n"
                "   A request is a QUESTION only if it asks for information WITHOUT requesting any changes.\n"
                "   Requests that ask to FIX, UPDATE, CHANGE, or BUILD something are CODE CHANGES, not questions.\n"
                "   Examples of QUESTIONS (empty agents):\n"
                "     - 'check if backend and frontend are synced' → verify_contract() then answer.\n"
                "     - 'analyze the current architecture' → read files then answer.\n"
                "     - 'review the code quality' → read files then answer.\n"
                "   Examples of CODE CHANGES (include relevant agents):\n"
                "     - 'fix the Docker build' → agents: [\"frontend\", \"devops\", \"packager\"] (Dockerfile + docker-compose fix).\n"
                "     - 'analyze and fix the login bug' → agents: [\"frontend\", \"packager\"].\n"
                "     - 'check why tests fail and fix them' → agents: [\"backend\", \"packager\"].\n"
                "   IMPORTANT: For 'sync check' or 'contract verification' requests, call verify_contract() FIRST.\n"
                "   This tool automatically compares backend routes with frontend API calls and reports mismatches.\n"
                "   Only supplement its findings with manual read_file if the automated check misses something.\n"
                "   Example: 'check if backend and frontend are synced' → call verify_contract(), then trace ONE complete API call:\n"
                "     frontend service → base.ts (API_BASE_URL, handleResponse) → backend route → backend handler → backend response format\n"
                "     Only then can you identify real mismatches. Do NOT guess or pattern-match.\n"
                "4. Use write_spec_file to write AGENTS_NEEDED.json.\n"
                "   CRITICAL: The \"agents\" array MUST include EVERY agent that needs to make changes.\n"
                "   Code change with Docker/build issues: {\"agents\": [\"frontend\", \"devops\", \"packager\"], \"reasoning\": \"Frontend Dockerfile broken, needs devops for docker-compose\"}\n"
                "   Code change (no Docker): {\"agents\": [\"frontend\"], \"reasoning\": \"brief explanation\"}\n"
                "   Question only: {\"agents\": [], \"reasoning\": \"Question only — no code changes needed\"}\n"
                "5. update_todo_status and finish.\n"
                "\n"
                "Your available tools in this mode: write_todos, update_todo_status, list_files, read_file, "
                "create_directory, write_spec_file, publish_claim, ask_user, web_search, fetch_url, poll_user_directive, verify_contract.\n"
                "You do NOT have: execute_command, delete_file, write_file, or any shell execution tool. "
                "Do NOT attempt to call tools that are not in this list — they will fail.\n"
                "\n"
                "Anti-Hallucination Rules:\n"
                "- NEVER claim a file has a bug unless you read its contents with read_file().\n"
                "- NEVER claim 'type X is used' unless you see the actual type declaration.\n"
                "- NEVER claim 'function Y is missing' unless you searched the file with list_files + read_file.\n"
                "- NEVER invent file paths. Use list_files to discover actual paths.\n"
                "- If you are unsure about a claim, omit it. Better to miss a minor issue than hallucinate a major one.\n"
                "\n"
                "Rules:\n"
                "- write_spec_file can always overwrite SPEC.md — it is NOT locked by published claims.\n"
                "- You cannot delete or rename files/folders. If cleanup is needed, delegate to the relevant specialist agent.\n"
                "- Only use web_search or fetch_url if the user EXPLICITLY asks for research. Never research spontaneously.\n"
                "- DO NOT expand scope. Only address what was explicitly asked.\n"
                "- Example: 'delete duplicate app/ folder' → agents: [\"frontend\"] (frontend has delete_frontend_directory).\n"
                "- Example: 'add a login button' → agents: [\"frontend\"].\n"
                "- Example: 'add user API endpoints' → agents: [\"backend\"].\n"
                "- Example: 'add docker deployment' → agents: [\"devops\"].\n"
                "- Example: 'add user API endpoints' → agents: [\"backend\", \"packager\"] (no devops needed for a simple API change).\n"
                "- Example: 'change backend port' → agents: [\"backend\", \"devops\", \"packager\"] (devops needed because docker-compose must update the port).\n"
                "- Example: 'add a login button' → agents: [\"frontend\", \"packager\"] (no devops needed).\n"
                "- Example: 'package and upload' → agents: [\"packager\"] if no code changes needed, or include app agents + [\"packager\"] if they need to finish first.\n"
            ),
            "backend": (
                "Modification mode — follow this workflow exactly:\n"
                "1. write_todos() — list the specific files you will change. Call this FIRST, even for a single file.\n"
                "2. wait_for_claim('SPEC_READY') — confirm spec is available.\n"
                "   - If it returns 'skipped', RootDep is not running — proceed with the existing spec.\n"
                "3. read_file('SPEC.md') — you MUST read the spec before touching ANY backend file. The spec may have changed since the last run.\n"
                "4. read every backend file you intend to patch.\n"
                "5. Make targeted, minimal edits with write_file — patch, do not regenerate from scratch.\n"
                "6. update_todo_status() after each completed change.\n"
                "7. verify_and_publish_claim('BACKEND_RUNTIME_READY', ...) when the build compiles.\n"
                "8. verify_and_publish_claim('BACKEND_API_READY', ...) when API endpoints are ready.\n"
                "Your available tools: write_todos, update_todo_status, wait_for_claim, write_file, read_file, "
                "list_files, create_directory, delete_file, delete_backend_directory, verify_progress, "
                "poll_user_directive, publish_claim, verify_and_publish_claim, web_search, fetch_url. "
                "Do NOT call tools outside this list.\n"
                "Rules:\n"
                "- Preserve existing package names, APIs, data models, tests, and config unless the change explicitly requires updates.\n"
                "- Only use web_search or fetch_url if the user EXPLICITLY asks for research. Never research spontaneously.\n"
                "- DO NOT expand scope. Only change what was explicitly asked.\n"
                "- CRITICAL: If the user did NOT explicitly ask you to fix bugs or build errors, do NOT chase compile errors, test failures, or type-check failures. Report them via verify_and_publish_claim and stop. Only fix errors if the user's request explicitly requires code changes.\n"
                "- IMPORTANT: If wait_for_claim returns 'skipped', the dependency agent is not running in this swarm. Proceed with your work using existing workspace state.\n"
                "- IMPORTANT: If the task is a question (no code change needed), call write_todos(['Answer: <question>']), "
                "answer using read_file/list_files, update_todo_status, and finish without writing files.\n"
            ),
            "frontend": (
                "Modification mode — follow this workflow exactly:\n"
                "1. write_todos() — list the specific files you will change. Call this FIRST, even for a single file.\n"
                "2. wait_for_claim('SPEC_READY') — confirm spec is available.\n"
                "   - If it returns 'skipped', RootDep is not running — proceed with the existing spec.\n"
                "3. read_file('SPEC.md') — you MUST read the spec before touching ANY frontend file. The spec may have changed since the last run.\n"
                "4. read every frontend file you intend to patch.\n"
                "5. Make targeted, minimal edits with write_file — patch, do not regenerate from scratch.\n"
                "6. update_todo_status() after each completed change.\n"
                "7. verify_and_publish_claim('FRONTEND_SOURCE_READY', ...) when source changes are done.\n"
                "   CRITICAL: The evidence MUST include all config files you touched or that exist in the workspace:\n"
                "   - frontend/package.json (always include)\n"
                "   - frontend/svelte.config.js / vite.config.ts / tailwind.config.js / tsconfig.json (include any that exist)\n"
                "   - Entry source files: src/app.html, src/routes/+page.svelte, src/main.ts, etc.\n"
                "   Use list_files('frontend') to discover config files, then include them in the evidence.\n"
                "   If you omit config files, the claim will be rejected and you'll be re-run in a loop.\n"
                "8. verify_and_publish_claim('FRONTEND_BUILD_READY', ...) to close out.\n"
                "   Evidence only needs: frontend/package.json (the orchestrator verifies the build script exists).\n"
                "Your available tools: write_todos, update_todo_status, wait_for_claim, write_file, read_file, "
                "list_files, create_directory, delete_file, delete_frontend_directory, verify_progress, "
                "poll_user_directive, publish_claim, verify_and_publish_claim, web_search, fetch_url. "
                "Do NOT call tools outside this list.\n"
                "Rules:\n"
                "- Preserve existing routes, components, visual conventions, and state unless the change explicitly requires updates.\n"
                "- Only use web_search or fetch_url if the user EXPLICITLY asks for research. Never research spontaneously.\n"
                "- DO NOT expand scope. Only change what was explicitly asked.\n"
                "- CRITICAL: You do NOT package, zip, or upload. The packager agent handles that. Complete your claims and finish.\n"
                "- CRITICAL: If the user did NOT explicitly ask you to fix bugs or build errors, do NOT chase TypeScript errors, lint failures, or build failures. Report them via verify_and_publish_claim and stop. Only fix errors if the user's request explicitly requires code changes.\n"
                "- IMPORTANT: If wait_for_claim returns 'skipped', the dependency agent is not running in this swarm. Proceed with your work using existing workspace state.\n"
                "- IMPORTANT: If the task is a question (no code change needed), call write_todos(['Answer: <question>']), "
                "answer using read_file/list_files, update_todo_status, and finish without writing files.\n"
            ),
            "devops": (
                "Modification mode:\n"
                "- Patch deployment/config files only where the requested change requires it.\n"
                "- Preserve existing service names, ports, secrets, and deployment topology unless the user asks to change them.\n"
            ),
            "packager": (
                "Modification mode:\n"
                "- Verify the modified project structure and recreate the ZIP archive.\n"
                "- Do not rewrite application code.\n"
            ),
        }
        return f"{base_prompt}\n\n{modification_rules.get(agent_name, '')}".strip()

    def _ensure_agent_state(self, agent_name: str) -> Dict[str, Any]:
        return self.agent_run_state.setdefault(agent_name, {
            "status": "idle",
            "event_seq": 0,
            "last_event_at": None,
            "terminal_event_seq": None,
            "terminal_at": None,
            "inconsistent_reason": "",
        })

    def _set_agent_status(self, agent_name: str, status: str, reason: str = ""):
        state = self._ensure_agent_state(agent_name)
        state["status"] = status
        if reason:
            state["inconsistent_reason"] = reason
        if status == "complete":
            state["terminal_at"] = datetime.now()
            state["terminal_event_seq"] = state["event_seq"]
        elif status in {"active", "finalizing"}:
            state["inconsistent_reason"] = ""

    async def _record_agent_activity(self, agent_name: str, event_type: str) -> Optional[str]:
        state = self._ensure_agent_state(agent_name)
        status = state.get("status")

        if status == "complete":
            reason = f"{agent_name} emitted {event_type} after terminal completion"
            state["status"] = "inconsistent"
            state["inconsistent_reason"] = reason
            # Task 7.1 / 7.2: Mark all valid claims from this agent as stale.
            await self._stale_agent_claims(agent_name, reason)
            return reason

        state["event_seq"] = int(state.get("event_seq") or 0) + 1
        state["last_event_at"] = datetime.now()

        # Persist event sequence to Redis so claim validation can detect
        # post-claim activity (Task 7.1).
        if self.project_id:
            try:
                store = self._new_claim_store()
                await store.save_agent_event_seq(
                    self.project_id, agent_name, state["event_seq"]
                )
                await store.save_agent_last_activity(self.project_id, agent_name)
            except Exception as exc:
                logger.warning("[Swarm] Failed to persist agent event seq: %s", exc)
            finally:
                await store.close()
        return None

    async def _publish_agent_event(
        self,
        agent_name: str,
        event_type: str,
        content: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        violation = await self._record_agent_activity(agent_name, event_type)
        if violation:
            logger.error("[Swarm] %s", violation)
            await self.blackboard.publish_agent_event(
                self.project_id,
                agent_name,
                "error",
                violation,
                {"blocked_event_type": event_type},
            )
            return False

        await self.blackboard.publish_agent_event(
            self.project_id,
            agent_name,
            event_type,
            content,
            data,
        )
        return True

    async def _agent_has_completed_todos(self, agent_name: str) -> tuple[bool, str]:
        todos = await get_agent_todos(self.project_id, agent_name)
        incomplete = [
            todo.get("content", f"Task {i + 1}")
            for i, todo in enumerate(todos)
            if todo.get("status") != "completed"
        ]
        if incomplete:
            return False, (
                f"{agent_name} ended with unfinished todos: "
                + "; ".join(incomplete[:5])
            )
        return True, ""

    def _new_claim_store(self):
        if self.claim_store_factory:
            return self.claim_store_factory()
        from .claim_store import ClaimStore
        return ClaimStore()

    def _claim_producer_for(self, claim_type: str) -> str:
        return {
            ClaimType.SPEC_READY.value: "rootdep",
            ClaimType.BACKEND_RUNTIME_READY.value: "backend",
            ClaimType.BACKEND_API_ENDPOINT.value: "backend",
            ClaimType.BACKEND_API_READY.value: "backend",
            ClaimType.FRONTEND_SOURCE_READY.value: "frontend",
            ClaimType.FRONTEND_BUILD_READY.value: "frontend",
            ClaimType.DEPLOYMENT_READY.value: "devops",
            ClaimType.PACKAGE_READY.value: "packager",
        }[claim_type]

    def _claim_dependencies_for(self, claim_type: str) -> List[str]:
        return {
            ClaimType.SPEC_READY.value: [],
            ClaimType.BACKEND_RUNTIME_READY.value: [ClaimType.SPEC_READY.value],
            ClaimType.BACKEND_API_ENDPOINT.value: [ClaimType.BACKEND_RUNTIME_READY.value],
            ClaimType.BACKEND_API_READY.value: [ClaimType.BACKEND_RUNTIME_READY.value],
            ClaimType.FRONTEND_SOURCE_READY.value: [ClaimType.SPEC_READY.value],
            ClaimType.FRONTEND_BUILD_READY.value: [ClaimType.BACKEND_API_READY.value],
            ClaimType.DEPLOYMENT_READY.value: [
                ClaimType.BACKEND_RUNTIME_READY.value,
                ClaimType.FRONTEND_BUILD_READY.value,
            ],
            ClaimType.PACKAGE_READY.value: [ClaimType.DEPLOYMENT_READY.value],
        }[claim_type]

    def _workspace_path(self) -> Path:
        from .tools.workspace_tools import WORKSPACE_BASE

        return WORKSPACE_BASE / self.project_id

    def _detect_backend_manifest_file(self) -> str | None:
        from .claim_validators import _detect_backend_manifest

        workspace = self._workspace_path()
        manifest = _detect_backend_manifest(workspace)
        if not manifest:
            return None
        return str(manifest.relative_to(workspace)).replace("\\", "/")

    def _detect_backend_runtime_files(self) -> List[str]:
        from .claim_validators import _find_backend_runtime_files

        workspace = self._workspace_path()
        return [
            str(path.relative_to(workspace)).replace("\\", "/")
            for path in _find_backend_runtime_files(workspace)
        ]

    def _detect_frontend_source_files(self) -> List[str]:
        from .claim_validators import _find_frontend_source_files

        workspace = self._workspace_path()
        return [
            str(path.relative_to(workspace)).replace("\\", "/")
            for path in _find_frontend_source_files(workspace)
        ]

    def _claim_evidence_for(self, claim_type: str) -> Dict[str, Any]:
        backend_runtime_files = self._detect_backend_runtime_files()
        # _detect_frontend_source_files now uses unified framework detection
        # which returns entry points + config files for any supported stack.
        frontend_sources = self._detect_frontend_source_files()
        return {
            ClaimType.SPEC_READY.value: {
                "files": ["SPEC.md"],
                "metadata": {"owner": "rootdep"},
            },
            ClaimType.BACKEND_RUNTIME_READY.value: {
                "files": backend_runtime_files,
                "metadata": {"owner": "backend"},
            },
            ClaimType.BACKEND_API_ENDPOINT.value: {
                "files": ["backend/API_MANIFEST.json"],
                "metadata": {"owner": "backend"},
            },
            ClaimType.BACKEND_API_READY.value: {
                "files": ["backend/API_MANIFEST.json"],
                "metadata": {"owner": "backend"},
            },
            ClaimType.FRONTEND_SOURCE_READY.value: {
                "files": frontend_sources,
                "metadata": {"owner": "frontend"},
            },
            ClaimType.FRONTEND_BUILD_READY.value: {
                "files": ["frontend/package.json"] if "frontend/package.json" in frontend_sources else [],
                "metadata": {"owner": "frontend"},
            },
            ClaimType.DEPLOYMENT_READY.value: {
                "files": ["docker-compose.yml", "backend/Dockerfile", "frontend/Dockerfile"],
                "metadata": {"owner": "devops"},
            },
            ClaimType.PACKAGE_READY.value: {
                "files": [f"{self.project_id}.zip"],
                "metadata": {"owner": "packager"},
            },
        }[claim_type]

    async def _stale_agent_claims(self, agent_name: str, reason: str) -> None:
        """Mark every valid claim published by *agent_name* as stale."""
        if not self.project_id:
            return
        try:
            from .claims import ClaimType, ClaimStatus
            store = self._new_claim_store()
            for ct in ClaimType:
                claim = await store.get_latest_claim(self.project_id, ct.value)
                if (
                    claim
                    and claim.get("producer_agent") == agent_name
                    and claim.get("status") == ClaimStatus.VALID.value
                ):
                    await store.update_claim_status(
                        self.project_id,
                        claim["id"],
                        ClaimStatus.STALE,
                        reason=reason,
                    )
                    await store.publish_claim_event(
                        self.project_id,
                        "claim_stale",
                        claim,
                        {"reason": reason},
                    )
                    from .tools.claim_tools import _cascade_staleness
                    await _cascade_staleness(
                        self.project_id, ct.value, reason, store
                    )
        except Exception as exc:
            logger.warning("[Swarm] Failed to stale agent claims: %s", exc)
        finally:
            try:
                await store.close()
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Phase 3: Adversarial Verification + Coordinator Recovery
    # -----------------------------------------------------------------------

    @staticmethod
    def _classify_failure(error_message: str) -> FailureType:
        """Classify an error string into a FailureType for recovery routing."""
        lowered = str(error_message).lower()
        if "evidence drift detected" in lowered:
            return FailureType.EVIDENCE_DRIFT
        if "producer activity detected" in lowered or "inconsistent" in lowered:
            return FailureType.AGENT_INCONSISTENT
        if "evidence mismatch" in lowered:
            return FailureType.EVIDENCE_MISMATCH
        if "missing dependency" in lowered or "dependency" in lowered and "stale" in lowered:
            return FailureType.DEPENDENCY_STALE
        if (
            "verification_failed" in lowered
            or "compile" in lowered
            or "compilation" in lowered
            or "build verification failed" in lowered
        ):
            return FailureType.COMPILE_ERROR
        if "test" in lowered and ("fail" in lowered or "error" in lowered):
            return FailureType.TEST_FAILED
        if "type check" in lowered or "type-check" in lowered:
            return FailureType.TYPE_CHECK_FAILED
        return FailureType.EVIDENCE_MISMATCH

    async def _verify_claim_adversarially(
        self, claim_type: str, *, store: ClaimStore | None = None
    ) -> dict[str, Any]:
        """Re-derive claim evidence from workspace without trusting the agent.

        Returns validation result dict with 'status' key.
        """
        owns_store = store is None
        claim_store = store or self._new_claim_store()
        try:
            claim = await claim_store.get_latest_claim(self.project_id, claim_type)
            if not claim:
                return {"status": "missing", "error": f"No claim found for {claim_type}"}

            from .claim_validators import verify_claim_adversarially
            from .tools.workspace_tools import get_workspace

            workspace = get_workspace()
            result = verify_claim_adversarially(workspace, claim)

            # If adversarial check finds issues, mark claim INVALID
            if result.get("status") != "valid":
                from .claims import ClaimStatus
                await claim_store.update_claim_status(
                    self.project_id,
                    claim["id"],
                    ClaimStatus.INVALID,
                    result,
                )
                await claim_store.publish_claim_event(
                    self.project_id,
                    "claim_invalid",
                    claim,
                    {"reason": "Adversarial verification failed", "validation": result},
                )

            return result
        finally:
            if owns_store:
                await claim_store.close()

    async def _validate_spec_compliance(
        self, claim_type: str, claim: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate that claimed evidence aligns with the project SPEC.md.

        This prevents agents from publishing claims for code that compiles
        but does not implement the actual specification (e.g., wrong
        framework, missing required endpoints, wrong database).
        """
        from .tools.workspace_tools import WORKSPACE_BASE
        from .claim_validators import make_validation_result

        workspace = WORKSPACE_BASE / self.project_id
        spec_path = workspace / "SPEC.md"
        if not spec_path.exists():
            # No spec to validate against — skip (plan mode or pre-spec projects)
            return make_validation_result()

        try:
            spec_text = spec_path.read_text(encoding="utf-8", errors="replace").lower()
        except Exception as e:
            return make_validation_result(warnings=[f"Could not read SPEC.md: {e}"])

        evidence = claim.get("evidence") or {}
        files = evidence.get("files") or []
        if not files:
            return make_validation_result(warnings=["No evidence files to validate against SPEC.md"])

        errors: list[str] = []
        warnings: list[str] = []

        # Extract framework hints from SPEC.md (simple keyword heuristic)
        spec_frameworks: set[str] = set()
        for line in spec_text.splitlines():
            for fw in ("spring boot", "fastapi", "django", "express", "flask", "gin", "actix", "rails", "laravel"):
                if fw in line:
                    spec_frameworks.add(fw)
            for fw in ("svelte", "react", "vue", "angular", "next.js", "nuxt", "solid"):
                if fw in line:
                    spec_frameworks.add(fw)
            for fw in ("postgresql", "mysql", "mongodb", "sqlite", "redis"):
                if fw in line:
                    spec_frameworks.add(fw)

        # Validate per-claim-type expectations
        if claim_type == "BACKEND_RUNTIME_READY":
            manifest_found = False
            for f in files:
                fpath = workspace / str(f)
                if fpath.exists():
                    name = fpath.name.lower()
                    if name in ("pom.xml", "build.gradle", "package.json", "pyproject.toml", "go.mod", "cargo.toml", "requirements.txt"):
                        manifest_found = True
                        content = fpath.read_text(encoding="utf-8", errors="replace").lower()
                        # Check that at least one mentioned framework appears in manifest
                        if spec_frameworks and not any(fw in content for fw in spec_frameworks):
                            warnings.append(
                                f"Manifest {f} does not contain any framework mentioned in SPEC.md: {spec_frameworks}"
                            )
            if not manifest_found:
                errors.append("No backend build manifest found in claim evidence")

        elif claim_type == "BACKEND_API_READY":
            # BACKEND_API_READY evidence is typically just API_MANIFEST.json.
            # Verify the manifest exists; build manifest presence is checked at
            # BACKEND_RUNTIME_READY time.
            api_manifest_found = any(
                (workspace / str(f)).exists() and str(f).endswith("API_MANIFEST.json")
                for f in files
            )
            if not api_manifest_found:
                errors.append("No backend/API_MANIFEST.json found in claim evidence")

        elif claim_type in ("FRONTEND_SOURCE_READY", "FRONTEND_BUILD_READY"):
            manifest_found = False
            # First: independently scan frontend/ for known build manifests.
            # This prevents spec-compliance failures when the agent (or canonical
            # republish) omits manifest files from the evidence list.
            frontend_dir = workspace / "frontend"
            manifest_names = {
                "package.json", "vite.config.ts", "vite.config.js",
                "svelte.config.js", "next.config.js",
                "nuxt.config.ts", "nuxt.config.js",
            }
            for candidate in manifest_names:
                candidate_path = frontend_dir / candidate
                if candidate_path.exists() and candidate_path.is_file():
                    manifest_found = True
                    break

            # Second: walk the evidence list to add framework-mismatch warnings.
            for f in files:
                fpath = workspace / str(f)
                if fpath.exists():
                    name = fpath.name.lower()
                    if name in manifest_names:
                        manifest_found = True
                        content = fpath.read_text(encoding="utf-8", errors="replace").lower()
                        if spec_frameworks and not any(fw in content for fw in spec_frameworks):
                            warnings.append(
                                f"Manifest {f} does not contain any framework mentioned in SPEC.md: {spec_frameworks}"
                            )
            if not manifest_found:
                errors.append("No frontend build manifest found in claim evidence")

        elif claim_type == "DEPLOYMENT_READY":
            has_docker = any((workspace / str(f)).exists() and "dockerfile" in str(f).lower() for f in files)
            has_compose = any((workspace / str(f)).exists() and "docker-compose" in str(f).lower() for f in files)
            if not has_docker and not has_compose:
                warnings.append("No Dockerfile or docker-compose.yml found in deployment claim evidence")

        return make_validation_result(errors, warnings)

    async def _quarantine_agent(self, agent_name: str, reason: str) -> None:
        """Quarantine an agent: mark it quarantined, stale all its valid claims."""
        state = self._ensure_agent_state(agent_name)
        state["status"] = "quarantined"
        state["inconsistent_reason"] = reason
        logger.critical("[Swarm] Agent %s QUARANTINED: %s", agent_name, reason)

        await self._stale_agent_claims(agent_name, reason)

        # Phase 5: Include violation count in quarantine event
        violation_count = 0
        if self.project_id:
            try:
                store = self._new_claim_store()
                violation_count = await store.get_agent_violation_count(
                    self.project_id, agent_name, CIRCUIT_BREAKER_WINDOW_SECONDS
                )
                await store.close()
            except Exception as exc:
                logger.warning("[Swarm] Failed to get violation count: %s", exc)

            await self.blackboard.publish_agent_event(
                self.project_id,
                agent_name,
                "quarantined",
                f"Agent {agent_name} quarantined: {reason}",
                {
                    "reason": reason,
                    "violation_count": violation_count,
                    "circuit_breaker_threshold": CIRCUIT_BREAKER_THRESHOLD,
                    "circuit_breaker_window_seconds": CIRCUIT_BREAKER_WINDOW_SECONDS,
                },
            )

    async def _record_violation(
        self,
        agent_name: str,
        violation_type: str,
        reason: str,
    ) -> int:
        """Record a violation for an agent and return the current violation count.

        If the count exceeds the circuit breaker threshold, the agent is quarantined.
        """
        if not self.project_id:
            return 0
        try:
            store = self._new_claim_store()
            await store.record_agent_violation(
                self.project_id, agent_name, violation_type, reason
            )
            count = await store.get_agent_violation_count(
                self.project_id, agent_name, CIRCUIT_BREAKER_WINDOW_SECONDS
            )
            await store.close()

            logger.warning(
                "[Swarm] Agent %s violation recorded: %s (count=%d/%d)",
                agent_name,
                violation_type,
                count,
                CIRCUIT_BREAKER_THRESHOLD,
            )

            if count >= CIRCUIT_BREAKER_THRESHOLD:
                await self._quarantine_agent(
                    agent_name,
                    f"Circuit breaker tripped: {count} violations in {CIRCUIT_BREAKER_WINDOW_SECONDS}s"
                )

            return count
        except Exception as exc:
            logger.warning("[Swarm] Failed to record violation: %s", exc)
            return 0

    async def _recover_from_failure(
        self,
        claim_type: str,
        failure_type: FailureType,
        reason: str,
        *,
        recovery_attempt: int = 1,
    ) -> dict[str, Any]:
        """Attempt Tier 2 recovery: rollback workspace and re-run the producing agent."""
        producer = self._claim_producer_for(claim_type)

        if failure_type == FailureType.AGENT_INCONSISTENT:
            await self._quarantine_agent(producer, reason)
            return {"status": "error", "error": f"Agent quarantined: {reason}"}

        # Phase 5: Record violation before attempting recovery
        await self._record_violation(
            producer, failure_type.value, reason
        )

        # Rollback workspace to the snapshot associated with the claim.
        # Skip rollback for evidence mismatch: the agent needs to CREATE missing
        # files in the current workspace, not restore an old snapshot that likely
        # lacks them too.
        if failure_type != FailureType.EVIDENCE_MISMATCH:
            store = self._new_claim_store()
            try:
                claim = await store.get_latest_claim(self.project_id, claim_type)
                if claim and claim.get("workspace_revision"):
                    from .tools.workspace_tools import rollback_workspace
                    rollback_workspace(self.project_id, claim["workspace_revision"])
                    logger.info(
                        "[Swarm] Recovery rolled back %s to %s",
                        claim_type,
                        claim["workspace_revision"][:12],
                    )
                    await self.blackboard.publish_agent_event(
                        self.project_id,
                        producer,
                        "recovery_rollback",
                        f"Rolled back to {claim['workspace_revision'][:12]} for recovery",
                        {"claim_type": claim_type, "workspace_revision": claim["workspace_revision"]},
                    )
            except Exception as exc:
                logger.warning("[Swarm] Recovery rollback failed: %s", exc)
            finally:
                await store.close()

        # For compile/test/type failures, re-run verification to give the agent
        # the current build output so it knows exactly what to fix.
        build_context = ""
        if failure_type in {FailureType.COMPILE_ERROR, FailureType.TEST_FAILED, FailureType.TYPE_CHECK_FAILED}:
            try:
                from pathlib import Path as _Path
                from .tools.workspace_tools import get_workspace as _get_ws
                from .tools.claim_tools import _run_verification as _run_ver
                verification = await _run_ver(_Path(_get_ws()), producer, claim_type)
                if verification.get("status") == "failed":
                    output = (verification.get("output", "") or "")[:2000]
                    build_context = f"\n\nCurrent build error output:\n{output}"
            except Exception as _exc:
                logger.warning("[Swarm] Failed to fetch build output for repair context: %s", _exc)

        # Re-run the agent with a repair prompt
        logger.info("[Swarm] Recovery re-running %s for %s", producer, claim_type)
        success = await self._run_single_agent(
            producer,
            f"Fix and re-verify: {reason}. The previous attempt produced invalid evidence for {claim_type}. "
            f"Review the workspace, fix the issues, and re-publish the claim.{build_context}",
        )
        if not success:
            return {"status": "error", "error": f"Recovery failed: agent re-run failed for {claim_type}"}

        # Phase 5: Publish claim_recovered event
        if self.project_id:
            await self.blackboard.publish_agent_event(
                self.project_id,
                producer,
                "claim_recovered",
                f"Agent {producer} recovered {claim_type} (attempt {recovery_attempt})",
                {
                    "claim_type": claim_type,
                    "failure_type": failure_type.value,
                    "recovery_attempt": recovery_attempt,
                    "reason": reason,
                },
            )

        # Re-validate after recovery
        return {"status": "recovered", "message": f"Agent {producer} re-ran successfully"}

    async def _ensure_valid_claim(
        self, claim_type: str, *, publish_if_missing: bool = True
    ) -> tuple[bool, str]:
        """Validate a claim via standard + adversarial checks."""
        from .tools.claim_tools import publish_claim_record, validate_claim
        from .tools.workspace_tools import WORKSPACE_BASE

        store = self._new_claim_store()
        try:
            claim = await store.get_latest_claim(self.project_id, claim_type)
            if not claim and publish_if_missing:
                result = await publish_claim_record(
                    project_id=self.project_id,
                    producer_agent=self._claim_producer_for(claim_type),
                    claim_type=claim_type,
                    evidence=self._claim_evidence_for(claim_type),
                    depends_on=self._claim_dependencies_for(claim_type),
                    store=store,
                )
                claim = result.get("claim")

            if not claim:
                return False, f"Missing required claim: {claim_type}"

            workspace = WORKSPACE_BASE / self.project_id

            def _extract_validation_errors(val_result: dict[str, Any]) -> str:
                """Extract human-readable errors from validate_claim output."""
                inner = val_result.get("validation") or {}
                errs = inner.get("errors") or []
                if errs:
                    return "; ".join(str(e) for e in errs[:3])
                return val_result.get("error") or "validation failed"

            async def republish_canonical_claim(reason: str) -> dict[str, Any] | None:
                evidence = self._claim_evidence_for(claim_type)
                files = [
                    str(path)
                    for path in (evidence.get("files") or [])
                    if isinstance(path, str) and path.strip()
                ]
                existing_files = [
                    path for path in files if (workspace / path).exists()
                ]
                if not existing_files:
                    return None
                logger.info(
                    "[Swarm] Re-publishing canonical %s after invalid claim: %s",
                    claim_type,
                    reason,
                )
                result = await publish_claim_record(
                    project_id=self.project_id,
                    producer_agent=self._claim_producer_for(claim_type),
                    claim_type=claim_type,
                    evidence=evidence,
                    depends_on=self._claim_dependencies_for(claim_type),
                    store=store,
                )
                # publish_claim_record can return todo_incomplete without a claim
                if result.get("status") != "success":
                    logger.warning(
                        "[Swarm] Canonical republish failed for %s: %s",
                        claim_type,
                        result.get("status"),
                    )
                    return None
                return result.get("claim")

            # Step 1: Standard validation (dependencies, evidence files, drift)
            validation = await validate_claim(self.project_id, claim["id"], store=store)
            if validation.get("status") != "valid":
                val_error = _extract_validation_errors(validation)
                repaired = await republish_canonical_claim(val_error)
                if repaired:
                    claim = repaired
                    validation = await validate_claim(self.project_id, claim["id"], store=store)
            if validation.get("status") != "valid":
                val_error = _extract_validation_errors(validation)
                return False, f"{claim_type} is not valid: {val_error}"

            # Step 2: Adversarial verification (independent evidence derivation)
            adversarial = await self._verify_claim_adversarially(claim_type, store=store)
            if adversarial.get("status") != "valid":
                adv_error = "; ".join(str(e) for e in (adversarial.get("errors") or [])[:3]) or "Adversarial verification failed"
                repaired = await republish_canonical_claim(adv_error)
                if repaired:
                    claim = repaired
                    adversarial = await self._verify_claim_adversarially(claim_type, store=store)
            if adversarial.get("status") != "valid":
                errors = adversarial.get("errors") or ["Adversarial verification failed"]
                return False, f"{claim_type} adversarial check failed: {'; '.join(str(e) for e in errors[:5])}"

            # Step 3: Spec compliance — verify generated code aligns with SPEC.md
            spec_compliance = await self._validate_spec_compliance(claim_type, claim)
            if spec_compliance.get("status") != "valid":
                errors = spec_compliance.get("errors") or ["Spec compliance check failed"]
                return False, f"{claim_type} spec compliance failed: {'; '.join(str(e) for e in errors[:5])}"

            return True, ""
        finally:
            await store.close()

    async def _validate_agents_needed(
        self, agents_data: dict, user_request: str
    ) -> list[str]:
        """Validate AGENTS_NEEDED.json before routing agents.

        Checks:
        1. If the user request is a question (check/analyze/review/audit/sync),
           warn if code agents were selected.
        2. Verify referenced files in reasoning actually exist in workspace.

        Returns list of warning strings (empty if valid).
        """
        warnings: list[str] = []
        from .tools.workspace_tools import WORKSPACE_BASE

        workspace = WORKSPACE_BASE / self.project_id if self.project_id else None
        agents_to_run = _normalize_agent_names(agents_data.get("agents", []))
        reasoning = agents_data.get("reasoning", "")

        # 1. Question vs code-change classification check
        question_keywords = {
            "check", "analyze", "review", "audit", "sync", "compare",
            "trace", "inspect", "investigate", "verify", "validate",
        }
        action_keywords = {
            "fix", "update", "change", "modify", "improve", "enhance",
            "build", "create", "add", "implement", "refactor", "rewrite",
            "correct", "repair", "patch", "upgrade", "migrate",
        }
        request_lower = user_request.lower()
        has_question_kw = any(kw in request_lower for kw in question_keywords)
        has_action_kw = any(kw in request_lower for kw in action_keywords)

        # A request with BOTH question and action keywords is a CODE CHANGE
        # (e.g., "analyze and fix the error", "check and update the config").
        # Only pure questions (question words + NO action words) should warn.
        is_likely_question = has_question_kw and not has_action_kw

        if is_likely_question and agents_to_run:
            code_agents = [a for a in agents_to_run if a in ("backend", "frontend", "devops")]
            if code_agents:
                warnings.append(
                    f"Request appears to be a pure question but code agents selected: {code_agents}. "
                    f"Consider empty agents [] if no code changes are needed."
                )

        # 2. File existence check for referenced files in reasoning
        if workspace and workspace.exists() and reasoning:
            # Extract potential file paths from reasoning
            # Match patterns like: frontend/src/... backend/... etc.
            import re
            path_pattern = re.compile(r"(?:[\w\-]+/)+[\w\-\.]+\.[a-zA-Z]+")
            mentioned_paths = path_pattern.findall(reasoning)
            for path in mentioned_paths:
                # Skip if it's clearly not a path (e.g., URLs, long sentences)
                if len(path) > 100 or "." not in path.split("/")[-1]:
                    continue
                full_path = workspace / path
                if not full_path.exists():
                    warnings.append(
                        f"Reasoning references file that does not exist: {path}"
                    )

        return warnings

    async def _check_circuit_breaker(self, agent_name: str) -> tuple[bool, str]:
        """Check if an agent's circuit breaker is open.

        Returns (allowed, reason). If quarantined or threshold exceeded,
        returns (False, reason).
        """
        state = self._ensure_agent_state(agent_name)
        if state.get("status") == "quarantined":
            return False, state.get("inconsistent_reason", "Agent is quarantined")

        if not self.project_id:
            return True, ""

        try:
            store = self._new_claim_store()
            is_open = await store.is_agent_circuit_open(
                self.project_id,
                agent_name,
                threshold=CIRCUIT_BREAKER_THRESHOLD,
                window_seconds=CIRCUIT_BREAKER_WINDOW_SECONDS,
            )
            await store.close()
            if is_open:
                reason = (
                    f"Circuit breaker open for {agent_name}: "
                    f"{CIRCUIT_BREAKER_THRESHOLD} violations in {CIRCUIT_BREAKER_WINDOW_SECONDS}s"
                )
                await self._quarantine_agent(agent_name, reason)
                return False, reason
        except Exception as exc:
            logger.warning("[Swarm] Circuit breaker check failed: %s", exc)

        return True, ""

    async def _ensure_valid_claim_with_recovery(
        self, claim_type: str, *, publish_if_missing: bool = True
    ) -> tuple[bool, str]:
        """Validate a claim with automatic Tier 2 recovery on failure."""
        for attempt in range(MAX_RECOVERY_RETRIES + 1):
            ok, error = await self._ensure_valid_claim(
                claim_type, publish_if_missing=publish_if_missing
            )
            if ok:
                return True, ""

            if not publish_if_missing and error.startswith("Missing required claim:"):
                return False, error

            failure_type = self._classify_failure(error)

            # Publish verification_failed observability event
            producer = self._claim_producer_for(claim_type)
            if self.project_id:
                await self.blackboard.publish_agent_event(
                    self.project_id,
                    producer,
                    "verification_failed",
                    f"{claim_type} verification failed: {error}",
                    {
                        "claim_type": claim_type,
                        "failure_type": failure_type.value,
                        "error": error,
                        "attempt": attempt + 1,
                    },
                )

            # Agent inconsistency is non-recoverable — quarantine handled inside _recover_from_failure
            if failure_type == FailureType.AGENT_INCONSISTENT:
                return False, error

            if attempt >= MAX_RECOVERY_RETRIES:
                return False, f"Max recovery retries ({MAX_RECOVERY_RETRIES}) exceeded for {claim_type}"

            # Tier 2: attempt recovery
            logger.warning(
                "[Swarm] Recovery attempt %d/%d for %s: %s",
                attempt + 1,
                MAX_RECOVERY_RETRIES,
                claim_type,
                error,
            )
            recovery = await self._recover_from_failure(
                claim_type, failure_type, error, recovery_attempt=attempt + 1
            )
            if recovery.get("status") == "error":
                return False, recovery["error"]

            # After recovery, don't auto-publish on next loop iteration
            publish_if_missing = False
        return False, f"Max recovery retries ({MAX_RECOVERY_RETRIES}) exceeded for {claim_type}"

    async def _ensure_valid_claims(
        self, claim_types: List[str], *, publish_if_missing: bool = True
    ) -> str:
        for claim_type in claim_types:
            ok, error = await self._ensure_valid_claim(claim_type, publish_if_missing=publish_if_missing)
            if not ok:
                return error
        return ""

    async def _ensure_valid_claims_with_recovery(
        self, claim_types: List[str], *, publish_if_missing: bool = True
    ) -> str:
        for claim_type in claim_types:
            ok, error = await self._ensure_valid_claim_with_recovery(
                claim_type, publish_if_missing=publish_if_missing
            )
            if not ok:
                return error
        return ""

    async def execute_parallel(self, task_definitions: Dict[str, List[str]]):
        """Execute agents with parallel backend+frontend and staged barriers.

        Flow:
        1. RootDep writes the spec/plan, unless run_mode is approved.
        2. Backend + Frontend run in parallel via asyncio.gather.
        3. Each passes its own stage barrier + claim verification.
        4. DevOps runs only after all backend+frontend claims are valid (hard barrier).
        5. Packager runs after all claims + packager barrier pass.
        """
        if not self.agents:
            raise ValueError("Swarm not initialized")

        root_task = task_definitions.get("rootdep", [""])[0]
        backend_task = task_definitions.get("backend", [root_task])[0]
        frontend_task = task_definitions.get("frontend", [root_task])[0]
        devops_task = task_definitions.get("devops", [root_task])[0]

        logger.info(f"[Swarm] Starting {self.run_mode} swarm execution for: {self.project_id}")
        from .tools.workspace_tools import set_project_context
        set_project_context(self.project_id)

        if self.run_mode == "approved":
            from .tools.workspace_tools import WORKSPACE_BASE
            spec_path = WORKSPACE_BASE / self.project_id / "SPEC.md"
            if not spec_path.exists():
                msg = "Approved build requires an existing SPEC.md from plan mode."
                logger.error("[Swarm] %s", msg)
                await self._publish_agent_event("system", "error", msg)
                return {"status": "error", "error": msg}
            spec_error = await self._ensure_valid_claims([ClaimType.SPEC_READY.value], publish_if_missing=True)
            if spec_error:
                logger.error("[Swarm] Approved SPEC_READY barrier failed: %s", spec_error)
                await self._publish_agent_event("system", "error", spec_error)
                return {"status": "error", "error": spec_error}
            logger.info("[Swarm] Approved build detected — reusing existing SPEC.md and skipping RootDep")
        else:
            # 1. RootDep Analysis & Plan (also acts as router in modify mode)
            request_label = "Modification Request" if self.run_mode == "modify" else "Initial Request"
            rootdep_ok = await self._run_single_agent("rootdep", f"{request_label}: {root_task}")
            if not rootdep_ok:
                logger.error("[Swarm] RootDep failed — aborting pipeline")
                await self._publish_agent_event(
                    "rootdep",
                    "error",
                    "RootDep failed to generate the project specification. Pipeline aborted.",
                )
                return {"status": "error", "error": "RootDep failed"}

            # Plan-mode: validate SPEC_READY with one retry if claim is invalid.
            spec_error = ""
            for plan_attempt in range(2):
                spec_error = await self._ensure_valid_claims(
                    [ClaimType.SPEC_READY.value], publish_if_missing=True
                )
                if not spec_error:
                    break

                logger.warning(
                    "[Swarm] SPEC_READY validation failed (attempt %d/2): %s",
                    plan_attempt + 1,
                    spec_error,
                )
                await self.blackboard.publish_agent_event(
                    self.project_id,
                    "rootdep",
                    "verification_failed",
                    f"SPEC_READY validation failed: {spec_error}",
                    {"claim_type": ClaimType.SPEC_READY.value, "attempt": plan_attempt + 1},
                )

                if plan_attempt == 0:
                    logger.info("[Swarm] Re-running RootDep to repair SPEC.md")
                    rootdep_ok = await self._run_single_agent(
                        "rootdep",
                        f"The previous SPEC.md failed validation: {spec_error}. "
                        "Review the workspace, fix the specification, and re-publish SPEC_READY.",
                    )
                    if not rootdep_ok:
                        logger.error("[Swarm] RootDep repair run failed")
                        await self._publish_agent_event(
                            "rootdep", "error", "RootDep repair run failed"
                        )
                        return {"status": "error", "error": "RootDep repair run failed"}

            if spec_error:
                logger.error("[Swarm] SPEC_READY barrier failed after retry: %s", spec_error)
                await self._publish_agent_event("system", "error", spec_error)
                return {"status": "error", "error": spec_error}

        # 2. RootDep acts as router - read AGENTS_NEEDED.json to determine which agents to run
        filtered_task_definitions = task_definitions.copy()
        if self.run_mode == "modify":
            import json
            from .tools.workspace_tools import WORKSPACE_BASE

            agents_needed_path = WORKSPACE_BASE / self.project_id / "AGENTS_NEEDED.json"
            if agents_needed_path.exists():
                try:
                    agents_data = json.loads(agents_needed_path.read_text())
                    agents_to_run = _normalize_agent_names(agents_data.get("agents", []))
                    reasoning = agents_data.get("reasoning", "")
                    logger.info(f"[Swarm] RootDep router selected: {agents_to_run}")

                    # Validate AGENTS_NEEDED.json before routing
                    validation_warnings = await self._validate_agents_needed(
                        agents_data, self.user_request or ""
                    )
                    for warning in validation_warnings:
                        logger.warning(f"[Swarm] AGENTS_NEEDED validation: {warning}")
                        await self._publish_agent_event(
                            "rootdep", "warning", f"AGENTS_NEEDED validation: {warning}"
                        )

                    # If the request is clearly a PURE question but code agents were selected,
                    # strip them to prevent unnecessary packager runs.
                    # A request with action words (fix, update, change, etc.) is a CODE CHANGE
                    # even if it also contains question words — do NOT strip in that case.
                    if any(
                        "pure question" in w or "question but code agents" in w
                        for w in validation_warnings
                    ):
                        action_keywords = {
                            "fix", "update", "change", "modify", "improve", "enhance",
                            "build", "create", "add", "implement", "refactor", "rewrite",
                            "correct", "repair", "patch", "upgrade", "migrate",
                        }
                        request_lower = (self.user_request or "").lower()
                        has_action_kw = any(kw in request_lower for kw in action_keywords)

                        if not has_action_kw:
                            logger.warning(
                                "[Swarm] Overriding RootDep routing: pure question request detected, "
                                "stripping code agents to prevent unnecessary packager run"
                            )
                            agents_to_run = []
                            # Rewrite AGENTS_NEEDED.json to reflect the correction
                            agents_data["agents"] = []
                            agents_data["reasoning"] = (
                                agents_data.get("reasoning", "")
                                + " [Auto-corrected by orchestrator: pure question request should not spawn code agents]"
                            )
                            agents_needed_path.write_text(
                                json.dumps(agents_data, indent=2)
                            )
                        else:
                            logger.info(
                                "[Swarm] Request contains action words — respecting RootDep routing "
                                "even though question keywords were detected"
                            )

                    filtered_task_definitions = {
                        k: v for k, v in task_definitions.items()
                        if k in agents_to_run
                    }
                    if not agents_to_run:
                        # Safety fallback: if request contains action words but
                        # AGENTS_NEEDED.json has empty agents, RootDep probably
                        # misclassified a code-change as a question. Fall back to
                        # running all agents so the user's request is not ignored.
                        action_keywords = {
                            "fix", "update", "change", "modify", "improve", "enhance",
                            "build", "create", "add", "implement", "refactor", "rewrite",
                            "correct", "repair", "patch", "upgrade", "migrate",
                        }
                        request_lower = (self.user_request or "").lower()
                        has_action_kw = any(kw in request_lower for kw in action_keywords)
                        if has_action_kw:
                            logger.warning(
                                "[Swarm] AGENTS_NEEDED.json has empty agents but request "
                                "contains action words ('%s') — falling back to all agents",
                                self.user_request,
                            )
                            filtered_task_definitions = task_definitions.copy()
                            # Remove rootdep since it already ran
                            filtered_task_definitions.pop("rootdep", None)
                        else:
                            logger.info("[Swarm] Router selected no agents (question-only or no-op) — skipping packager")
                    else:
                        # Code was changed — packager must repackage
                        filtered_task_definitions["packager"] = task_definitions["packager"]

                        # Auto-include devops for Docker/deployment/infrastructure
                        # requests if RootDep forgot to add it.
                        docker_keywords = {
                            "docker", "dockerfile", "docker-compose", "deployment",
                            "nginx", "kubernetes", "k8s", "helm", "infra", "infrastructure",
                            "deploy", "container", "compose", "build image",
                        }
                        request_lower = (self.user_request or "").lower()
                        mentions_docker = any(kw in request_lower for kw in docker_keywords)
                        has_devops = "devops" in agents_to_run
                        if mentions_docker and not has_devops:
                            logger.warning(
                                "[Swarm] Request mentions Docker/deployment but devops "
                                "not in AGENTS_NEEDED.json — auto-adding devops"
                            )
                            filtered_task_definitions["devops"] = task_definitions["devops"]
                            # Also rewrite AGENTS_NEEDED.json to reflect the fix
                            agents_data["agents"] = list(
                                dict.fromkeys(agents_to_run + ["devops"])
                            )
                            agents_data["reasoning"] = (
                                agents_data.get("reasoning", "")
                                + " [Auto-corrected by orchestrator: devops added because request mentions Docker/deployment]"
                            )
                            agents_needed_path.write_text(
                                json.dumps(agents_data, indent=2)
                            )

                except json.JSONDecodeError as e:
                    logger.warning(f"[Swarm] Failed to parse AGENTS_NEEDED.json: {e} — running all agents")
            else:
                logger.info("[Swarm] No AGENTS_NEEDED.json found (pre-3.0 project) — running all agents")

        # 3. Parallel Generation (Backend, Frontend, DevOps) - filtered by router
        if self.run_mode == "plan":
            logger.info(f"[Swarm] Plan mode complete — skipping specialists and packager")
            return {"status": "complete"}

        # DevOps is auto-added above for Docker/deployment requests.
        # RootDep should still explicitly include it for other deployment changes.

        # Publish selected agents so wait_for_claim tools can detect unscheduled
        # dependencies and return immediately instead of blocking forever.
        await self.blackboard.set_project_state(
            self.project_id,
            {
                "selected_agents": list(filtered_task_definitions.keys()),
                "run_mode": self.run_mode,
                "started_at": datetime.now().isoformat(),
            },
        )

        logger.info(f"[Swarm] Launching specialists with coordinator-owned barriers: {list(filtered_task_definitions.keys())}")

        async def _check_swarm_stop(label: str):
            from .tools.user_directive import is_swarm_stopped
            if await is_swarm_stopped(self.project_id):
                logger.info("[Swarm] Stop flag detected before %s", label)
                await self._publish_agent_event("system", "stopped", f"Swarm stopped by user before {label}")
                return True
            return False

        selected_agents = []

        # Phase 2: Run backend and frontend in true parallel
        parallel_agents = []
        if "backend" in filtered_task_definitions:
            parallel_agents.append(("backend", filtered_task_definitions.get("backend", [root_task])[0]))
        if "frontend" in filtered_task_definitions:
            parallel_agents.append(("frontend", filtered_task_definitions.get("frontend", [root_task])[0]))

        if parallel_agents:
            for name, _ in parallel_agents:
                if await _check_swarm_stop(name):
                    return {"status": "stopped", "reason": f"Stopped by user before {name}"}

            logger.info("[Swarm] Launching parallel agents: %s", [n for n, _ in parallel_agents])
            await self._publish_agent_event(
                "system", "info", f"Launching parallel agents: {[n for n, _ in parallel_agents]}"
            )

            async def _run_with_name(name: str, task: str):
                return name, await self._run_single_agent(name, task)

            results = await asyncio.gather(
                *[_run_with_name(name, task) for name, task in parallel_agents],
                return_exceptions=True,
            )

            for result in results:
                if isinstance(result, Exception):
                    msg = f"Parallel agent failed with exception: {result}"
                    logger.error("[Swarm] %s", msg)
                    await self._publish_agent_event("system", "error", msg)
                    return {"status": "error", "error": msg}

                name, ok = result
                if not ok:
                    msg = f"Specialist agents failed: {name}"
                    logger.error("[Swarm] %s", msg)
                    await self._publish_agent_event(
                        "system", "error", msg, {"failed_agents": [name]}
                    )
                    return {"status": "error", "error": msg}

                selected_agents.append(name)
                self._code_agents_completed.add(name)

                barrier = await self._verify_stage_barrier([name])
                if barrier:
                    logger.error("[Swarm] %s barrier failed: %s", name, barrier)
                    await self._publish_agent_event("system", "error", barrier)
                    return {"status": "error", "error": barrier}

                claim_types = {
                    "backend": [ClaimType.BACKEND_RUNTIME_READY.value, ClaimType.BACKEND_API_READY.value],
                    "frontend": [ClaimType.FRONTEND_SOURCE_READY.value, ClaimType.FRONTEND_BUILD_READY.value],
                }
                claim_error = await self._ensure_valid_claims_with_recovery(
                    claim_types[name], publish_if_missing=False,
                )
                if claim_error:
                    logger.error("[Swarm] %s claim barrier failed: %s", name, claim_error)
                    await self._publish_agent_event("system", "error", claim_error)
                    return {"status": "error", "error": claim_error}

        # Phase 3: DevOps — hard claim barrier (requires backend + frontend claims)
        if "devops" in filtered_task_definitions:
            if await _check_swarm_stop("devops"):
                return {"status": "stopped", "reason": "Stopped by user before devops"}

            required_claims = []
            if "backend" in filtered_task_definitions:
                required_claims.extend([
                    ClaimType.BACKEND_RUNTIME_READY.value,
                    ClaimType.BACKEND_API_READY.value,
                ])
            if "frontend" in filtered_task_definitions:
                required_claims.extend([
                    ClaimType.FRONTEND_SOURCE_READY.value,
                    ClaimType.FRONTEND_BUILD_READY.value,
                ])

            if required_claims:
                claim_error = await self._ensure_valid_claims_with_recovery(
                    required_claims, publish_if_missing=False,
                )
                if claim_error:
                    logger.error("[Swarm] DevOps hard claim barrier failed: %s", claim_error)
                    await self._publish_agent_event(
                        "system", "error", f"DevOps blocked — missing claims: {claim_error}"
                    )
                    return {"status": "error", "error": f"DevOps blocked: {claim_error}"}

            devops_ok = await self._run_single_agent(
                "devops", filtered_task_definitions.get("devops", [root_task])[0]
            )
            if not devops_ok:
                msg = "Specialist agents failed: devops"
                logger.warning("[Swarm] %s — continuing to packager", msg)
                await self._publish_agent_event("system", "warning", msg, {"failed_agents": ["devops"]})
            else:
                selected_agents.append("devops")

            claim_error = await self._ensure_valid_claims_with_recovery(
                [ClaimType.DEPLOYMENT_READY.value], publish_if_missing=False,
            )
            if claim_error:
                logger.warning("[Swarm] Deployment claim barrier failed: %s — continuing to packager", claim_error)
                await self._publish_agent_event("system", "warning", f"Deployment claim failed: {claim_error}")

        if "packager" not in filtered_task_definitions:
            logger.info("[Swarm] Skipping packager — no code changes were made")
            return {"status": "complete"}

        # Phase 4: Packager — verify all claims before packaging
        all_claims = []
        if "backend" in filtered_task_definitions:
            all_claims.extend([
                ClaimType.BACKEND_RUNTIME_READY.value,
                ClaimType.BACKEND_API_READY.value,
            ])
        if "frontend" in filtered_task_definitions:
            all_claims.extend([
                ClaimType.FRONTEND_SOURCE_READY.value,
                ClaimType.FRONTEND_BUILD_READY.value,
            ])
        if "devops" in filtered_task_definitions and "devops" in selected_agents:
            all_claims.append(ClaimType.DEPLOYMENT_READY.value)

        if all_claims:
            claim_error = await self._ensure_valid_claims_with_recovery(
                all_claims, publish_if_missing=False,
            )
            if claim_error:
                logger.error("[Swarm] Packager claim barrier failed: %s", claim_error)
                await self._publish_agent_event("system", "error", f"Packager blocked: {claim_error}")
                emergency = await self._run_emergency_packager()
                if emergency.get("status") == "complete":
                    return {
                        "status": "complete",
                        "warning": f"Packager claim barrier failed: {claim_error}. Emergency packaging succeeded.",
                    }
                return {
                    "status": "error",
                    "error": f"Packager claim barrier failed: {claim_error}. Emergency packaging also failed.",
                }

        barrier = await self._verify_packager_barrier(selected_agents, filtered_task_definitions)
        if barrier:
            logger.error("[Swarm] Packager barrier failed: %s", barrier)
            await self._publish_agent_event("system", "error", barrier)
            emergency = await self._run_emergency_packager()
            if emergency.get("status") == "complete":
                return {
                    "status": "complete",
                    "warning": f"Packager barrier failed: {barrier}. Emergency packaging succeeded.",
                }
            return {
                "status": "error",
                "error": f"Packager barrier failed: {barrier}. Emergency packaging also failed.",
            }

        # 5. Finalization (Packager)
        logger.info("[Swarm] Finalizing with packager")
        packager_ok = await self._run_single_agent("packager", task_definitions.get(
            "packager",
            ["Verify all files are generated, create zip, and upload."]
        )[0])
        if packager_ok:
            self._packager_ran = True
            logger.info("[Swarm] Parallel swarm execution completed")
            return {"status": "complete"}

        # Packager failed — try emergency packaging once
        emergency = await self._run_emergency_packager()
        if emergency.get("status") == "complete":
            return {"status": "complete", "warning": "Primary packager failed but emergency packaging succeeded."}
        return {"status": "error", "error": "Packager failed and emergency packaging also failed."}

    async def _wait_for_stable_terminals(self, agent_names: List[str]):
        if not agent_names or PACKAGER_STABILIZATION_SECONDS <= 0:
            return

        terminal_times = [
            self._ensure_agent_state(agent_name).get("terminal_at")
            for agent_name in agent_names
        ]
        latest_terminal = max((t for t in terminal_times if t), default=None)
        if not latest_terminal:
            return

        elapsed = (datetime.now() - latest_terminal).total_seconds()
        remaining = PACKAGER_STABILIZATION_SECONDS - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _auto_finalize_todos(self, agent_name: str, work_log: WorkLog) -> None:
        """Mark relevant todos as completed after a successful agent run.

        Only todos whose work was actually performed (tracked in work_log)
        are auto-marked. Todos for unstarted work are left unchanged so the
        strict todo check can catch truly incomplete agents.
        """
        if not self.project_id:
            return
        try:
            todos = await get_agent_todos(self.project_id, agent_name)
            if not todos:
                return
            incomplete_indices = [
                i for i, todo in enumerate(todos)
                if todo.get("status") != "completed"
            ]
            if not incomplete_indices:
                return

            matched = 0
            for idx in incomplete_indices:
                todo_text = todos[idx].get("content", "")
                if work_log.matches_todo(todo_text):
                    todos[idx]["status"] = "completed"
                    matched += 1

            if matched == 0:
                return

            # Store updated list back to Redis
            from .tools.todo_tools import _get_todo_key, _publish_state_event
            import redis.asyncio as redis
            r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
            try:
                key = _get_todo_key(self.project_id, agent_name)
                await r.set(key, json.dumps(todos), ex=3600)
            finally:
                await r.aclose()

            await _publish_state_event(self.project_id, agent_name, todos)
            logger.info(
                "[Swarm] Auto-finalized %d/%d todos for %s (work-matched)",
                matched,
                len(incomplete_indices),
                agent_name,
            )
        except Exception as exc:
            logger.warning("[Swarm] Failed to auto-finalize todos for %s: %s", agent_name, exc)

    async def _force_complete_all_todos(self, agent_name: str) -> None:
        """Force-mark all remaining todos as completed after a successful agent run.

        Called after _auto_finalize_todos. Since claim verification is the quality
        gate, unmatched todos are bookkeeping gaps and must show as done.
        """
        if not self.project_id:
            return
        try:
            todos = await get_agent_todos(self.project_id, agent_name)
            if not todos:
                return
            remaining = [t for t in todos if t.get("status") != "completed"]
            if not remaining:
                return
            for todo in todos:
                todo["status"] = "completed"
            from .tools.todo_tools import _get_todo_key, _publish_state_event
            import redis.asyncio as _redis
            r = _redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
            try:
                await r.set(_get_todo_key(self.project_id, agent_name), json.dumps(todos), ex=3600)
            finally:
                await r.aclose()
            await _publish_state_event(self.project_id, agent_name, todos)
            logger.info("[Swarm] Force-completed %d remaining todos for %s", len(remaining), agent_name)
        except Exception as exc:
            logger.warning("[Swarm] Failed to force-complete todos for %s: %s", agent_name, exc)

    async def _verify_stage_barrier(self, agent_names: List[str]) -> str:
        await self._wait_for_stable_terminals(agent_names)
        for agent_name in agent_names:
            state = self._ensure_agent_state(agent_name)
            if state.get("status") != "complete":
                reason = state.get("inconsistent_reason")
                if reason:
                    return reason
                return f"{agent_name} is not terminal; current state is {state.get('status')}"
        return ""

    async def _verify_packager_barrier(
        self, agent_names: List[str], filtered_task_definitions: Dict[str, List[str]]
    ) -> str:
        """Return an error message if packaging would race unfinished work."""
        # Only require devops if RootDep explicitly selected it.
        app_agents = [agent for agent in agent_names if agent in {"backend", "frontend"}]
        if app_agents and "devops" in filtered_task_definitions and "devops" not in agent_names:
            return "devops was selected but did not complete before packager"
        # Check for incomplete todos even if agent status is "complete"
        for agent_name in agent_names:
            ok, reason = await self._agent_has_completed_todos(agent_name)
            if not ok:
                return f"{agent_name} reported completion with unfinished todos: {reason}"
        return await self._verify_stage_barrier(agent_names)

    async def _run_emergency_packager(self, task: str = "") -> dict[str, Any]:
        """Trigger the packager agent as a safety net when the normal pipeline
        aborts after code agents have completed but before packaging ran.

        Returns the result dict from the packager run.
        """
        if self._packager_ran:
            return {"status": "skipped", "reason": "Packager already ran"}
        if not self._code_agents_completed:
            return {"status": "skipped", "reason": "No code agents completed — nothing to package"}

        logger.warning(
            "[Swarm] Running emergency packager after pipeline abort. "
            "Code agents completed: %s",
            sorted(self._code_agents_completed),
        )
        await self._publish_agent_event(
            "system",
            "warning",
            f"Emergency packaging triggered. Completed agents: {sorted(self._code_agents_completed)}",
            {"completed_agents": sorted(self._code_agents_completed)},
        )

        packager_task = task or "Emergency packaging: verify project structure, create zip, and upload to storage."
        packager_ok = await self._run_single_agent("packager", packager_task)
        if packager_ok:
            self._packager_ran = True
            logger.info("[Swarm] Emergency packager succeeded")
            return {"status": "complete", "source": "emergency_packager"}
        logger.error("[Swarm] Emergency packager failed")
        return {"status": "error", "error": "Emergency packager failed"}

    # -----------------------------------------------------------------------
    # Phase 9: Legacy dependency signaling removed.
    # Agents use publish_claim / wait_for_claim exclusively.
    # -----------------------------------------------------------------------

    async def _run_single_agent(self, agent_name: str, task: str) -> bool:
        """Run a single agent as an independent task and stream its events.

        Returns True on success, False on failure.
        """
        # Phase 5: Block quarantined agents from running
        state = self._ensure_agent_state(agent_name)
        if state.get("status") == "quarantined":
            reason = state.get("inconsistent_reason", "Agent is quarantined")
            logger.error("[Swarm] Agent %s is quarantined and cannot run: %s", agent_name, reason)
            await self._publish_agent_event(
                agent_name,
                "error",
                f"Agent {agent_name} blocked: {reason}",
                {"reason": reason, "status": "quarantined"},
            )
            return False

        agent = self.agents.get(agent_name)
        if not agent:
            logger.error(f"[Swarm] Agent {agent_name} not found")
            return False

        # Set agent name in context so todo tools know who is calling
        set_agent_name(agent_name)
        await clear_agent_final(self.project_id, agent_name)
        from .tools.workspace_tools import set_agent_workspace_scope, set_project_context
        set_project_context(self.project_id)
        set_agent_workspace_scope(agent_name)
        self._set_agent_status(agent_name, "active")

        # Pre-flight stop check — don't even start streaming if stop was requested
        # while the previous agent was finishing.
        from .tools.user_directive import is_swarm_stopped
        if await is_swarm_stopped(self.project_id):
            logger.info("[Swarm] Stop flag detected before starting agent=%s — aborting", agent_name)
            self._set_agent_status(agent_name, "stopped", "Swarm stopped by user before start")
            await self._publish_agent_event(
                agent_name, "stopped", "Stopped by user before start"
            )
            return False

        logger.info(f"[Swarm] Starting agent task: {agent_name}")

        expected_steps = {
            "rootdep": 4,
            "backend": 3,
            "frontend": 3,
            "devops": 2,
            "packager": 4,
        }
        total_steps = expected_steps.get(agent_name, 3)
        completed_steps = 0
        last_emitted_percent = 0  # monotonic clamp — percent never goes backwards

        await self._publish_agent_event(
            agent_name,
            "progress",
            f"{agent_name.capitalize()} started",
            {"percent": 0, "completed_steps": 0, "total_steps": total_steps}
        )

        built_context = await self.context_builder.build_agent_input(
            project_id=self.project_id,
            agent_name=agent_name,
            user_request=self.user_request or task,
            task=task,
            context_mode=self.context_mode,
        )
        initial_input = {"messages": [HumanMessage(content=built_context.content)]}

        await self._publish_agent_event(
            agent_name,
            "context_built",
            f"{agent_name.capitalize()} context built",
            {
                "estimated_tokens": built_context.estimated_tokens,
                "rag_chunks": built_context.rag_chunks,
                "file_excerpt_count": built_context.file_excerpt_count,
                "compacted": built_context.compacted,
                "summary_id": built_context.summary_id,
                "sources": built_context.sources,
                "context_mode": self.context_mode,
            },
        )

        if built_context.compacted:
            await self._publish_agent_event(
                agent_name,
                "context_compacted",
                f"{agent_name.capitalize()} context compacted before invocation",
                {
                    "estimated_tokens": built_context.estimated_tokens,
                    "summary_id": built_context.summary_id,
                },
            )

        recursion_limit = SWARM_RECURSION_LIMIT
        attempt = 0
        event_buffer: List[Dict[str, Any]] = []
        checkpoint_tracker = CheckpointTracker(self.project_id, agent_name)

        work_log = WorkLog()

        while attempt <= MAX_RECURSION_RETRIES:
            config = {
                "configurable": {"thread_id": f"{self.project_id}-{agent_name}"},
                "metadata": {"agent_name": agent_name},
                "recursion_limit": recursion_limit,
            }

            thinking_accumulator = []
            
            async def flush_thinking():
                if thinking_accumulator:
                    combined = "".join(thinking_accumulator)
                    event_buffer.append({
                        "type": "thinking",
                        "content": combined,
                        "agent_name": agent_name,
                    })
                    await self._publish_agent_event(
                        agent_name,
                        "thinking",
                        combined
                    )
                    thinking_accumulator.clear()

            try:
                stream = agent.astream_events(initial_input, config, version="v2").__aiter__()
                while True:
                    try:
                        event = await asyncio.wait_for(
                            stream.__anext__(),
                            timeout=AGENT_IDLE_TIMEOUT_SECONDS,
                        )
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        checkpoint_info = await checkpoint_tracker.create_checkpoint(self, event_buffer)
                        error_summary = (
                            f"Agent idle timeout after {AGENT_IDLE_TIMEOUT_SECONDS}s without events. "
                            f"Partial progress saved: iteration {checkpoint_info.get('iteration')}, "
                            f"{len(checkpoint_tracker.files_created)} files created."
                        )
                        await self._publish_agent_event(
                            agent_name,
                            "checkpoint_on_error",
                            error_summary,
                            {
                                **checkpoint_info,
                                "error_details": {
                                    "type": "IdleTimeout",
                                    "message": error_summary,
                                    "timeout_seconds": AGENT_IDLE_TIMEOUT_SECONDS,
                                },
                            },
                        )
                        logger.error("[Swarm] %s", error_summary)
                        self._set_agent_status(agent_name, "failed", error_summary)
                        await self._publish_agent_event(
                            agent_name,
                            "error",
                            error_summary,
                            {"timeout_seconds": AGENT_IDLE_TIMEOUT_SECONDS, "type": "IdleTimeout"},
                        )
                        return False

                    event_type = event.get("event", "")
                    name = event.get("name", "")

                    # Check swarm stop flag at natural boundaries:
                    # - tool_start: abort before expensive operations
                    # - tool_end: abort after completing current operation
                    # - chat_model_start: abort before long LLM generation
                    # We intentionally skip chat_model_stream (too frequent — Redis O(1) still adds up).
                    if event_type in ("on_tool_start", "on_tool_end", "on_chat_model_start"):
                        from .tools.user_directive import is_swarm_stopped
                        if await is_swarm_stopped(self.project_id):
                            logger.info("[Swarm] Stop flag detected in agent=%s event loop (event=%s)", agent_name, event_type)
                            self._set_agent_status(agent_name, "stopped", "Swarm stopped by user")
                            await self._publish_agent_event(
                                agent_name, "stopped", "Stopped by user request"
                            )
                            return False

                    # Capture reasoning/thinking
                    if event_type == "on_chat_model_stream":
                        content = event.get("data", {}).get("chunk", {}).content
                        if content:
                            thinking_accumulator.append(content)
                            if len(thinking_accumulator) >= 20: # Flush every 20 tokens
                                await flush_thinking()

                    if event_type == "on_tool_end":
                        await flush_thinking()
                        tool_output = event.get("data", {}).get("output", {})
                        file_path = None
                        if name == "write_file" and isinstance(tool_output, dict):
                            file_path = tool_output.get("file_path") or tool_output.get("path")
                        work_log.record_tool(name, tool_output)
                        event_buffer.append({
                            "type": "tool_call",
                            "tool": name,
                            "content": f"Completed {name}",
                            "output": tool_output,
                        })
                        completed_steps += 1
                        if completed_steps > total_steps:
                            total_steps = completed_steps + 1
                        raw_percent = min(int((completed_steps / total_steps) * 90), 90)
                        percent = max(raw_percent, last_emitted_percent)
                        last_emitted_percent = percent

                        logger.info(f"[Swarm] {agent_name} completed tool: {name} ({completed_steps}/{total_steps})")
                        await self._publish_agent_event(
                            agent_name,
                            "tool_call",
                            f"Completed {name}",
                            {"tool": name, "output": tool_output}
                        )

                        # Emit dedicated file_created so the frontend file explorer
                        # can refresh in real-time without polling.
                        if name == "write_file" and file_path and isinstance(tool_output, dict) and tool_output.get("status") == "success":
                            await self._publish_agent_event(
                                agent_name,
                                "file_created",
                                file_path,
                                {
                                    "file_path": file_path,
                                    "bytes_written": tool_output.get("bytes_written", 0),
                                    "agent": agent_name,
                                },
                            )
                        elif name == "create_directory" and isinstance(tool_output, dict) and tool_output.get("status") == "success":
                            directory_path = tool_output.get("directory") or tool_output.get("path")
                            if directory_path:
                                await self._publish_agent_event(
                                    agent_name,
                                    "directory_created",
                                    str(directory_path),
                                    {
                                        "directory_path": directory_path,
                                        "agent": agent_name,
                                    },
                                )
                        await self._publish_agent_event(
                            agent_name,
                            "progress",
                            f"{agent_name.capitalize()}: {name} done ({completed_steps}/{total_steps})",
                            {"percent": percent, "completed_steps": completed_steps, "total_steps": total_steps}
                        )

                        if checkpoint_tracker.tick(tool_name=name, file_path=file_path):
                            checkpoint_info = await checkpoint_tracker.create_checkpoint(self, event_buffer)
                            await self._publish_agent_event(
                                agent_name,
                                "checkpoint",
                                f"Checkpoint created at iteration {checkpoint_info.get('iteration')}",
                                checkpoint_info,
                            )

                        compacted_events = await self.context_builder.compact_and_save_events(
                            self.project_id,
                            agent_name,
                            event_buffer,
                        )
                        if compacted_events:
                            await self._publish_agent_event(
                                agent_name,
                                "context_compacted",
                                f"{agent_name.capitalize()} event context compacted",
                                compacted_events,
                            )
                            event_buffer.clear()

                    elif event_type == "on_tool_start":
                        await flush_thinking()
                        tool_input = event.get("data", {}).get("input", {})
                        event_buffer.append({
                            "type": "tool_start",
                            "tool": name,
                            "content": f"Starting {name}",
                            "input": tool_input,
                        })
                        logger.info(f"[Swarm] {agent_name} started tool: {name}")
                        await self._publish_agent_event(
                            agent_name,
                            "tool_start",
                            f"Starting {name}",
                            {"tool": name, "input": tool_input}
                        )
                        if name == "write_file" and isinstance(tool_input, dict):
                            file_path = tool_input.get("file_path") or tool_input.get("path")
                            content = tool_input.get("content")
                            if file_path and isinstance(content, str):
                                await self._publish_agent_event(
                                    agent_name,
                                    "file_modified",
                                    str(file_path),
                                    {
                                        "file_path": file_path,
                                        "content": content,
                                        "bytes_planned": len(content),
                                        "agent": agent_name,
                                        "phase": "preview",
                                    },
                                )

                await flush_thinking()

                # Auto-finalize todos that match work recorded in work_log,
                # then force-complete any remainder so the frontend shows a
                # clean state. The real quality gate is claim verification.
                await self._auto_finalize_todos(agent_name, work_log)
                await self._force_complete_all_todos(agent_name)

                self._set_agent_status(agent_name, "finalizing")
                await self._publish_agent_event(
                    agent_name,
                    "progress",
                    f"{agent_name.capitalize()} complete",
                    {"percent": 100, "completed_steps": completed_steps, "total_steps": completed_steps}
                )
                from .tools.workspace_tools import lock_agent_workspace_writes
                lock_agent_workspace_writes()
                await mark_agent_final(self.project_id, agent_name)
                await self._publish_agent_event(
                    agent_name,
                    "complete",
                    f"{agent_name.capitalize()} task complete"
                )
                self._set_agent_status(agent_name, "complete")
                logger.info(f"[Swarm] Agent task complete: {agent_name}")
                return True

            except GraphRecursionError:
                checkpoint_info = await checkpoint_tracker.create_checkpoint(self, event_buffer)
                await self._publish_agent_event(
                    agent_name,
                    "checkpoint_before_retry",
                    f"Checkpoint before retry #{attempt}: iteration {checkpoint_info.get('iteration')}",
                    checkpoint_info,
                )
                attempt += 1
                if attempt > MAX_RECURSION_RETRIES:
                    msg = (
                        f"[Swarm] Agent {agent_name} exhausted all retries. "
                        f"Final recursion limit was {recursion_limit}. "
                        f"Checkpoint saved at iteration {checkpoint_tracker.iteration} "
                        f"with {len(checkpoint_tracker.files_created)} files created."
                    )
                    logger.error(msg)
                    self._set_agent_status(agent_name, "failed", msg)
                    await self._publish_agent_event(agent_name, "error", msg)
                    return False

                new_limit = recursion_limit * 2
                logger.warning(
                    f"[Swarm] Agent {agent_name} hit recursion limit ({recursion_limit}). "
                    f"Auto-increasing to {new_limit} and retrying "
                    f"(attempt {attempt}/{MAX_RECURSION_RETRIES})..."
                )
                await self._publish_agent_event(
                    agent_name,
                    "retry",
                    f"Recursion limit hit. Increasing to {new_limit} and retrying...",
                )
                recursion_limit = new_limit

            except Exception as e:
                import traceback
                error_details = {
                    "type": type(e).__name__,
                    "message": str(e) or "(empty message)",
                    "args": list(e.args) if e.args else [],
                    "traceback": traceback.format_exc(),
                }
                checkpoint_info = await checkpoint_tracker.create_checkpoint(self, event_buffer)
                error_summary = (
                    f"Partial progress saved: iteration {checkpoint_info.get('iteration')}, "
                    f"{len(checkpoint_tracker.files_created)} files created. "
                    f"Error type: {error_details['type']}, message: {error_details['message']}"
                )
                await self._publish_agent_event(
                    agent_name,
                    "checkpoint_on_error",
                    error_summary,
                    {**checkpoint_info, "error_details": error_details},
                )
                logger.error(
                    f"[Swarm] Error in agent task {agent_name}: "
                    f"{error_details['type']}: {error_details['message']}\n"
                    f"{error_details['traceback']}"
                )
                self._set_agent_status(agent_name, "failed", error_summary)
                await self._publish_agent_event(
                    agent_name,
                    "error",
                    f"{error_details['type']}: {error_details['message']}",
                    error_details,
                )
                return False

    async def shutdown(self):
        logger.info("[Swarm] Shutting down...")
        if self._postgres_conn is not None:
            try:
                await self._postgres_conn.close()
                logger.info("[Swarm] Closed PostgresSaver connection")
            except Exception as e:
                logger.warning(f"[Swarm] Error closing PostgresSaver connection: {e}")
        if self._owns_blackboard:
            await self.blackboard.disconnect()
            logger.info("[Swarm] Disconnected from Redis")


async def create_swarm_execution(
    project_id: str,
    project_spec: Dict[str, Any],
    tasks: Dict[str, List[str]],
    llm_provider: str = "minimax",
) -> Dict[str, Any]:
    logger.info(f"[create_swarm_execution] Starting for project: {project_id}")

    swarm = AgentSwarm(llm_provider=llm_provider)
    await swarm.initialize(project_id, project_spec)

    try:
        logger.info("[create_swarm_execution] Starting swarm execution")
        result = await swarm.execute_parallel(tasks)

        logger.info("[create_swarm_execution] Swarm execution finished")
        return {
            "project_id": project_id,
            "status": "complete",
            "result": result,
            "agents": list(swarm.agents.keys()),
        }
    finally:
        await swarm.shutdown()
        logger.info("[create_swarm_execution] Swarm shutdown complete")
