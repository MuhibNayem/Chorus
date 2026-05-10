# Swarm Claim Protocol Implementation Plan

**Status:** Draft for implementation  
**Created:** 2026-05-07  
**Scope:** Replace agent-level "done" trust with artifact-level swarm claims, validated barriers, and revocable readiness while preserving swarm autonomy.

---

## 1. Purpose

The current system has improved coordinator barriers, but it still models completion mostly as agent lifecycle state. A true swarm should not treat "backend is done" as the primary dependency. It should treat "backend API is ready" as a claim with evidence that can be validated, consumed, invalidated, and re-issued.

This plan defines the implementation required to move from agent-level completion gates to a blackboard-based claim protocol.

The goal is not to create a master/slave workflow. The goal is to keep agents autonomous while making shared state trustworthy.

---

## 2. Design Principle

Agents remain autonomous specialists. They decide how to implement their domain, inspect the workspace, publish todos, generate artifacts, and publish readiness claims.

The protocol enforces shared truth:

- Claims must include evidence.
- Evidence must be validated.
- Dependent claims rely on validated prerequisite claims.
- Post-claim activity can make a claim stale.
- Packager starts only after the required claim graph is valid and stable.

This creates a swarm with strict rules, not a hierarchy.

---

## 3. Target Claim Graph

```text
SPEC_READY
  -> BACKEND_RUNTIME_READY
  -> BACKEND_API_READY
  -> FRONTEND_BUILD_READY
  -> DEPLOYMENT_READY
  -> PACKAGE_READY
```

Parallel-friendly version:

```text
SPEC_READY
  -> BACKEND_RUNTIME_READY
  -> BACKEND_API_READY

SPEC_READY
  -> FRONTEND_SOURCE_READY

BACKEND_API_READY + FRONTEND_SOURCE_READY
  -> FRONTEND_BUILD_READY

BACKEND_RUNTIME_READY + FRONTEND_BUILD_READY
  -> DEPLOYMENT_READY

DEPLOYMENT_READY
  -> PACKAGE_READY
```

---

## 4. Claim Types

### 4.1 SPEC_READY

Producer: `rootdep`

Meaning: The shared project specification is available and stable enough for implementation agents.

Evidence:

- `SPEC.md` exists.
- `SPEC.md` is non-empty.
- Optional `AGENTS_NEEDED.json` exists in modify mode.

Consumers:

- `backend`
- `frontend`
- `devops`

Validation:

- File exists inside workspace.
- File size is greater than 0.
- If approved mode is used, the claim is restored from the existing `SPEC.md`; RootDep must not rerun.

### 4.2 BACKEND_RUNTIME_READY

Producer: `backend`

Meaning: Backend application source and runtime manifest are ready.

Evidence:

- `backend/pom.xml`
- `backend/src/main/...`
- `backend/src/main/resources/application.yml`
- Optional backend port metadata.
- Completed backend todos.

Consumers:

- `devops`
- `packager`

Validation:

- `backend/pom.xml` exists.
- Java/Spring Boot version can be parsed or inferred.
- No backend todo is pending or in progress.
- Backend agent has no post-claim write activity.

### 4.3 BACKEND_API_READY

Producer: `backend`

Meaning: Backend API contract is ready for frontend integration.

Evidence:

- `backend/API_MANIFEST.json` or extracted endpoint summary.
- Controller files exist.
- Auth/WebSocket metadata if applicable.
- Completed backend todos.

Consumers:

- `frontend`
- `devops`
- `packager`

Validation:

- API manifest exists or can be derived from source.
- Evidence files exist.
- Claim depends on valid `BACKEND_RUNTIME_READY`.
- Backend has no later conflicting activity.

### 4.4 FRONTEND_SOURCE_READY

Producer: `frontend`

Meaning: Frontend source code exists and can be analyzed by DevOps.

Evidence:

- `frontend/package.json`
- `frontend/src/app.html`
- `frontend/src/routes/...`
- Completed frontend todos.

Consumers:

- `devops`
- `packager`

Validation:

- `frontend/package.json` exists.
- SvelteKit dependency exists.
- Build script exists or can be inferred.
- Frontend has no post-claim write activity.

### 4.5 FRONTEND_BUILD_READY

Producer: `frontend`

Meaning: Frontend source and build manifest are ready for deployment wiring.

Evidence:

- `frontend/package.json`
- `frontend/svelte.config.js` or `frontend/svelte.config.ts`
- Build command.
- Adapter information if available.

Consumers:

- `devops`
- `packager`

Validation:

- Depends on valid `BACKEND_API_READY` when frontend integrates backend APIs.
- `package.json` has valid JSON.
- Build script is present.
- No frontend todo is pending or in progress.

### 4.6 DEPLOYMENT_READY

Producer: `devops`

Meaning: Deployment artifacts are ready and consistent with backend/frontend manifests.

Evidence:

- `backend/Dockerfile`
- `frontend/Dockerfile`
- `docker-compose.yml`
- Optional `nginx/nginx.conf`
- Optional `.env.example`
- Optional CI/Kubernetes files.

Consumers:

- `packager`

Validation:

- Depends on valid `BACKEND_RUNTIME_READY`.
- Depends on valid `FRONTEND_BUILD_READY`.
- Dockerfiles exist only after DevOps runs.
- Root `docker-compose.yml` exists.
- Compose build contexts match generated folders.
- DevOps has no post-claim write activity.

### 4.7 PACKAGE_READY

Producer: `packager`

Meaning: Workspace has been verified, zipped, and uploaded.

Evidence:

- Project zip exists.
- Storage object exists or upload result is successful.
- Download URL exists.

Consumers:

- UI
- Project status system

Validation:

- Depends on valid `DEPLOYMENT_READY`.
- Zip exists and is non-empty.
- Upload tool returned success.

---

## 5. Claim Schema

Store each claim as JSON.

```json
{
  "id": "claim-uuid",
  "project_id": "project-id",
  "claim_type": "BACKEND_API_READY",
  "producer_agent": "backend",
  "status": "claimed",
  "evidence": {
    "files": ["backend/API_MANIFEST.json"],
    "ports": [8080],
    "commands": [],
    "metadata": {}
  },
  "depends_on": ["BACKEND_RUNTIME_READY"],
  "created_at": "2026-05-07T12:00:00Z",
  "updated_at": "2026-05-07T12:00:00Z",
  "producer_event_seq": 42,
  "workspace_revision": "optional-hash",
  "validation": {
    "status": "unknown",
    "validated_at": null,
    "errors": [],
    "warnings": []
  }
}
```

Allowed statuses:

- `draft`
- `claimed`
- `valid`
- `invalid`
- `stale`
- `revoked`

Rules:

- Agents publish `claimed`.
- Protocol validation changes `claimed` to `valid` or `invalid`.
- Later conflicting activity changes `valid` to `stale`.
- A producing agent can explicitly publish a replacement claim.
- `revoked` is terminal for that claim version.

---

## 6. Redis Key Design

Use Redis as the live swarm blackboard.

```text
project:{project_id}:claims:index
project:{project_id}:claims:{claim_type}
project:{project_id}:claim:{claim_id}
project:{project_id}:claim_dependencies:{claim_id}
project:{project_id}:agent:{agent_name}:event_seq
project:{project_id}:agent:{agent_name}:last_activity_at
project:{project_id}:events
```

Recommended storage:

- `claims:index`: Redis set of claim IDs.
- `claims:{claim_type}`: latest claim ID for type.
- `claim:{claim_id}`: JSON claim payload.
- `claim_dependencies:{claim_id}`: set of dependency claim IDs or types.
- Publish every claim change on `project:{project_id}:events`.

---

## 7. Tool API

### 7.1 publish_claim

Agent-facing tool.

Input:

```json
{
  "claim_type": "BACKEND_API_READY",
  "evidence": {
    "files": ["backend/API_MANIFEST.json"],
    "ports": [8080],
    "metadata": {}
  },
  "depends_on": ["BACKEND_RUNTIME_READY"]
}
```

Output:

```json
{
  "status": "success",
  "claim_id": "claim-uuid",
  "claim_type": "BACKEND_API_READY"
}
```

Rules:

- Tool sets `producer_agent` from context.
- Tool attaches current agent event sequence.
- Tool publishes a `claim` event.
- Tool does not mark the claim valid.

### 7.2 validate_claim

Protocol-facing function, not generally agent-facing.

Input:

```json
{
  "claim_type": "BACKEND_API_READY"
}
```

Output:

```json
{
  "status": "valid",
  "claim_id": "claim-uuid",
  "errors": [],
  "warnings": []
}
```

Rules:

- Validates evidence.
- Validates dependencies.
- Validates no producer activity after claim.
- Updates claim status.
- Publishes `claim_validated` event.

### 7.3 wait_for_claim

Agent-facing tool.

Input:

```json
{
  "claim_type": "BACKEND_API_READY",
  "timeout_seconds": 0
}
```

Output:

```json
{
  "status": "success",
  "claim_type": "BACKEND_API_READY",
  "claim_id": "claim-uuid",
  "evidence": {}
}
```

Rules:

- Waits for a valid claim, not merely a claimed one.
- If latest claim becomes stale, continues waiting.
- If dependency failure is published, returns error.
- Timeout `0` means indefinite wait.

### 7.4 revoke_claim

Protocol-facing function.

Input:

```json
{
  "claim_id": "claim-uuid",
  "reason": "backend wrote files after BACKEND_API_READY"
}
```

Output:

```json
{
  "status": "revoked",
  "claim_id": "claim-uuid"
}
```

Rules:

- Revokes the claim and marks dependents stale.
- Publishes `claim_revoked`.

---

## 8. Integration Flow

### 8.1 Plan Mode

Current behavior:

- RootDep runs.
- `SPEC.md` is generated.
- UI receives `PlanReady`.

Required behavior:

1. RootDep generates `SPEC.md`.
2. Protocol publishes `SPEC_READY`.
3. Protocol validates `SPEC_READY`.
4. UI receives `PlanReady`.

Approved build behavior:

1. `/api/approve` saves approved `SPEC.md`.
2. Build starts with `run_mode=approved`.
3. RootDep is skipped.
4. Protocol restores/publishes `SPEC_READY` from the approved `SPEC.md`.
5. Backend starts.

### 8.2 Backend Flow

1. Backend waits for valid `SPEC_READY`.
2. Backend writes backend source and manifests.
3. Backend publishes `BACKEND_RUNTIME_READY`.
4. Protocol validates `BACKEND_RUNTIME_READY`.
5. Backend publishes `BACKEND_API_READY`.
6. Protocol validates `BACKEND_API_READY`.

### 8.3 Frontend Flow

1. Frontend waits for valid `SPEC_READY`.
2. Frontend waits for valid `BACKEND_API_READY` if backend APIs are required.
3. Frontend writes frontend source and manifests.
4. Frontend publishes `FRONTEND_SOURCE_READY`.
5. Protocol validates `FRONTEND_SOURCE_READY`.
6. Frontend publishes `FRONTEND_BUILD_READY`.
7. Protocol validates `FRONTEND_BUILD_READY`.

### 8.4 DevOps Flow

1. DevOps waits for valid `BACKEND_RUNTIME_READY`.
2. DevOps waits for valid `FRONTEND_BUILD_READY`.
3. DevOps reads actual manifests.
4. DevOps writes deployment artifacts.
5. DevOps publishes `DEPLOYMENT_READY`.
6. Protocol validates `DEPLOYMENT_READY`.

### 8.5 Packager Flow

1. Packager waits for valid `DEPLOYMENT_READY`.
2. Packager verifies workspace.
3. Packager creates zip.
4. Packager uploads zip.
5. Packager publishes `PACKAGE_READY`.
6. Protocol validates `PACKAGE_READY`.
7. UI receives final download event.

---

## 9. Atomic Task Definitions

Progress:

- Phase 1: Claim Data Model — **Completed 2026-05-07**
- Phase 2: Claim Store — **Completed 2026-05-07**
- Phase 3: Claim Tools — **Completed 2026-05-07**
- Phase 4: Claim Validators — **Completed 2026-05-07**
- Phase 5: Agent Prompt and Tool Wiring — **Completed 2026-05-07**
- Phase 6: Coordinator Claim Barriers — **Completed 2026-05-07**
- Phase 7: Claim Revocation and Staleness — **Completed 2026-05-07**

### Phase 1: Claim Data Model

Status: **Completed 2026-05-07**

Implemented files:

- `backend/src/swarm/claims.py`
- `backend/tests/test_claims.py`

Verification:

- `python3 -m pytest backend/tests/test_claims.py backend/tests/test_swarm_coordination.py`
- `python3 -m compileall backend/src backend/tests`

#### Task 1.1: Add claim type constants

Status: **Completed**

Files:

- `backend/src/swarm/claims.py`

Steps:

1. Create `ClaimType` string constants.
2. Create `ClaimStatus` string constants.
3. Add helper `is_terminal_claim_status(status)`.

Acceptance criteria:

- Claim types include all seven target claims.
- Status constants include `draft`, `claimed`, `valid`, `invalid`, `stale`, `revoked`.
- Module imports without Redis or app dependencies.

Tests:

- Unit test that all required claim types exist.
- Unit test terminal status helper.

#### Task 1.2: Add claim schema helpers

Status: **Completed**

Files:

- `backend/src/swarm/claims.py`

Steps:

1. Add `build_claim_payload(...)`.
2. Add `claim_now_iso()`.
3. Add `normalize_evidence(...)`.

Acceptance criteria:

- Payload contains `id`, `project_id`, `claim_type`, `producer_agent`, `status`, `evidence`, `depends_on`, timestamps, and validation block.
- Evidence defaults to empty `files`, `ports`, `commands`, and `metadata`.

Tests:

- Unit test default evidence shape.
- Unit test payload has required keys.

### Phase 2: Claim Store

Status: **Completed 2026-05-07**

Implemented files:

- `backend/src/swarm/claim_store.py`
- `backend/tests/test_claim_store.py`

Verification:

- `python3 -m pytest backend/tests/test_claims.py backend/tests/test_claim_store.py backend/tests/test_swarm_coordination.py`
- `python3 -m compileall backend/src backend/tests`

#### Task 2.1: Add Redis claim store class

Status: **Completed**

Files:

- `backend/src/swarm/claim_store.py`

Steps:

1. Create `ClaimStore(redis_url)`.
2. Add `connect()` and `close()`.
3. Add key helper methods.
4. Add `save_claim(project_id, claim)`.
5. Add `get_claim(project_id, claim_id)`.
6. Add `get_latest_claim(project_id, claim_type)`.

Acceptance criteria:

- Claims are stored as JSON.
- Latest claim per type can be retrieved.
- Claim ID is added to project claim index.

Tests:

- Use a fake/in-memory store where practical or monkeypatch Redis calls.
- Test latest-claim lookup.
- Test save/load round trip.

#### Task 2.2: Add claim status update

Status: **Completed**

Files:

- `backend/src/swarm/claim_store.py`

Steps:

1. Add `update_claim_status(project_id, claim_id, status, validation=None)`.
2. Update `updated_at`.
3. Preserve original evidence and dependencies.

Acceptance criteria:

- Status update does not lose claim data.
- Validation errors and warnings are persisted.

Tests:

- Test status transition from `claimed` to `valid`.
- Test validation payload persistence.

#### Task 2.3: Add claim event publishing

Status: **Completed**

Files:

- `backend/src/swarm/claim_store.py`
- `backend/src/blackboard/redis_blackboard.py` if helper reuse is needed.

Steps:

1. Add `publish_claim_event(project_id, event_type, claim, data=None)`.
2. Publish to `project:{project_id}:events`.
3. Use AG-UI-compatible event shape.

Acceptance criteria:

- UI receives claim events on existing event stream.
- Event includes `claim_type`, `claim_id`, and `status`.

Tests:

- Monkeypatch Redis publish and assert event shape.

### Phase 3: Claim Tools

Status: **Completed 2026-05-07**

Implemented files:

- `backend/src/swarm/tools/claim_tools.py`
- `backend/tests/test_claim_tools.py`
- `backend/src/swarm/tools/__init__.py`
- `backend/src/swarm/agents.py`

Verification:

- `python3 -m pytest backend/tests/test_claims.py backend/tests/test_claim_store.py backend/tests/test_claim_tools.py backend/tests/test_swarm_coordination.py`
- `python3 -m compileall backend/src backend/tests`

#### Task 3.1: Add claim tool module

Status: **Completed**

Files:

- `backend/src/swarm/tools/claim_tools.py`

Steps:

1. Create context access for current agent and project.
2. Add `publish_claim` LangChain tool.
3. Add `wait_for_claim` LangChain tool.
4. Add non-tool `validate_claim`.
5. Add non-tool `revoke_claim`.

Acceptance criteria:

- Agents can publish claims.
- Agents can wait for valid claims.
- Validation is callable from coordinator without LLM involvement.

Tests:

- Unit test `publish_claim` builds correct claim.
- Unit test `wait_for_claim` returns only valid claim.
- Unit test wait returns error for invalid dependency failure.

#### Task 3.2: Add claim dependency resolution

Status: **Completed**

Files:

- `backend/src/swarm/tools/claim_tools.py`

Steps:

1. Add `validate_dependencies(project_id, claim)`.
2. Load latest claim for each dependency type.
3. Require dependency claim status `valid`.
4. Return structured errors if missing/stale/invalid.

Acceptance criteria:

- Missing dependency blocks validation.
- Stale dependency blocks validation.
- Valid dependencies allow validation to continue.

Tests:

- Missing dependency test.
- Invalid dependency test.
- Valid dependency test.

### Phase 4: Claim Validators

Status: **Completed 2026-05-07**

Implemented files:

- `backend/src/swarm/claim_validators.py`
- `backend/tests/test_claim_validators.py`
- `backend/src/swarm/tools/claim_tools.py`
- `backend/tests/test_claim_tools.py`

Verification:

- `python3 -m pytest backend/tests/test_claims.py backend/tests/test_claim_store.py backend/tests/test_claim_tools.py backend/tests/test_claim_validators.py backend/tests/test_swarm_coordination.py`
- `python3 -m compileall backend/src backend/tests`

#### Task 4.1: Add generic evidence validator

Status: **Completed**

Files:

- `backend/src/swarm/claim_validators.py`

Steps:

1. Add `validate_evidence_files(workspace, files)`.
2. Ensure all files remain inside workspace.
3. Ensure files exist and are regular files.

Acceptance criteria:

- Missing files produce errors.
- Path traversal is rejected.
- Empty files can be warnings or errors depending on claim type.

Tests:

- Existing file passes.
- Missing file fails.
- `../` path fails.

#### Task 4.2: Add SPEC_READY validator

Status: **Completed**

Files:

- `backend/src/swarm/claim_validators.py`

Steps:

1. Check `SPEC.md`.
2. Check non-empty content.
3. Return validation result.

Acceptance criteria:

- Empty or missing `SPEC.md` invalidates claim.

Tests:

- Missing spec fails.
- Empty spec fails.
- Valid spec passes.

#### Task 4.3: Add backend validators

Status: **Completed**

Files:

- `backend/src/swarm/claim_validators.py`

Steps:

1. Validate `BACKEND_RUNTIME_READY`.
2. Validate `BACKEND_API_READY`.
3. Parse `backend/pom.xml` enough to detect Java/Spring metadata.
4. Check source files exist.

Acceptance criteria:

- Missing `pom.xml` fails runtime claim.
- Missing API evidence fails API claim.
- Valid source/manifests pass.

Tests:

- Missing `pom.xml`.
- Valid minimal `pom.xml`.
- Missing API manifest.

#### Task 4.4: Add frontend validators

Status: **Completed**

Files:

- `backend/src/swarm/claim_validators.py`

Steps:

1. Validate `FRONTEND_SOURCE_READY`.
2. Validate `FRONTEND_BUILD_READY`.
3. Parse `frontend/package.json`.
4. Check SvelteKit dependency and build script.

Acceptance criteria:

- Invalid JSON fails.
- Missing build script fails build-ready claim.
- Valid package manifest passes.

Tests:

- Invalid JSON.
- Missing build script.
- Valid manifest.

#### Task 4.5: Add deployment validator

Status: **Completed**

Files:

- `backend/src/swarm/claim_validators.py`

Steps:

1. Validate `DEPLOYMENT_READY`.
2. Check `backend/Dockerfile`.
3. Check `frontend/Dockerfile`.
4. Check root `docker-compose.yml`.
5. Optionally parse compose YAML if dependency exists.

Acceptance criteria:

- Dockerfiles must exist.
- Compose file must exist.
- Compose references backend/frontend build contexts.

Tests:

- Missing compose fails.
- Missing Dockerfile fails.
- Valid minimal compose passes.

#### Task 4.6: Add package validator

Status: **Completed**

Files:

- `backend/src/swarm/claim_validators.py`

Steps:

1. Validate zip exists.
2. Validate zip size greater than 0.
3. Validate upload evidence exists.

Acceptance criteria:

- Missing zip fails.
- Empty zip fails.
- Valid zip passes.

Tests:

- Missing zip.
- Empty zip.
- Non-empty zip.

### Phase 5: Agent Prompt and Tool Wiring

Status: **Completed 2026-05-07**

Implemented files:

- `backend/src/swarm/agents.py`
- `backend/src/swarm/tools/__init__.py`
- `backend/tests/test_agent_claim_wiring.py`

Verification:

- `python3 -m pytest backend/tests/test_agent_claim_wiring.py backend/tests/test_claims.py backend/tests/test_claim_store.py backend/tests/test_claim_tools.py backend/tests/test_claim_validators.py backend/tests/test_swarm_coordination.py`
- `python3 -m compileall backend/src backend/tests`

#### Task 5.1: Wire claim tools into agents

Status: **Completed**

Files:

- `backend/src/swarm/agents.py`
- `backend/src/swarm/tools/__init__.py`

Steps:

1. Import `publish_claim` and `wait_for_claim`.
2. Add tools to backend/frontend/devops/packager toolsets.
3. Keep validation functions coordinator-only.

Acceptance criteria:

- Backend can call `publish_claim`.
- Frontend can call `wait_for_claim`.
- DevOps can wait for backend/frontend claims.
- Packager can wait for deployment claim.

Tests:

- Toolset construction includes expected claim tools.

#### Task 5.2: Update RootDep prompt

Status: **Completed**

Files:

- `backend/src/swarm/agents.py`

Steps:

1. Tell RootDep to publish `SPEC_READY` after writing `SPEC.md`.
2. Keep RootDep forbidden from code generation.

Acceptance criteria:

- Prompt references `SPEC_READY`.
- Prompt does not instruct RootDep to create app code.

Tests:

- String assertion test for prompt content.

#### Task 5.3: Update Backend prompt

Status: **Completed**

Files:

- `backend/src/swarm/agents.py`

Steps:

1. Tell backend to wait for `SPEC_READY`.
2. Tell backend to publish `BACKEND_RUNTIME_READY`.
3. Tell backend to publish `BACKEND_API_READY`.
4. Keep deployment artifact ban.

Acceptance criteria:

- Prompt references backend claims.
- Prompt does not reference `signal_ready`.
- Prompt forbids Docker/deployment writes.

Tests:

- String assertion test.

#### Task 5.4: Update Frontend prompt

Status: **Completed**

Files:

- `backend/src/swarm/agents.py`

Steps:

1. Tell frontend to wait for `SPEC_READY`.
2. Tell frontend to wait for `BACKEND_API_READY` when backend APIs are needed.
3. Tell frontend to publish `FRONTEND_SOURCE_READY`.
4. Tell frontend to publish `FRONTEND_BUILD_READY`.
5. Keep deployment artifact ban.

Acceptance criteria:

- Prompt references frontend claims.
- Prompt forbids Docker/deployment writes.

Tests:

- String assertion test.

#### Task 5.5: Update DevOps prompt

Status: **Completed**

Files:

- `backend/src/swarm/agents.py`

Steps:

1. Tell DevOps to wait for `BACKEND_RUNTIME_READY`.
2. Tell DevOps to wait for `FRONTEND_BUILD_READY`.
3. Tell DevOps to read real manifests.
4. Tell DevOps to publish `DEPLOYMENT_READY`.

Acceptance criteria:

- Prompt clearly states DevOps owns deployment artifacts.
- Prompt tells DevOps to derive versions from manifests.

Tests:

- String assertion test.

#### Task 5.6: Update Packager prompt

Status: **Completed**

Files:

- `backend/src/swarm/agents.py`

Steps:

1. Tell Packager to wait for `DEPLOYMENT_READY`.
2. Tell Packager to publish `PACKAGE_READY`.
3. Keep Packager forbidden from app/deployment code generation.

Acceptance criteria:

- Prompt references `DEPLOYMENT_READY` and `PACKAGE_READY`.
- Prompt forbids code generation.

Tests:

- String assertion test.

### Phase 6: Coordinator Claim Barriers

Status: **Completed 2026-05-07**

Implemented files:

- `backend/src/swarm/agents.py`
- `backend/tests/test_swarm_coordination.py`

Verification:

- `python3 -m pytest backend/tests/test_agent_claim_wiring.py backend/tests/test_claims.py backend/tests/test_claim_store.py backend/tests/test_claim_tools.py backend/tests/test_claim_validators.py backend/tests/test_swarm_coordination.py`
- `python3 -m compileall backend/src backend/tests`

#### Task 6.1: Publish SPEC_READY in plan mode

Status: **Completed**

Files:

- `backend/src/main.py`
- `backend/src/swarm/agents.py`

Steps:

1. After plan RootDep finishes, publish `SPEC_READY`.
2. Validate `SPEC_READY`.
3. Store claim status.
4. Keep existing `PlanReady` UI event.

Acceptance criteria:

- Plan mode leaves a valid `SPEC_READY` claim.
- UI behavior is unchanged.

Tests:

- Plan-mode unit test with fake claim store.

#### Task 6.2: Restore SPEC_READY in approved mode

Status: **Completed**

Files:

- `backend/src/swarm/agents.py`

Steps:

1. In `run_mode=approved`, skip RootDep.
2. Validate existing `SPEC.md`.
3. Publish or restore valid `SPEC_READY`.
4. Fail if missing/invalid.

Acceptance criteria:

- Approved build never invokes RootDep.
- Missing `SPEC.md` fails early.

Tests:

- Existing approved-mode tests remain passing.
- Add assertion that `SPEC_READY` is valid before backend starts.

#### Task 6.3: Replace backend_api dependency signal

Status: **Completed**

Files:

- `backend/src/swarm/tools/coordination.py`
- `backend/src/swarm/agents.py`

Steps:

1. Deprecate backend-specific `signal_ready('backend_api')` path.
2. Replace frontend dependency with `wait_for_claim('BACKEND_API_READY')`.
3. Keep old function only for compatibility if needed.

Acceptance criteria:

- Frontend no longer depends on raw Redis dependency key.
- Backend API readiness is evidence-backed.

Tests:

- Frontend waits for claim, not dependency key.

#### Task 6.4: Gate DevOps by claims

Status: **Completed**

Files:

- `backend/src/swarm/agents.py`

Steps:

1. Before DevOps starts, validate latest `BACKEND_RUNTIME_READY`.
2. Validate latest `FRONTEND_BUILD_READY`.
3. Start DevOps only when both are valid.

Acceptance criteria:

- DevOps does not start on agent completion alone.
- DevOps starts on valid claims.

Tests:

- Missing backend claim blocks DevOps.
- Missing frontend claim blocks DevOps.
- Valid claims allow DevOps.

#### Task 6.5: Gate Packager by DEPLOYMENT_READY

Status: **Completed**

Files:

- `backend/src/swarm/agents.py`

Steps:

1. Before packager starts, validate latest `DEPLOYMENT_READY`.
2. Ensure dependent claims remain valid.
3. Start packager only after stabilization window.

Acceptance criteria:

- Packager cannot start without valid deployment claim.
- Stale dependent claim blocks packager.

Tests:

- Missing deployment claim blocks packager.
- Stale deployment claim blocks packager.
- Valid deployment claim allows packager.

### Phase 7: Claim Revocation and Staleness

Status: **Completed 2026-05-07**

Implemented files:

- `backend/src/swarm/claims.py`
- `backend/src/swarm/claim_store.py`
- `backend/src/swarm/tools/claim_tools.py`
- `backend/src/swarm/agents.py`
- `backend/tests/test_claim_tools.py`
- `backend/tests/test_claim_store.py`
- `backend/tests/test_swarm_coordination.py`

Verification:

- `python3 -m pytest backend/tests/test_claims.py backend/tests/test_claim_store.py backend/tests/test_claim_tools.py backend/tests/test_claim_validators.py backend/tests/test_agent_claim_wiring.py backend/tests/test_swarm_coordination.py`
- `python3 -m compileall backend/src backend/tests`

#### Task 7.1: Track producer activity after claim

Status: **Completed**

Files:

- `backend/src/swarm/agents.py`
- `backend/src/swarm/claim_store.py`
- `backend/src/swarm/tools/claim_tools.py`
- `backend/src/swarm/claim_validators.py`

Steps:

1. Store `producer_event_seq` on claim at publish time (read from Redis).
2. Persist agent event sequence to Redis on every mutating event (`_record_agent_activity`).
3. **Evidence drift detection** (`check_evidence_drift`): Compare each evidence file's `mtime` against the claim's `created_at`. If any evidence was modified after the claim was published, the claim is stale. This is the authoritative staleness signal.
4. Event-seq comparison is kept as a supplementary **warning** in validation. It does not auto-stale on its own (avoids false positives when agents publish sequential claims within the same run).
5. Auto-stale all valid claims from an agent when it becomes `inconsistent` (post-completion activity).

Acceptance criteria:

- Evidence modified after claim publication makes the claim stale.
- `inconsistent` agent automatically triggers cascading staleness of all its valid claims.
- Event-seq gap produces a diagnostic warning but does not falsely stale valid claims from agents that publish multiple sequential claims.

Tests:

- Evidence file modified after claim time → validation marks claim stale.
- Evidence file unmodified after claim time → validation stays valid even if event-seq gap is large.
- Inconsistent agent auto-stales its valid claims.

#### Task 7.2: Revoke dependent claims

Status: **Completed**

Files:

- `backend/src/swarm/claims.py`
- `backend/src/swarm/claim_store.py`
- `backend/src/swarm/tools/claim_tools.py`

Steps:

1. Add `CLAIM_DEPENDENCIES` forward graph and `get_claim_dependents()` reverse lookup.
2. Add `_cascade_staleness()` helper that traverses the dependency graph and marks all valid dependent claims stale.
3. Invoke cascade when a claim is revoked, when validation detects staleness, and when a claim is superseded.
4. Publish `claim_stale` events for every affected claim.

Acceptance criteria:

- Stale backend claim marks frontend and deployment claims stale.
- Stale deployment claim blocks packager.
- Cascade is idempotent (re-running does not duplicate errors).

Tests:

- Dependency cascade test: revoke BACKEND_API_READY → FRONTEND_BUILD_READY and DEPLOYMENT_READY become stale.
- Idempotency: cascading twice affects dependents only once.

#### Task 7.3: Add claim replacement

Status: **Completed**

Files:

- `backend/src/swarm/tools/claim_tools.py`

Steps:

1. When `publish_claim_record` saves a new claim, check for an existing latest claim of the same type.
2. If a previous latest exists, mark it `stale` with reason "Superseded by newer claim of the same type."
3. Publish `claim_stale` event for the superseded claim.
4. Cascade staleness to all dependents of the superseded claim.
5. Save the new claim and update the latest claim pointer.

Acceptance criteria:

- Latest claim lookup returns newest claim.
- Historical claims remain inspectable.
- Superseded claims are explicitly marked stale with a clear reason.

Tests:

- Publish two claims of same type; latest returns second; first is stale.
- Superseding a claim cascades staleness to its dependents.

### Phase 8: UI Telemetry

#### Task 8.1: Add claim event type

Files:

- `frontend/src/lib/types.ts`
- `frontend/src/lib/agent-registry.svelte.ts`
- `frontend/src/lib/aguiclient.ts`

Steps:

1. Add claim event type.
2. Add claim status types.
3. Store claims in registry.

Acceptance criteria:

- Claim events do not break current stream.
- UI state can list claims by type/status.

Tests:

- Type check passes.
- Claim event dispatch updates registry.

#### Task 8.2: Add claim panel

Files:

- `frontend/src/lib/components/mesh/AgentDetail.svelte`
- Optional new `frontend/src/lib/components/mesh/ClaimPanel.svelte`

Steps:

1. Show claim type.
2. Show status.
3. Show producing agent.
4. Show evidence file count.
5. Show validation errors.

Acceptance criteria:

- User can see why packager is waiting.
- Stale/invalid claims are visually distinct.

Tests:

- `npm run check`.

### Phase 9: Migration and Compatibility

#### Task 9.1: Keep legacy events during transition

Files:

- `backend/src/swarm/agents.py`
- `backend/src/swarm/tools/coordination.py`

Steps:

1. Keep `complete` events for UI compatibility.
2. Add claim events in parallel.
3. Do not remove existing progress telemetry.

Acceptance criteria:

- Existing UI does not regress.
- New claim data is available.

Tests:

- Current coordination tests pass.

#### Task 9.2: Deprecate raw dependency keys

Files:

- `backend/src/swarm/tools/coordination.py`

Steps:

1. Mark `wait_on_agent` as compatibility-only.
2. Route new prompts to `wait_for_claim`.
3. Remove backend-specific dependency signaling after claim flow is stable.

Acceptance criteria:

- No prompt tells agents to use `signal_ready`.
- Frontend prompt uses claim wait.

Tests:

- Prompt assertions.

---

## 10. Implementation Order

Recommended order:

1. Claim constants and schema.
2. Claim store.
3. Claim validators.
4. Claim tools.
5. Publish `SPEC_READY` in plan and approved modes.
6. Backend publishes backend claims.
7. Frontend waits for backend claim and publishes frontend claims.
8. DevOps waits for app claims and publishes deployment claim.
9. Packager waits for deployment claim and publishes package claim.
10. Revocation and stale dependency cascade.
11. UI telemetry.
12. Remove legacy dependency reliance.

---

## 11. Definition of Done

The claim protocol is complete when:

- Approved builds skip RootDep and reuse approved `SPEC.md`.
- Backend/frontend/devops/packager publish evidence-backed claims.
- Frontend waits for `BACKEND_API_READY`, not raw backend completion.
- DevOps waits for backend/frontend claims and derives Docker config from manifests.
- Packager waits for `DEPLOYMENT_READY`.
- Any post-claim producer activity marks the claim stale.
- Stale claims cascade to dependent claims.
- Packager cannot start if any required claim is missing, invalid, or stale.
- UI exposes claim status clearly enough to diagnose why the swarm is waiting.
- Tests cover missing claims, stale claims, false done, dependency cascade, and approved-plan build.

---

## 12. Test Matrix

| Scenario | Expected Result |
|----------|-----------------|
| Plan mode completes | `SPEC_READY` valid |
| Approved build starts | RootDep skipped |
| Approved build missing `SPEC.md` | Build fails early |
| Backend publishes runtime claim with missing `pom.xml` | Claim invalid |
| Backend publishes API claim before runtime claim | Claim invalid |
| Frontend waits before backend API claim | Frontend blocks |
| Backend changes file after API claim | API claim stale |
| Frontend build claim depends on stale backend API claim | Frontend claim stale/invalid |
| DevOps starts without frontend build claim | DevOps blocked |
| DevOps deployment claim missing compose | Claim invalid |
| Packager starts without deployment claim | Packager blocked |
| Deployment claim becomes stale before package | Packager blocked |
| Package upload succeeds | `PACKAGE_READY` valid |

---

## 13. Risks

### Risk: Too much centralization

Mitigation:

- Keep validation protocol-based.
- Let agents publish claims independently.
- Do not move implementation decisions into the coordinator.

### Risk: Claim validation becomes brittle

Mitigation:

- Start with evidence existence and dependency validity.
- Add deeper parsing gradually.
- Treat non-critical details as warnings first.

### Risk: Legacy UI confusion

Mitigation:

- Keep current events.
- Add claim events incrementally.
- Show both agent progress and claim progress during transition.

### Risk: Agents forget to publish claims

Mitigation:

- Coordinator can synthesize minimal claims from known artifacts during transition.
- Prompt tests ensure claim instructions remain present.
- Packager gate makes missing claims visible.

---

## 14. Effort Estimate

Backend-only claim protocol:

- Claim model and store: 0.5 day
- Validators and tools: 0.5 to 1 day
- Agent prompt/tool wiring: 0.5 day
- Coordinator barrier replacement: 0.5 to 1 day
- Tests: 0.5 day

Estimated backend total: 2 to 3 focused days.

UI telemetry:

- Claim state handling: 0.5 day
- Claim panel: 0.5 to 1 day

Estimated UI total: 1 to 1.5 focused days.

Recommended first implementation milestone:

- Backend-only protocol with no UI panel.
- Keep current UI progress.
- Emit claim events for future UI.
- Gate packager by `DEPLOYMENT_READY`.

Estimated first milestone: 1.5 to 2 focused days.

---

## 15. Non-Goals

- Do not introduce a master agent.
- Do not remove agent autonomy.
- Do not block all parallelism permanently.
- Do not require full Docker builds during claim validation in the first milestone.
- Do not replace all current UI progress with claim UI in the first backend milestone.
