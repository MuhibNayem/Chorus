import os
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from langchain_core.messages import HumanMessage, AIMessage
from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError

from ..llm.minimax import get_llm
from ..blackboard.redis_blackboard import RedisBlackboard
from .tools.todo_tools import write_todos, update_todo_status, set_agent_name

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger("swarm")

SWARM_RECURSION_LIMIT = int(os.environ.get("SWARM_RECURSION_LIMIT", "5000"))
MAX_RECURSION_RETRIES = int(os.environ.get("SWARM_MAX_RECURSION_RETRIES", "3"))


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
    ):
        self.llm_provider = llm_provider
        self.blackboard = blackboard or RedisBlackboard()
        self.agents: Dict[str, Any] = {}
        self.project_id: Optional[str] = None
        logger.info("AgentSwarm instance created")

    async def initialize(self, project_id: str, project_spec: Dict[str, Any]):
        self.project_id = project_id
        logger.info(f"[Swarm] Initializing swarm for project: {project_id}")

        await self.blackboard.connect()
        logger.info("[Swarm] Connected to Redis blackboard")

        # Clean up abandoned workspaces before starting a new project
        from .tools.workspace_tools import cleanup_old_workspaces
        cleanup_old_workspaces()

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
            llm = get_llm(self.llm_provider)

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
                system_prompt=prompt,
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

        user_request = task_definitions.get("rootdep", [""])[0]

        logger.info(f"[Swarm] Starting true parallel swarm execution for: {self.project_id}")

        # 1. RootDep Analysis & Plan
        rootdep_ok = await self._run_single_agent("rootdep", f"Initial Request: {user_request}")
        if not rootdep_ok:
            logger.error("[Swarm] RootDep failed — aborting pipeline")
            await self.blackboard.publish_agent_event(
                self.project_id,
                "rootdep",
                "error",
                "RootDep failed to generate the project specification. Pipeline aborted.",
            )
            return {"status": "error", "error": "RootDep failed"}

        # 2. Parallel Generation (Backend, Frontend, DevOps)
        logger.info("[Swarm] Launching parallel specialists: backend, frontend, devops")

        results = await asyncio.gather(
            self._run_single_agent("backend", user_request),
            self._run_single_agent("frontend", user_request),
            self._run_single_agent("devops", f"Generate devops for the project based on: {user_request}")
        )

        if not any(results):
            logger.error("[Swarm] All parallel agents failed")
            return {"status": "error", "error": "All specialist agents failed"}

        # 3. Finalization (Packager)
        logger.info("[Swarm] Finalizing with packager")
        await self._run_single_agent("packager", "Verify all files are generated, create zip, and upload.")

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

        initial_input = {"messages": [HumanMessage(content=task)]}
        recursion_limit = SWARM_RECURSION_LIMIT
        attempt = 0

        while attempt <= MAX_RECURSION_RETRIES:
            config = {
                "configurable": {"thread_id": f"{self.project_id}-{agent_name}"},
                "metadata": {"agent_name": agent_name},
                "recursion_limit": recursion_limit,
            }

            try:
                async for event in agent.astream_events(initial_input, config, version="v2"):
                    event_type = event.get("event", "")
                    name = event.get("name", "")

                    # Capture reasoning/thinking
                    if event_type == "on_chat_model_stream":
                        content = event.get("data", {}).get("chunk", {}).content
                        if content:
                            await self.blackboard.publish_agent_event(
                                self.project_id,
                                agent_name,
                                "thinking",
                                content
                            )

                    if event_type == "on_tool_end":
                        tool_output = event.get("data", {}).get("output", {})
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

                    elif event_type == "on_tool_start":
                        tool_input = event.get("data", {}).get("input", {})
                        logger.info(f"[Swarm] {agent_name} started tool: {name}")
                        await self.blackboard.publish_agent_event(
                            self.project_id,
                            agent_name,
                            "tool_start",
                            f"Starting {name}",
                            {"tool": name, "input": tool_input}
                        )

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
                attempt += 1
                if attempt > MAX_RECURSION_RETRIES:
                    msg = (
                        f"[Swarm] Agent {agent_name} exhausted all retries. "
                        f"Final recursion limit was {recursion_limit}."
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
                logger.error(f"[Swarm] Error in agent task {agent_name}: {e}")
                await self.blackboard.publish_agent_event(
                    self.project_id,
                    agent_name,
                    "error",
                    str(e)
                )
                return False

    async def shutdown(self):
        logger.info("[Swarm] Shutting down...")
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
