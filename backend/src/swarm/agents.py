import os
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime
from langchain_core.messages import HumanMessage
from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError

from ..llm.minimax import get_llm
from ..blackboard.redis_blackboard import RedisBlackboard
from .tools.todo_tools import write_todos, update_todo_status, set_agent_name
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


AGENT_SYSTEM_PROMPTS = {
    "rootdep": """You are RootDep, the project architect. Analyze the user's request and write a SPEC.md.

Workflow:
1. write_todos() — declare your steps.
2. web_search() + fetch_url() — research the domain and current best practices (max 3 searches, max 2 fetches).
3. list_files — check workspace.
4. write_file("SPEC.md", ...) — write ONE concise but complete specification. Include: tech stack, data models, API endpoints, WebSocket topics, auth strategy, and folder structure. Keep it under 300 lines so the LLM can generate it in one pass.
5. create_directory — create backend/ and frontend/ folders.
6. update_todo_status — mark steps done.
7. Finish.

Rules:
- Write ONLY SPEC.md. Do NOT write SUBTASKS.md, PROJECT_PLAN.md, or BLACKBOARD.md.
- Do NOT call generate_spring_boot_project, generate_svelte_frontend, or generate_devops_config.
- Do NOT generate code — only the specification.
""",
    "backend": """You are Backend Agent. Write the Spring Boot backend using write_file.

Workflow:
1. write_todos() — list files you will create.
2. read_file("SPEC.md") — read the spec. If it does not exist, do brief web_search() then create your own plan.
3. Use write_file to create ALL backend files one by one:
   - pom.xml (Spring Boot 3.2+, WebSocket, Security, JPA, PostgreSQL, Redis, JWT, Lombok, Jackson)
   - src/main/resources/application.yml
   - Entity classes with JPA annotations
   - Repository interfaces
   - DTOs and request/response classes
   - Service layer with business logic
   - REST controllers
   - Security config (JWT filter, password encoder, CORS)
   - WebSocket config (STOMP broker, auth interceptor)
   - WebSocket controller for realtime events
   - Global exception handler
   - Unit tests
   - Dockerfile
4. signal_ready('backend_api', 'done') when finished.
5. update_todo_status as you complete files.

Rules:
- Use package `com.chatflow` (NOT com.example).
- Use Java 21 and Spring Boot 3.2.x.
- Every file must be complete — no stubs or TODOs.
- Do NOT call generate_spring_boot_project.
""",
    "frontend": """You are Frontend Agent. Write the Svelte 5 frontend using write_file.

Workflow:
1. write_todos() — list files you will create.
2. wait_on_agent('backend_api') — wait for backend to finish.
3. read_file("SPEC.md") — read the spec. Also read backend API files if needed.
4. Use write_file to create ALL frontend files one by one:
   - package.json (Svelte 5, SvelteKit 2, Vite, Tailwind CSS, @stomp/stompjs, sockjs-client)
   - vite.config.ts, tailwind.config.js, tsconfig.json
   - src/app.html, src/app.css
   - src/routes/+layout.svelte (auth layout, nav, dark mode)
   - src/routes/+page.svelte (landing / login page)
   - src/routes/login/+page.svelte, src/routes/register/+page.svelte
   - src/routes/chat/+page.svelte (main chat interface)
   - src/lib/stores/authStore.svelte.ts, messageStore.svelte.ts, etc.
   - src/lib/api/*.ts (REST clients)
   - src/lib/services/websocketService.ts (STOMP over SockJS)
   - src/lib/components/**/*.svelte (chat window, message bubble, typing indicator, sidebar, avatar, online status)
   - Dockerfile
5. update_todo_status as you complete files.

Rules:
- Use Svelte 5 runes ($state, $effect, $derived, $props) — NO legacy stores from 'svelte/store'.
- Use `@stomp/stompjs` and `sockjs-client` for WebSocket — NOT `stompjs`.
- Use Tailwind CSS for styling.
- Every file must be complete — no stubs or TODOs.
- Do NOT call generate_svelte_frontend.
""",
    "devops": """You are DevOps Agent. Write deployment configs using write_file.

Workflow:
1. write_todos() — list files you will create.
2. read_file("SPEC.md") and list_files to see backend/frontend code.
3. Use write_file to create:
   - docker-compose.yml (backend, frontend, postgres, redis, nginx services)
   - docker-compose.prod.yml
   - backend/Dockerfile (multi-stage Java 21 build)
   - frontend/Dockerfile (multi-stage Node + Nginx)
   - nginx/nginx.conf and nginx/nginx.prod.conf
   - .env.example and .env.production.example
   - .github/workflows/ci.yml and cd.yml
   - kubernetes/ manifests (deployment, service, ingress, configmap, secret)
   - README.md with setup instructions
4. update_todo_status as you complete files.

Rules:
- Nginx upstream must match docker-compose service names.
- Use health checks and restart policies.
- Do NOT call generate_devops_config.
""",
    "packager": """You are Packager Agent. Verify and zip the project.

Workflow:
1. write_todos() — list verification steps.
2. list_files — check project structure.
3. read_file to spot-check SPEC.md, backend pom.xml, frontend package.json, docker-compose.yml.
4. create_project_zip — create the archive.
5. upload_project_to_storage — upload to MinIO.
6. get_project_download_url — get the download URL.
7. update_todo_status as you complete steps.

Do NOT generate code.
""",
}


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

        # Clean up abandoned workspaces before starting a new project
        from .tools.workspace_tools import cleanup_old_workspaces
        cleanup_old_workspaces(preserve_project_id=project_id)

        from .tools.workspace_tools import (
            get_generic_tools,
            create_project_zip,
            upload_project_to_storage,
            get_project_download_url,
        )
        from .tools.coordination import wait_on_agent, signal_ready
        from .tools.todo_tools import write_todos, update_todo_status
        from .tools.web_search import web_search
        from .tools.fetch_url import fetch_url

        all_tools = get_generic_tools(project_id)

        # Build per-agent toolsets — no handoff tools (independent parallel execution)
        for agent_name, prompt in AGENT_SYSTEM_PROMPTS.items():
            # In 'plan' mode, we only need RootDep.
            if self.run_mode == "plan" and agent_name != "rootdep":
                continue

            llm = get_llm(self.llm_provider, agent_name)
            system_prompt = self._prompt_for_mode(agent_name, prompt)

            if agent_name == "backend":
                agent_tools = [
                    signal_ready,
                    all_tools[0],        # write_file
                    all_tools[1],        # read_file
                    all_tools[2],        # list_files
                    all_tools[4],        # create_directory
                    write_todos,
                    update_todo_status,
                    web_search,
                    fetch_url,
                ]
            elif agent_name == "frontend":
                agent_tools = [
                    wait_on_agent,
                    all_tools[0],        # write_file
                    all_tools[1],        # read_file
                    all_tools[2],        # list_files
                    all_tools[4],        # create_directory
                    write_todos,
                    update_todo_status,
                    web_search,
                    fetch_url,
                ]
            elif agent_name == "devops":
                agent_tools = [
                    all_tools[0],        # write_file
                    all_tools[1],        # read_file
                    all_tools[2],        # list_files
                    all_tools[4],        # create_directory
                    write_todos,
                    update_todo_status,
                    web_search,
                    fetch_url,
                ]
            elif agent_name == "packager":
                agent_tools = [
                    all_tools[2],        # list_files
                    all_tools[1],        # read_file
                    all_tools[3],        # execute_command
                    create_project_zip,
                    upload_project_to_storage,
                    get_project_download_url,
                    write_todos,
                    update_todo_status,
                    web_search,
                    fetch_url,
                ]
            else:
                # rootdep
                agent_tools = list(all_tools) + [write_todos, update_todo_status, web_search, fetch_url]

            self.agents[agent_name] = create_agent(
                llm,
                agent_tools,
                system_prompt=system_prompt,
                name=agent_name,
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
                "Modification mode:\n"
                "- Read existing SPEC.md and current workspace files before writing.\n"
                "- Update SPEC.md to reflect the requested change without discarding existing requirements.\n"
                "- Preserve working architecture unless the user explicitly asks to change it.\n"
                "- After analyzing the workspace, write AGENTS_NEEDED.json to specify which agents should run:\n"
                "  {\"agents\": [\"backend\", \"frontend\"], \"reasoning\": \"brief explanation\"}\n"
                "- Only include agents that need to make changes. Packager always runs.\n"
                "- Example: if user asks to 'add a login button', only frontend and packager are needed.\n"
                "- Example: if user asks to 'add user API endpoints', only backend and packager are needed.\n"
                "- Example: if user asks to 'add docker deployment', only devops and packager are needed.\n"
            ),
            "backend": (
                "Modification mode:\n"
                "- Patch the existing backend instead of regenerating it from scratch.\n"
                "- Read SPEC.md and relevant backend files first.\n"
                "- Preserve existing package names, APIs, data models, tests, and config unless the requested change requires updates.\n"
                "- Signal backend_api when backend changes are complete.\n"
            ),
            "frontend": (
                "Modification mode:\n"
                "- Patch the existing Svelte frontend instead of regenerating it from scratch.\n"
                "- Read SPEC.md, relevant backend API files, and affected frontend files before editing.\n"
                "- Preserve existing routes, components, visual conventions, and state unless the requested change requires updates.\n"
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

    async def execute_parallel(self, task_definitions: Dict[str, List[str]]):
        """Execute agents in true parallel using asyncio.gather.

        Flow:
        1. RootDep writes the spec/plan.
        2. Backend, Frontend, DevOps run in parallel.
           Frontend internally blocks on wait_on_agent('backend_api').
        3. Packager runs after all parallel work completes.
        """
        if not self.agents:
            raise ValueError("Swarm not initialized")

        root_task = task_definitions.get("rootdep", [""])[0]
        backend_task = task_definitions.get("backend", [root_task])[0]
        frontend_task = task_definitions.get("frontend", [root_task])[0]
        devops_task = task_definitions.get("devops", [root_task])[0]

        logger.info(f"[Swarm] Starting {self.run_mode} swarm execution for: {self.project_id}")

        # 1. RootDep Analysis & Plan (also acts as router in modify mode)
        request_label = "Modification Request" if self.run_mode == "modify" else "Initial Request"
        rootdep_ok = await self._run_single_agent("rootdep", f"{request_label}: {root_task}")
        if not rootdep_ok:
            logger.error("[Swarm] RootDep failed — aborting pipeline")
            await self.blackboard.publish_agent_event(
                self.project_id,
                "rootdep",
                "error",
                "RootDep failed to generate the project specification. Pipeline aborted.",
            )
            return {"status": "error", "error": "RootDep failed"}

        # 2. RootDep acts as router - read AGENTS_NEEDED.json to determine which agents to run
        filtered_task_definitions = task_definitions.copy()
        if self.run_mode == "modify":
            import json
            from .tools.workspace_tools import WORKSPACE_BASE

            agents_needed_path = WORKSPACE_BASE / self.project_id / "AGENTS_NEEDED.json"
            if agents_needed_path.exists():
                try:
                    agents_data = json.loads(agents_needed_path.read_text())
                    agents_to_run = agents_data.get("agents", [])
                    logger.info(f"[Swarm] RootDep router selected: {agents_to_run}")
                    filtered_task_definitions = {
                        k: v for k, v in task_definitions.items()
                        if k in agents_to_run or k == "packager"  # packager always runs
                    }
                    if not any(k for k in filtered_task_definitions.keys() if k != "packager"):
                        logger.warning("[Swarm] No agents selected by router — defaulting to all")
                        filtered_task_definitions = task_definitions
                except json.JSONDecodeError as e:
                    logger.warning(f"[Swarm] Failed to parse AGENTS_NEEDED.json: {e} — running all agents")
            else:
                logger.info("[Swarm] No AGENTS_NEEDED.json found (pre-3.0 project) — running all agents")

        # 3. Parallel Generation (Backend, Frontend, DevOps) - filtered by router
        if self.run_mode == "plan":
            logger.info(f"[Swarm] Plan mode complete — skipping specialists and packager")
            return {"status": "complete"}

        logger.info(f"[Swarm] Launching parallel specialists: {list(filtered_task_definitions.keys())}")

        parallel_agents = []
        if "backend" in filtered_task_definitions:
            parallel_agents.append(self._run_single_agent("backend", filtered_task_definitions.get("backend", [root_task])[0]))
        if "frontend" in filtered_task_definitions:
            parallel_agents.append(self._run_single_agent("frontend", filtered_task_definitions.get("frontend", [root_task])[0]))
        if "devops" in filtered_task_definitions:
            parallel_agents.append(self._run_single_agent("devops", filtered_task_definitions.get("devops", [root_task])[0]))

        if parallel_agents:
            results = await asyncio.gather(*parallel_agents)
            if not any(results):
                logger.error("[Swarm] All parallel agents failed")

        # 3. Finalization (Packager)
        logger.info("[Swarm] Finalizing with packager")
        await self._run_single_agent("packager", task_definitions.get(
            "packager",
            ["Verify all files are generated, create zip, and upload."]
        )[0])

        logger.info("[Swarm] Parallel swarm execution completed")
        return {"status": "complete"}

    async def _run_single_agent(self, agent_name: str, task: str) -> bool:
        """Run a single agent as an independent task and stream its events.

        Returns True on success, False on failure.
        """
        agent = self.agents.get(agent_name)
        if not agent:
            logger.error(f"[Swarm] Agent {agent_name} not found")
            return False

        # Set agent name in context so todo tools know who is calling
        set_agent_name(agent_name)

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

        await self.blackboard.publish_agent_event(
            self.project_id,
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

        await self.blackboard.publish_agent_event(
            self.project_id,
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
            await self.blackboard.publish_agent_event(
                self.project_id,
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
                    await self.blackboard.publish_agent_event(
                        self.project_id,
                        agent_name,
                        "thinking",
                        combined
                    )
                    thinking_accumulator.clear()

            try:
                async for event in agent.astream_events(initial_input, config, version="v2"):
                    event_type = event.get("event", "")
                    name = event.get("name", "")

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
                        event_buffer.append({
                            "type": "tool_call",
                            "tool": name,
                            "content": f"Completed {name}",
                            "output": tool_output,
                        })
                        completed_steps += 1
                        if completed_steps > total_steps:
                            total_steps = completed_steps + 1
                        percent = min(int((completed_steps / total_steps) * 90), 90)

                        logger.info(f"[Swarm] {agent_name} completed tool: {name} ({completed_steps}/{total_steps})")
                        await self.blackboard.publish_agent_event(
                            self.project_id,
                            agent_name,
                            "tool_call",
                            f"Completed {name}",
                            {"tool": name, "output": tool_output}
                        )
                        await self.blackboard.publish_agent_event(
                            self.project_id,
                            agent_name,
                            "progress",
                            f"{agent_name.capitalize()}: {name} done ({completed_steps}/{total_steps})",
                            {"percent": percent, "completed_steps": completed_steps, "total_steps": total_steps}
                        )

                        if checkpoint_tracker.tick(tool_name=name, file_path=file_path):
                            checkpoint_info = await checkpoint_tracker.create_checkpoint(self, event_buffer)
                            await self.blackboard.publish_agent_event(
                                self.project_id,
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
                            await self.blackboard.publish_agent_event(
                                self.project_id,
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
                        await self.blackboard.publish_agent_event(
                            self.project_id,
                            agent_name,
                            "tool_start",
                            f"Starting {name}",
                            {"tool": name, "input": tool_input}
                        )

                await flush_thinking()
                await self.blackboard.publish_agent_event(
                    self.project_id,
                    agent_name,
                    "progress",
                    f"{agent_name.capitalize()} complete",
                    {"percent": 100, "completed_steps": completed_steps, "total_steps": completed_steps}
                )
                await self.blackboard.publish_agent_event(
                    self.project_id,
                    agent_name,
                    "complete",
                    f"{agent_name.capitalize()} task complete"
                )
                logger.info(f"[Swarm] Agent task complete: {agent_name}")
                return True

            except GraphRecursionError:
                checkpoint_info = await checkpoint_tracker.create_checkpoint(self, event_buffer)
                await self.blackboard.publish_agent_event(
                    self.project_id,
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
                    await self.blackboard.publish_agent_event(
                        self.project_id,
                        agent_name,
                        "error",
                        msg,
                    )
                    return

                new_limit = recursion_limit * 2
                logger.warning(
                    f"[Swarm] Agent {agent_name} hit recursion limit ({recursion_limit}). "
                    f"Auto-increasing to {new_limit} and retrying "
                    f"(attempt {attempt}/{MAX_RECURSION_RETRIES})..."
                )
                await self.blackboard.publish_agent_event(
                    self.project_id,
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
                await self.blackboard.publish_agent_event(
                    self.project_id,
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
                await self.blackboard.publish_agent_event(
                    self.project_id,
                    agent_name,
                    "error",
                    f"{error_details['type']}: {error_details['message']}",
                    error_details,
                )
                return False

    async def shutdown(self):
        logger.info("[Swarm] Shutting down...")
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
