# Chorus — AI Agent Swarm Project Generator

## Complete Project Specification

**Version:** 1.0  
**Date:** 2026-05-05  
**Status:** Draft — Pending Implementation

---

## 1. Overview

### 1.1 Project Name

**DeepSeek** — AI Agent Swarm Project Generator

### 1.2 Core Functionality

A true decentralized agent swarm that generates production-ready projects from natural language descriptions. Users describe a project in plain English (e.g., "build a todo app with JWT auth and PostgreSQL"). The swarm autonomously generates:

- **Backend:** Spring Boot 4.x with Spring AI 2.0, JPA, Spring Security
- **Frontend:** Svelte 5 + SvelteKit + Tailwind 4 + shadcn-svelte + Lucide Icons
- **Infrastructure:** Dockerfile, Docker Compose, build scripts
- **Output Formats:** Downloadable ZIP archive + runnable Docker image

### 1.3 Target Users

Developers who want instant, production-ready project scaffolding without manual setup, configuration, or boilerplate coding.

### 1.4 Key Differentiator

This is a **true swarm** — not a supervisor/worker pattern. Agents are peers that communicate via a shared blackboard, dynamically delegate work via handoffs, and self-organize without a central controller.

---

## 2. Philosophy: True Swarm Architecture

### 2.1 Supervisor vs Swarm

| Aspect | Supervisor (Hierarchical) | True Swarm (Decentralized) |
|--------|---------------------------|----------------------------|
| Control | Central bottleneck | Peer-to-peer, no central controller |
| Communication | Vertical (up/down chain) | Horizontal (gossip/blackboard) |
| Role Assignment | Hardcoded roles | Dynamic (fluid role switching) |
| Failure Mode | Single point of failure | Self-healing (others take over) |
| Scalability | Limited by supervisor context | Infinite parallelism |
| Behavior | Pre-defined workflow | Emergent from local interactions |
| Inspiration | Corporate hierarchy | Ant colonies, bee swarms |

### 2.2 Biological Inspiration

True swarm intelligence is inspired by natural systems:

- **Ant colonies** — no CEO ant directing traffic; complex behavior emerges from simple local interactions
- **Bee swarms** — decentralized decision making via waggle dance (stigmergy)
- **Fish flocks** — coordinated movement from local rules, no leader
- **Termite mounds** — structure emerges from independent agents modifying environment

### 2.3 Swarm Principles Applied

| Principle | Implementation |
|-----------|----------------|
| **Local interaction** | Agents act on blackboard state, no global view |
| **Stigmergy** | Agents communicate via shared environment (Redis pub/sub) |
| **Emergence** | Complex project generation from simple agent rules |
| **Self-organization** | No central control; roles emerge based on task queue |
| **Adaptability** | Swarm responds to failures without re-architecture |

### 2.4 Why LangGraph Swarm (Not LangChain4j)

| Feature | LangGraph Swarm | LangChain4j |
|---------|-----------------|-------------|
| Architecture | Decentralized handoffs | Sequential/parallel workflows |
| Handoff mechanism | `create_handoff_tool()` | Not available |
| State management | Checkpointed state graphs | AgenticScope |
| Cycle support | Yes (cyclical graphs) | Limited to linear workflows |
| Checkpointing | SqliteSaver for pause/resume | Not available |
| True swarm behavior | **Yes** | **No (workflow only)** |

**Decision:** Use **LangGraph Swarm (Python)** for the orchestrator — required for true peer-to-peer agent handoffs.

### 2.5 A2A Protocol Role

A2A (Agent-to-Agent) is a **boundary protocol** for cross-organizational, cross-framework communication. It is NOT the internal swarm mechanism. Internal communication uses gossip/blackboard. A2A is used for:

- External agent integration
- Future multi-swarm communication
- Protocol standardization with other frameworks (CrewAI, Google ADK, etc.)

---

## 3. Technology Stack

### 3.1 Frontend

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Framework | Svelte 5 + SvelteKit | Latest (2026) | Reactive chat UI |
| Language | TypeScript | 5.6+ | Type safety |
| Styling | Tailwind CSS 4 | 4.0+ | Utility-first CSS |
| Components | shadcn-svelte | Latest | Accessible UI primitives |
| Icons | Lucide Icons | Latest | Consistent icon set |
| State | Svelte 5 Runes | — | `$state`, `$derived`, `$effect` |
| Real-time | SSE (EventSource) | Native | Server-to-client streaming |
| Protocol | AG-UI | v1 | Standardized event types |
| Build | Vite | 6.0+ | Fast builds |

### 3.2 Backend (Python)

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| Framework | FastAPI | 0.136+ | Async API + SSE |
| Runtime | Python | 3.11+ | Required for `get_stream_writer()` |
| Agent Framework | LangGraph + langgraph-swarm | 0.2.70+ | Swarm orchestration |
| LLM | MiniMax M2.7 | Latest | All agents powered by same model |
| Validation | Pydantic | v2 | Schema validation |
| HTTP Client | httpx | Latest | Async HTTP |
| WebSocket | fastapi+websockets | — | Future bidirectional |

### 3.3 Infrastructure

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Blackboard (Real-time)** | Redis | Task queue, pub/sub gossip, agent heartbeat, prompt cache |
| **Blackboard (Persistent)** | PostgreSQL + pgvector | Project metadata, file manifest, dependency graph, chat history, RAG vector store |
| **RAG Vector Store** | pgvector | Knowledge base embeddings for Spring Boot, Svelte, best practices |
| **Sandbox** | Seatbelt (macOS) / bubblewrap (Linux) | Per-project isolated workspace, no Docker overhead |
| **Message Broker** | Redis Pub/Sub | Agent-to-agent gossip |

### 3.4 RAG (Retrieval-Augmented Generation)

RAG enhances agent code generation by providing relevant knowledge from a vectorized corpus.

#### 3.4.1 Purpose

| Use Case | Description |
|---------|-------------|
| **Documentation Lookup** | Agents retrieve relevant Spring Boot 4, Svelte 5, Tailwind 4 docs when generating code |
| **Best Practices** | Vectorized best practices for architecture, security, performance |
| **Pattern Retrieval** | Similar past project patterns for reference |
| **Error Resolution** | Common error solutions retrieved when build/test fails |

#### 3.4.2 RAG Pipeline

```
User Request
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│                    RAG RETRIEVAL                             │
│  1. Parse user request → embedding                          │
│  2. Query pgvector for relevant docs                        │
│  3. Retrieve: Spring Boot patterns, Svelte patterns, etc.   │
│  4. Inject into agent context (relevant snippets only)     │
└─────────────────────────────────────────────────────────────┘
     │
     ▼
Agent Context (project spec + retrieved knowledge)
     │
     ▼
Code Generation (grounded in retrieved knowledge)
```

#### 3.4.3 Knowledge Base Corpus

| Corpus | Content | Embedding Model |
|--------|---------|-----------------|
| Spring Boot 4 Docs | REST, JPA, Security, AI integration | `nomic-embed-text` |
| Svelte 5 Docs | Components, runes, stores, routing | `nomic-embed-text` |
| Tailwind 4 Docs | Utility classes, dark mode, components | `nomic-embed-text` |
| Architecture Patterns | DDD, hexagonal, event-driven | `nomic-embed-text` |
| Security Best Practices | JWT, OAuth2, OWASP Top 10 | `nomic-embed-text` |
| Past Projects | Previously generated project metadata | `nomic-embed-text` |

#### 3.4.4 Vector Store Schema

```sql
-- Documents table (source of truth)
CREATE TABLE rag_documents (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,          -- 'spring-boot', 'svelte', 'pattern', etc.
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    metadata JSONB,                        -- tags, date, version
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Embeddings table (pgvector)
CREATE TABLE rag_embeddings (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES rag_documents(id),
    embedding vector(1536),               -- nomic-embed-text dimensions
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for similarity search
CREATE INDEX idx_rag_embeddings_cosine ON rag_embeddings USING cosine(embedding);
```

#### 3.4.5 Retrieval Configuration

| Parameter | Value | Rationale |
|-----------|-------|----------|
| Chunk size | 512 tokens | Balance between context and specificity |
| Top-K retrieval | 5-10 chunks | Enough context without overflow |
| Similarity threshold | 0.7 | Discard low-relevance results |
| Reranking | Enabled | Maximize relevance to user request |

### 3.4 LLM Configuration

| Property | Value |
|----------|-------|
| Model | MiniMax M2.7 |
| Provider | MiniMax API (platform.minimax.io) |
| Context window | ~196,608 tokens |
| Input cost | $0.30 / 1M tokens |
| Output cost | $1.20 / 1M tokens |
| API key | `MINIMAX_API_KEY` environment variable |
| Deployment | API key (not self-hosted) |

### 3.5 MiniMax M2.7 Model Specs

| Property | Value |
|----------|-------|
| Type | Sparse Mixture-of-Experts (MoE) |
| Parameters | 229B |
| Context window | ~196,608 tokens |
| Input cost | $0.30 / 1M tokens |
| Output cost | $1.20 / 1M tokens |
| Native features | Agent Teams, function calling, 100+ skills |
| Benchmark (SWE-Pro) | 56.22% |
| Benchmark (MLE Bench) | 66.6% medal rate |

**Why MiniMax M2.7:**
- Native Agent Teams support — multi-agent collaboration built into model
- 229B MoE provides excellent performance at reasonable cost
- Function calling native — essential for tool use
- Open-weight available for self-hosting if needed later

---

## 4. Agent Swarm Architecture

### 4.1 Agent Types & Responsibilities

| Agent | Priority | Dependencies | Produces | Tools |
|-------|----------|--------------|----------|-------|
| **RootDepAgent** | MAX (spawns first) | Project spec | Shared schemas, DTOs, auth models, base classes | write_schema, generate_dto, create_auth_model, build_base_class |
| **BackendAgent** | HIGH | RootDep complete | Spring Boot 4 REST API, services, repositories, security | write_controller, write_service, write_repository, create_config, write_tests |
| **FrontendAgent** | HIGH | RootDep complete | Svelte 5 + Tailwind 4 UI, routes, stores | write_component, write_route, write_api_client, write_store, configure_tailwind |
| **DevOpsAgent** | MEDIUM | Backend complete | Dockerfile, Docker Compose, build scripts | write_dockerfile, write_docker_compose, build_image, push_image |
| **PackagerAgent** | LOW (runs last) | All complete | ZIP archive, delivery management | create_zip, verify_archive, trigger_docker_run |

### 4.2 Dependency Flow

```
User Request (natural language)
         │
         ▼
  Project Spec Parser ──► Task DAG (dependency graph)
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│                    BLACKBOARD (Redis + PostgreSQL)           │
│  Task Queue │ Agent Heartbeat │ Gossip │ File Manifest │ Meta│
└─────────────────────────────────────────────────────────────┘
         │
         ▼
  RootDepAgent (priority: MAX)
    └─ Writes: schemas/, DTOs/, auth/, base/
    └─ On completion: sets `dependencies_ready = true`
              │
    ┌─────────┴─────────┐
    ▼                   ▼
BackendAgent         FrontendAgent
(writes Spring)       (writes Svelte)
    │                   │
    └────────┬──────────┘
             ▼
        DevOpsAgent
        (Dockerfile + build)
             │
             ▼
        PackagerAgent
        (ZIP + image)
             │
             ▼
    Consensus Voter
    (all agents vote "done")
             │
             ▼
      Project Complete
```

### 4.3 Blackboard Pattern

**Redis (Real-time Layer):**
- Task queue (priority FIFO)
- Agent heartbeat (pub/sub)
- Gossip protocol (peer-to-peer status)
- File locks (prevent concurrent writes)

**PostgreSQL (Persistent Layer):**
- Project metadata (id, name, spec, status, created_at)
- File manifest (path, checksum, agent, created_at)
- Dependency graph (task DAG)
- Agent voting records (consensus)
- Chat history (per session, per user)

### 4.4 Gossip Protocol

```python
# Agent publishes status to Redis pub/sub
async def publish_update(agent_id: str, status: dict):
    channel = f"swarm:agent:{agent_id}"
    await redis.publish(channel, json.dumps(status))

# Other agents subscribe to relevant channels
async def subscribe_to_dependencies(deps: list):
    for dep in deps:
        channel = f"swarm:completed:{dep}"
        # Subscribe and trigger callback when dep completes
```

### 4.5 Dynamic Agent Spawning

```python
# Monitor queue depth
queue_depth = await redis.llen("swarm:tasks:pending")
if queue_depth > SPAWN_THRESHOLD:
    # Spawn additional agents of needed type
    await spawn_agents(
        type=detect_needed_type(queue_depth),
        count=ceil(queue_depth / SPAWN_THRESHOLD)
    )
```

### 4.6 Consensus Termination

```python
class ConsensusVoter:
    def __init__(self, total_agents: int, threshold: float = 0.8):
        self.votes = {}
        self.total = total_agents
        self.threshold = threshold

    def vote(self, agent_id: str, done: bool) -> bool:
        self.votes[agent_id] = done
        yes_votes = len([v for v in self.votes.values() if v])
        return yes_votes >= self.total * self.threshold
```

---

## 5. A2A Protocol (Agent-to-Agent)

### 5.1 Purpose

A2A is a **boundary protocol** for:
- Cross-organizational agent communication
- Cross-framework interoperability (CrewAI, Google ADK, LangGraph)
- External service integration
- Future multi-swarm handoffs

### 5.2 Agent Card

Each agent publishes its capabilities:

```json
{
  "agentId": "root_dep_agent",
  "name": "Root Dependency Agent",
  "description": "Builds shared schemas, DTOs, auth models, base classes for Spring Boot projects",
  "capabilities": ["schema_generation", "auth_models", "base_classes"],
  "skills": ["java", "spring_boot", "postgresql"],
  "endpoint": "http://localhost:8000/a2a/agents/root_dep"
}
```

### 5.3 Task Protocol

```python
class A2ATask:
    task_id: str
    agent_id: str
    input: dict
    context: dict  # shared state from blackboard
    priority: int
    deadline: Optional[datetime]
```

### 5.4 A2A vs Internal Communication

| Scope | Protocol | Use Case |
|-------|----------|----------|
| Internal swarm | Gossip + blackboard | Agent coordination within swarm |
| External agents | A2A | Cross-framework, cross-org communication |
| User interface | AG-UI (SSE) | Real-time agent-to-frontend events |

---

## 6. AG-UI Protocol (Full 17+ Event Types)

### 6.1 Overview

AG-UI (Agent-User Interaction) is a standardized, event-based protocol for real-time streaming between agents and frontends. All agent-to-frontend communication uses AG-UI via Server-Sent Events (SSE).

### 6.2 Event Categories

| Category | Events | Purpose |
|----------|--------|---------|
| **Lifecycle** | `RunStarted`, `RunFinished`, `RunError` | Agent run boundaries |
| **Step** | `StepStarted`, `StepFinished` | Granular progress tracking |
| **Text Streaming** | `TextMessageStart`, `TextMessageContent`, `TextMessageEnd` | Streaming textual content |
| **Tool Calls** | `ToolCallStart`, `ToolCallArgs`, `ToolCallEnd`, `ToolCallResult` | Agent tool invocations |
| **State** | `StateSnapshot`, `StateDelta` | State synchronization |
| **Activity** | `ActivitySnapshot`, `ActivityDelta` | In-progress activity updates |
| **Reasoning** | `ReasoningStart`, `ReasoningMessageContent`, `ReasoningEnd` | Agent thinking visibility |
| **Special** | `Raw`, `Custom` | Extension events |

### 6.3 Event Definitions

#### Lifecycle Events

| Event | Properties | Description |
|-------|------------|-------------|
| `RunStarted` | `runId`, `threadId`, `parentRunId?`, `input?` | Start of agent run |
| `RunFinished` | `outcome`, `result?` | End of run (success/interrupt/error) |
| `RunError` | `message`, `code?` | Error during run |

#### Step Events

| Event | Properties | Description |
|-------|------------|-------------|
| `StepStarted` | `stepName` | Agent started a step |
| `StepFinished` | `stepName` | Agent completed a step |

#### Text Streaming Events

| Event | Properties | Description |
|-------|------------|-------------|
| `TextMessageStart` | `messageId`, `role` | Start of text message |
| `TextMessageContent` | `messageId`, `delta` | Text content chunk |
| `TextMessageEnd` | `messageId` | End of text message |

#### Tool Call Events

| Event | Properties | Description |
|-------|------------|-------------|
| `ToolCallStart` | `toolCallId`, `toolCallName`, `parentMessageId?` | Tool invocation started |
| `ToolCallArgs` | `toolCallId`, `delta` | Tool arguments (streaming) |
| `ToolCallEnd` | `toolCallId` | Tool invocation complete |
| `ToolCallResult` | `messageId`, `toolCallId`, `content`, `role?` | Tool execution result |

#### State Events

| Event | Properties | Description |
|-------|------------|-------------|
| `StateSnapshot` | `snapshot` | Complete state snapshot |
| `StateDelta` | `delta` | JSON Patch incremental update |

#### Activity Events

| Event | Properties | Description |
|-------|------------|-------------|
| `ActivitySnapshot` | `messageId`, `activityType`, `content`, `replace?` | Full activity state |
| `ActivityDelta` | `messageId`, `activityType`, `patch` | Incremental activity update |

#### Reasoning Events

| Event | Properties | Description |
|-------|------------|-------------|
| `ReasoningStart` | `messageId` | Agent starts reasoning |
| `ReasoningMessageContent` | `messageId`, `delta` | Reasoning content chunk |
| `ReasoningEnd` | `messageId` | Reasoning complete |

#### Special Events

| Event | Properties | Description |
|-------|------------|-------------|
| `Raw` | `event`, `source?` | Passthrough external events |
| `Custom` | `name`, `value` | Application-specific events |

### 6.4 SSE Implementation

**Backend (FastAPI):**
```python
@router.get("/api/stream/{session_id}")
async def stream_events(session_id: str):
    async def generator():
        async for event in swarm.stream_events(session_id):
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )
```

**Frontend (Svelte 5):**
```typescript
function createSSEClient(sessionId: string) {
  const events = new EventSource(`/api/stream/${sessionId}`);

  events.addEventListener('RunStarted', (e) => handleRunStart(JSON.parse(e.data)));
  events.addEventListener('ActivitySnapshot', (e) => handleActivity(JSON.parse(e.data)));
  events.addEventListener('StepStarted', (e) => handleStepStart(JSON.parse(e.data)));
  events.addEventListener('ReasoningStart', (e) => handleThinking(JSON.parse(e.data)));
  events.addEventListener('ToolCallStart', (e) => handleToolCall(JSON.parse(e.data)));
  // ... all 17+ AG-UI event types

  return events;
}
```

### 6.5 Frontend Display Components

| Component | Displays |
|-----------|----------|
| `ChatMessage` | User messages + agent responses |
| `ActivityFeed` | Real-time agent actions (scrolling) |
| `ThinkingDisplay` | Agent reasoning with typing effect |
| `ProgressBar` | Step progress (StepStarted → StepFinished) |
| `ToolCallDisplay` | Tool invocations with arguments/results |
| `DownloadButtons` | ZIP download + Docker run |

---

## 7. Tools & Tool Calling

### 7.1 Agent Toolset

#### RootDepAgent Tools

| Tool | Purpose | Output |
|------|---------|--------|
| `write_schema` | Write database schema | `schemas/*.sql` |
| `generate_dto` | Create DTO Java classes | `dto/*.java` |
| `create_auth_model` | Generate auth entities | `auth/*.java` |
| `build_base_class` | Create base controller/service | `base/*.java` |

#### BackendAgent Tools

| Tool | Purpose | Output |
|------|---------|--------|
| `write_controller` | Generate REST controllers | `*Controller.java` |
| `write_service` | Generate service layer | `*Service.java` |
| `write_repository` | Generate JPA repositories | `*Repository.java` |
| `create_config` | Generate configs | `application.yml` |
| `write_tests` | Generate unit tests | `*Test.java` |

#### FrontendAgent Tools

| Tool | Purpose | Output |
|------|---------|--------|
| `write_component` | Generate Svelte components | `*.svelte` |
| `write_route` | Create SvelteKit routes | `routes/*` |
| `write_api_client` | Generate API client | `lib/api.ts` |
| `write_store` | Create Svelte stores | `lib/stores/*` |
| `configure_tailwind` | Set up Tailwind | `tailwind.config.js` |

#### DevOpsAgent Tools

| Tool | Purpose | Output |
|------|---------|--------|
| `write_dockerfile` | Create Dockerfile | `Dockerfile` |
| `write_docker_compose` | Create Compose file | `docker-compose.yml` |
| `build_image` | Build Docker image | `docker build` |
| `push_image` | Push to registry | `docker push` |

#### PackagerAgent Tools

| Tool | Purpose | Output |
|------|---------|--------|
| `create_zip` | Create ZIP archive | `*.zip` |
| `verify_archive` | Verify ZIP integrity | — |
| `trigger_docker_run` | Start container | `docker run` |

### 7.2 Handoff Tool (LangGraph Swarm)

```python
from langgraph.swarm import create_handoff_tool

handoff_to_backend = create_handoff_tool(
    agent_name="backend_agent",
    description="Handoff to Backend Agent for REST API generation"
)
```

### 7.3 Tool Result Streaming

```python
# Tool calls streamed via AG-UI
{"type": "ToolCallStart", "toolCallId": "tc-001", "toolCallName": "write_schema"}
{"type": "ToolCallArgs", "toolCallId": "tc-001", "delta": "package com.example"}
{"type": "ToolCallEnd", "toolCallId": "tc-001"}
{"type": "ToolCallResult", "toolCallId": "tc-001", "content": "Created: src/main/java/com/example/schema.sql"}
```

---

## 8. Context Engineering & Compaction

### 8.1 Token Budget

| Component | Budget |
|-----------|--------|
| MiniMax M2.7 context | 196,608 tokens |
| System prompt (agent instructions) | ~8,000 tokens |
| Shared blackboard context | ~20,000 tokens |
| Available for conversation | ~168,000 tokens |

### 8.2 Prompt Caching Strategy

- **Static prompts** (agent instructions, schemas) cached in Redis with 1-hour TTL
- **Dynamic context** (task-specific) computed per request
- **System prompt optimization** — minimal instruction text, reference external docs

### 8.3 Context Compaction

When context exceeds 128K tokens, compact via:

```python
class ContextCompaction:
    """
    Compacts conversation history via:
    1. Key-fact extraction (entities, decisions)
    2. Summarization of older messages
    3. Pruning redundant tool call results
    4. Preserving: architectural decisions, DB schema, auth models
    """

    def compact(self, messages: list, max_tokens: int) -> list:
        facts = self.extract_key_facts(messages)
        summaries = self.summarize(messages[:-10])
        pruned = self.prune_tool_results(messages)
        return facts + summaries + pruned
```

### 8.4 Retention Policy

| Message Type | Retention | Compaction |
|-------------|-----------|------------|
| User requests | Full | Never |
| Agent reasoning | Summary only | → key facts |
| Tool results | Final output only | Prune intermediate steps |
| System prompts | Static (cached) | Never |
| Shared dependencies | Always preserved | Never |

### 8.5 Context Window Allocation Per Agent

| Agent | System | Blackboard | Work | Total |
|-------|--------|------------|------|-------|
| RootDepAgent | 6K | 15K | 175K | 196K |
| BackendAgent | 6K | 20K | 170K | 196K |
| FrontendAgent | 6K | 15K | 175K | 196K |
| DevOpsAgent | 4K | 10K | 182K | 196K |
| PackagerAgent | 3K | 5K | 188K | 196K |

---

## 9. Sandbox & Code Generation

### 9.1 Docker-in-Docker Setup

```yaml
# docker-compose.yml
services:
  swarm:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    privileged: true
```

### 9.2 Workspace Per Project

```python
async def create_workspace(project_id: str) -> str:
    workspace_dir = f"/workspaces/{project_id}"
    os.makedirs(workspace_dir, exist_ok=True)
    subprocess.run(["git", "init"], cwd=workspace_dir)
    return workspace_dir
```

### 9.3 Resource Limits

```python
limits = {
    "mem_limit": "2g",
    "cpu_period": 100000,
    "cpu_quota": 50000,  # 50% CPU
    "pids_limit": 100,
    "network_mode": "none"  # No network access
}
```

### 9.4 Code Generation Strategy

**From-scratch generation:**
- Project spec parsed by LLM into structured requirements
- Agent writes all code files directly (no templates)
- Spring Boot 4.x with Jakarta EE 11
- Svelte 5 with runes (not legacy Svelte 4)
- Tailwind 4 (not Tailwind 3)

### 9.5 File Lock Mechanism

```python
async def write_file(path: str, content: str, lock_key: str):
    async with redis.lock(f"lock:{lock_key}", timeout=30):
        with open(path, "w") as f:
            f.write(content)
```

---

## 10. API Endpoints

### 10.1 Phase 1 Mock API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/chat` | Send message, returns `{session_id}` |
| `GET` | `/api/stream/{session_id}` | SSE stream of AG-UI events |
| `GET` | `/api/history/{session_id}` | Get chat history |
| `GET` | `/api/project/{session_id}` | Get project status + download links |

### 10.2 Production API (Future)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/projects` | Create new project |
| `GET` | `/api/v1/projects/{id}` | Get project status |
| `GET` | `/api/v1/projects/{id}/stream` | SSE stream |
| `GET` | `/api/v1/projects/{id}/download` | Download ZIP |
| `POST` | `/api/v1/projects/{id}/run` | Run Docker container |

### 10.3 RAG API (Production)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/rag/ingest` | Ingest documents into vector store |
| `GET` | `/api/v1/rag/search` | Search vector store, returns relevant chunks |
| `POST` | `/api/v1/rag/query` | Retrieve + generate (RAG completion) |

---

## 11. Database Schema

### 11.1 Chat Persistence (PostgreSQL)

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    role TEXT NOT NULL,  -- 'user' or 'assistant'
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id),
    spec JSON,
    status TEXT DEFAULT 'pending',
    zip_path TEXT,
    docker_image TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);
```

### 11.2 Project Metadata (PostgreSQL)

```sql
CREATE TABLE project_files (
    id SERIAL PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    path TEXT NOT NULL,
    checksum TEXT,
    agent TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agent_votes (
    id SERIAL PRIMARY KEY,
    project_id TEXT REFERENCES projects(id),
    agent_id TEXT,
    vote BOOLEAN,
    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE rag_documents (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,          -- 'spring-boot', 'svelte', 'pattern', etc.
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    metadata JSONB,                        -- tags, date, version
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Note: pgvector extension must be enabled: CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE rag_embeddings (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES rag_documents(id) ON DELETE CASCADE,
    embedding vector(1536),               -- nomic-embed-text dimensions
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_rag_embeddings_cosine ON rag_embeddings USING cosine(embedding);
CREATE INDEX idx_rag_documents_source ON rag_documents(source);
CREATE INDEX idx_rag_documents_created ON rag_documents(created_at);
```

---

## 12. Configuration

### 12.1 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MINIMAX_API_KEY` | — | MiniMax API key (required) |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `DATABASE_URL` | `postgresql://localhost:5432/deepseek` | PostgreSQL connection URL |
| `MINIMAX_API_URL` | `https://api.minimax.io` | MiniMax API endpoint |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed CORS origins |
| `DEBUG` | `false` | Debug mode |

### 12.2 Agent Configuration

| Agent | Max Tokens | Temperature | Tools |
|-------|-----------|-------------|-------|
| RootDepAgent | 8192 | 0.7 | schema, dto, auth, base |
| BackendAgent | 16384 | 0.7 | controller, service, repo, config |
| FrontendAgent | 16384 | 0.7 | component, route, api, store |
| DevOpsAgent | 4096 | 0.5 | dockerfile, compose, build |
| PackagerAgent | 2048 | 0.3 | zip, verify |

---

## 13. Error Handling & Recovery

### 13.1 Retry Mechanism

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def with_retry(func, *args):
    return await func(*args)
```

### 13.2 Fallback Strategy

If LLM generation fails after retries:
- Fall back to template-based generation
- Use pre-defined Spring Boot + Svelte scaffolds
- Mark project as "partial" with manual intervention required

### 13.3 State Recovery

```python
async def checkpoint_state(state: SwarmState):
    async with async_session() as session:
        checkpoint = Checkpoint(
            project_id=state["project_id"],
            state=json.dumps(state),
            step=state["current_step"]
        )
        session.add(checkpoint)
        await session.commit()
```

### 13.4 Dead Agent Detection

```python
# If no heartbeat for 60s, consider agent dead
async def monitor_heartbeats():
    while True:
        for agent_id, last_seen in agent_heartbeats.items():
            if time.time() - last_seen > 60:
                await respawn_agent(agent_id)
        await asyncio.sleep(10)
```

---

## 14. Security Considerations

### 14.1 Sandbox Isolation

- No network access in sandbox containers
- Resource limits (memory, CPU, pids)
- Read-only root filesystem (where possible)
- Non-root user execution

### 14.2 API Security

- JWT authentication for all endpoints
- Rate limiting per user
- Input validation with Pydantic
- SQL injection prevention (parameterized queries)

### 14.3 Secret Management

- API keys stored in environment variables
- Database credentials via secrets manager
- No secrets in code or config files

---

## 15. Performance Targets

| Metric | Target |
|--------|--------|
| Time to first token (TTFT) | < 500ms |
| Project generation (simple) | < 60s |
| Project generation (complex) | < 180s |
| Concurrent projects | 5 per user, 20 total |
| Token efficiency | < 500K tokens per project |
| ZIP creation | < 10s |
| Docker build | < 120s |

---

## 16. File Structure

```
/home/amnayem/Projects/nvidia_dev/deepseek/
├── docs/
│   ├── SPEC.md                              # This specification
│   ├── IMPLEMENTATION_PLAN.md               # Detailed task breakdown
│   └── AGENTS/
│       ├── ROOT_DEP.md                      # RootDep agent spec
│       ├── BACKEND.md                       # Backend agent spec
│       ├── FRONTEND.md                      # Frontend agent spec
│       ├── DEVOPS.md                        # DevOps agent spec
│       └── PACKAGER.md                      # Packager agent spec
│
├── frontend/                                # Svelte 5 UI
│   ├── src/
│   │   ├── routes/
│   │   │   ├── +page.svelte                # Main chat page
│   │   │   └── api/stream/+server.ts        # SSE mock endpoint
│   │   ├── components/
│   │   │   ├── ChatMessage.svelte
│   │   │   ├── ActivityFeed.svelte
│   │   │   ├── ThinkingDisplay.svelte
│   │   │   ├── ProgressBar.svelte
│   │   │   └── DownloadButtons.svelte
│   │   ├── lib/
│   │   │   ├── api.ts
│   │   │   ├── sse.ts                      # AG-UI event parser
│   │   │   └── stores/
│   │   │       ├── chat.svelte.ts
│   │   │       └── agent.svelte.ts
│   │   └── app.css
│   ├── package.json
│   ├── svelte.config.js
│   ├── tailwind.config.js
│   └── vite.config.ts
│
├── backend/                                 # Python FastAPI
│   ├── main.py
│   ├── api/
│   │   ├── router.py
│   │   └── schemas.py
│   ├── mock/
│   │   ├── agent_simulator.py
│   │   └── event_generator.py
│   ├── storage/
│   │   └── sqlite.py
│   └── requirements.txt
│
├── swarm/                                   # LangGraph Swarm
│   ├── agents/
│   │   ├── root_dep.py
│   │   ├── backend.py
│   │   ├── frontend.py
│   │   ├── devops.py
│   │   ├── packager.py
│   │   └── base.py
│   ├── blackboard/
│   │   ├── redis_client.py
│   │   └── postgres_client.py
│   ├── tools/
│   │   ├── file_tools.py
│   │   ├── docker_tools.py
│   │   └── handoff_tools.py
│   └── requirements.txt
│
├── sandbox/                                 # Docker workspace
│   ├── docker/
│   │   └── Dockerfile
│   └── entrypoint.sh
│
└── templates/                               # Code generation templates
    ├── spring-boot/
    │   ├── pom.xml.j2
    │   └── ...
    └── svelte/
        └── ...
```

---

## 17. Implementation Phases

| Phase | Description | Timeline | Status |
|-------|-------------|----------|--------|
| **Phase 1** | Frontend Chat UI + Mocked API | 2-3 weeks | ✅ Completed |
| **Phase 2** | Real LangGraph Swarm + MiniMax | 3-4 weeks | ✅ Completed |
| **Phase 3** | Sandbox + Code Generation | 4-6 weeks | 🔄 In Progress |
| **Phase 4** | Swarm Refinement + Polish | 2-3 weeks | ⏳ Pending |

---

## 18. Coding Agent Sandbox Architecture (Market Leader Research)

### 18.1 How Market Leaders Implement Sandboxing

Based on research of Qwen Code, Claude Code, Kimi, and other market leaders:

#### Claude Code (Anthropic)

| Platform | Technology | Details |
|----------|------------|---------|
| macOS | **Seatbelt** (`sandbox-exec`) | Built-in Apple sandboxing, no container overhead |
| Linux | **bubblewrap** + network proxy | OS-level namespace isolation |
| Windows | Restricted Tokens | Process-level restrictions |
| Cloud | Full microVMs | Complete isolation for web-based sessions |

**Architecture:**
- Uses `@anthropic-ai/sandbox-runtime` npm package
- `bubblewrap` wraps the bash tool with filesystem + network restrictions
- Network proxy allows controlled outbound access
- Settings in `~/.claude/settings.json`

#### Qwen Code (Alibaba)

| Platform | Technology | Details |
|----------|------------|---------|
| macOS | **Seatbelt** | Lightweight, no Docker required |
| Linux | **Docker / Podman** | Container-based full isolation |
| Default Image | `ghcr.io/qwenlm/qwen-code:<version>` | Customizable via `.qwen/sandbox.Dockerfile` |

**Architecture:**
- Environment variable: `QWEN_SANDBOX=true|docker|podman|sandbox-exec`
- Seatbelt profiles: `permissive-open`, `restrictive-closed`, etc.
- Docker customization: `.qwen/sandbox.Dockerfile`
- Network proxying via `QWEN_SANDBOX_PROXY_COMMAND`

#### Kimi K2 (Moonshot AI)

| Platform | Technology | Details |
|----------|------------|---------|
| Architecture | **Agent Swarm** | 300 sub-agents, 4000 coordinated steps |
| Backend | Alibaba Cloud ACK/ACS | Kubernetes-based elastic infrastructure |
| Isolation | Container-based | Per-agent containerized worktrees |

**Architecture:**
- Agent cluster architecture for scale
- Multi-agent orchestration with sub-agent spawning
- Git branch-based worktree isolation

#### OpenAI Codex CLI

| Platform | Technology | Details |
|----------|------------|---------|
| macOS | **Seatbelt** | Built-in |
| Linux | **Landlock + seccomp** | No container! OS-level restrictions |
| Windows | Restricted Tokens | Process restrictions |
| Modes | `read-only`, `workspace-write`, `danger-full-access` | Progressive trust levels |

**Key Insight:** Codex CLI uses **Landlock** on Linux — a Linux Security Module that provides filesystem restrictions without container overhead. This is lighter weight than Docker.

### 18.2 Sandbox Technology Spectrum

| Type | Technologies | Overhead | Isolation |
|------|--------------|----------|----------|
| **OS-level** | Seatbelt, Landlock, seccomp-bpf, bubblewrap | Lowest | Weakest |
| **MicroVM** | Firecracker, Kata, Cloud Hypervisor | Low | Hardware boundary |
| **Container** | Docker, Podman, LXC | Medium | Shared kernel |
| **WASM** | WASMtime, WASI | Lowest | Strongest |

### 18.3 Market Leader Sandbox Choices

| Platform | Primary Sandbox | Secondary | BYOC |
|----------|---------------|----------|------|
| Claude Code | Seatbelt/bubblewrap | — | No |
| Qwen Code | Seatbelt | Docker | No |
| Codex CLI | Landlock + seccomp | — | No |
| Kimi | Container-based | — | Yes (Alibaba Cloud) |
| E2B | Firecracker microVM | — | AWS only |
| Northflank | Kata + Firecracker | gVisor | Yes (multi-cloud) |
| Modal | gVisor | — | No |
| Fly.io Sprites | Firecracker | — | No |

### 18.4 Recommended Sandbox Architecture for DeepSeek

Based on market leader research, we implement a **layered approach**:

#### Layer 1: Local Development (Fast)
```
Host Machine
└── LangGraph Swarm Process
    └── bubblewrap/Landlock (workspace-write)
```
- Fast cold start (<100ms)
- Filesystem restricted to project workspace
- Network allowed for API calls (MiniMax)

#### Layer 2: Production / Multi-Tenant (Secure)
```
Docker Host / Kubernetes
└── MicroVM / Container
    └── Agent Workspace
        ├── Ubuntu base
        ├── Java 21
        ├── Node 20
        └── Maven/NPM
    Network: Restricted (allowlist)
```
- Firecracker microVM or Docker container
- Resource limits: 2CPU, 4GB RAM, 100 pids
- Network: no external access, API calls through proxy

### 18.5 Sandbox Implementation Details

#### Qwen Code Sandbox Configuration (Reference)

```bash
# Enable sandboxing
export QWEN_SANDBOX=true  # auto-select provider

# Force Docker
export QWEN_SANDBOX=docker

# Custom image
export QWEN_SANDBOX_IMAGE=ghcr.io/qwenlm/qwen-code:latest

# Custom Dockerfile for extension
# .qwen/sandbox.Dockerfile
FROM ghcr.io/qwenlm/qwen-code:latest
RUN apt-get update && apt-get install -y openjdk-17-jre && rm -rf /var/lib/apt/lists/*

# Build custom sandbox
QWEN_SANDBOX=docker BUILD_SANDBOX=1 qwen -s
```

#### Claude Code Sandbox Configuration (Reference)

```bash
# Enable sandbox (automatic on macOS with Seatbelt)
# On Linux: needs bubblewrap installed

# Network proxy for allowlist
export ANTHROPIC_SANDBOX_PROXY=http://localhost:8877

# Check sandbox status
claude --sandbox-status
```

### 18.6 Key Insights from Market Leaders

1. **Seatbelt is the default on macOS** — No Docker needed for local development
2. **Landlock on Linux** — Codex CLI uses this instead of containers (lighter)
3. **Docker/Podman as fallback** — For full Linux userland or complex tooling
4. **MicroVMs for production** — E2B, Northflank use Firecracker/Kata for stronger isolation
5. **Network proxying** — All major agents support controlled outbound access
6. **Custom Dockerfile extension** — Qwen Code pattern: extend base image with `.qwen/sandbox.Dockerfile`
7. **Modes/Profiles** — Progressive trust levels: `read-only` → `workspace-write` → `danger-full-access`

### 18.7 Our Implementation Decision

For DeepSeek, we implement **Seatbelt/bubblewrap** (market leader approach):

| Environment | Sandbox | Reason |
|------------|---------|--------|
| **Phase 1 (Mock)** | None | No code execution |
| **Phase 2 (Dev)** | Seatbelt (macOS) / bubblewrap (Linux) | OS-level, <100ms cold start |
| **Phase 3 (Production)** | bubblewrap with resource limits | Per-project isolation, lightweight |

**Key advantages over Docker-in-Docker:**
- Cold start: <100ms vs 3-5s
- No Docker daemon dependency
- Lower memory overhead
- Native OS-level isolation (matches Claude Code, Qwen Code, Codex CLI)

**Platform detection:**
```python
import platform
import subprocess

def get_sandbox_type():
    system = platform.system()
    if system == "Darwin":
        return "seatbelt"  # Built-in Apple sandbox
    elif system == "Linux":
        # Check if bubblewrap is available
        try:
            subprocess.run(["bwrap", "--version"], check=True, capture_output=True)
            return "bubblewrap"
        except:
            return "landlock"  # Fallback to Landlock
    else:
        return "docker"  # Windows fallback

---

## 19. Security Considerations

### 19.1 Sandbox Isolation Levels

| Level | Restriction | Use Case |
|-------|------------|----------|
| **Strict** | No network, read-only filesystem except workspace | Untrusted code |
| **Standard** | Network via proxy, read-write workspace | Normal agent work |
| **Relaxed** | Full network, read-write workspace, privileged | Build/compile only |

### 19.2 Threat Model

| Threat | Mitigation |
|--------|-----------|
| Kernel exploit escaping container | MicroVM (Firecracker/Kata) |
| Prompt injection via files | Sandboxed filesystem, no exfiltration |
| Resource exhaustion | cgroups limits (CPU, memory, pids) |
| Network exfiltration | Proxy with allowlist, no direct internet |
| Credential theft | Secrets not mounted in sandbox, env vars only |

---

## 20. Open Questions / TODOs

- [x] ~~RAG integration~~ — Added in Section 3.4
- [x] ~~PostgreSQL persistence layer~~ — Added in Section 3.3 and 11
- [x] ~~Sandbox architecture research~~ — Added in Section 18
- [x] ~~Docker-in-Docker vs Landlock/bubblewrap~~ — **Decision: Seatbelt/bubblewrap** (Section 18.7)
- [ ] Confirm: Resource limits (CPU, RAM, pids) for bubblewrap sandbox?
- [ ] Confirm: Network proxy allowlist (which domains are allowed)?
- [ ] Confirm: bubblewrap installation required on Linux (apt install bubblewrap)?

---

## 21. References

- [Qwen Code Sandbox Docs](https://qwenlm.github.io/qwen-code-docs/en/users/features/sandbox/)
- [Claude Code Sandboxing](https://code.claude.com/docs/en/sandboxing)
- [Coding Agent Sandboxes — Comprehensive List (GitHub Gist)](https://gist.github.com/wincent/2752d8d97727577050c043e4ff9e386e)
- [Northflank: Best sandboxes for coding agents](https://northflank.com/blog/best-sandboxes-for-coding-agents)
- [Kimi K2.6 Agent Swarm](https://www.marktechpost.com/2026/04/20/moonshot-ai-releases-kimi-k2-6-with-long-horizon-coding-agent-swarm-scaling-to-300-sub-agents-and-4000-coordinated-steps/)
- [LangGraph Swarm](https://reference.langchain.com/python/langgraph-swarm)
- [AG-UI Protocol](https://docs.ag-ui.com/)
- [MiniMax M2.7 Model Card](https://huggingface.co/MiniMaxAI/MiniMax-M2.7)

---

**End of Specification**