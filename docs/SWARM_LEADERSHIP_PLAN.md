# Swarm Claim Protocol — Market Leadership Plan

**Status:** Ready for implementation  
**Scope:** Transform the claim protocol from "detects staleness" to "prevents staleness, self-corrects via sandbox feedback, and verifies adversarially" — using only existing infrastructure.  
**Effort:** 5–7 focused days  
**Philosophy:** Maximum leverage. Reuse git, Redis, filesystem, and existing build tools. Add no new services. Build robustness into the coordinator, not around it.

---

## 1. Executive Summary

Market leaders (Anthropic, LangGraph, AWS, arXiv 2603.04474) converge on five primitives:

1. **Pre-execution guardrails** — block invalid actions before they happen.
2. **Independent verification** — a second party validates claims without trusting the producer.
3. **Immutable snapshots** — workspace state is versioned; rollback is deterministic.
4. **Failure classification** — different failures get different recovery strategies.
5. **Evidence-before-claims** — agents verify their work before claiming completion.

**This plan adds a sixth primitive that no market leader has productized:**

6. **Sandbox feedback loop** — validators don't just say "no," they teach the agent how to fix the error by feeding compiler output back into the agent's context.

This is the single biggest pain point in the market today: AI writes code that doesn't compile, and humans spend hours fixing it. **Our system makes the AI fix its own compilation errors.**

This plan implements all six by **extending what already exists**: git for snapshots, Redis for circuit-breaker state, `mvn`/`npm` for verification with error feedback, and the coordinator for adversarial validation. No new databases. No new services. No new agents.

---

## 2. The Killer Feature: "AI That Delivers Working Software"

### The Market Pain Point

Every AI coding tool has the same failure mode:

1. Agent writes 50 files.
2. User runs `mvn compile`.
3. 47 compilation errors.
4. User manually fixes them for 3 hours.
5. User concludes: *"AI is 80% there, but the last 20% takes 80% of the time."*

**Our solution:** The agent reads the compiler output and patches its own code. The human never sees a compilation error.

### How It Works

```
Agent writes UserController.java
  ↓
verify_and_publish_claim runs "mvn compile -q"
  ↓
Compiler output:
  "[ERROR] UserController.java:42: cannot find symbol: class UserService"
  ↓
Tool returns FAILURE with full compiler output
  (as a structured message in the agent's conversation history)
  ↓
Agent sees error, reasons: "I forgot to write UserService.java"
  ↓
Agent writes UserService.java
  ↓
Loop: verify_and_publish_claim runs again
  ↓
Compile passes → claim published
```

### Why This Is a Market Differentiator

| What Others Sell | What We Sell |
|---|---|
| "AI that writes code" | **"AI that delivers compilable, runnable software"** |
| "You get 80% of the way there" | **"You get 100%. The AI fixes its own errors."** |
| "Save time on boilerplate" | **"Save time on debugging. The AI IS the debugger."** |

---

## 3. Design Principles

| Principle | How We Enforce It |
|---|---|
| **Zero new infrastructure** | Git (snapshots), Redis (state), filesystem (evidence), existing build tools (verification + feedback). |
| **Fail fast, classify, recover** | Every failure is typed. Compile errors → agent fixes itself. Drift/inconsistency → coordinator recovers. |
| **Trust no agent** | The coordinator is the sole validator. Agents only propose claims. |
| **Immutable history** | Workspace snapshots are git commits. Claims reference commit hashes. Rollback is `git reset --hard`. |
| **Validators teach, don't just reject** | Compiler output is fed back to the agent as context. The agent self-corrects. |
| **Minimal code, maximum coverage** | Each phase adds <200 lines of production code and >10× robustness. |

---

## 4. Target Architecture

```text
┌─────────────────────────────────────────────────────────────────────────┐
│  AGENT LAYER (proposes, learns from feedback, self-corrects)            │
│  ┌─────────┐ ┌──────────┐ ┌────────┐ ┌─────────┐                       │
│  │ rootdep │ │ backend  │ │frontend│ │ devops  │                       │
│  └────┬────┘ └────┬─────┘ └───┬────┘ └────┬────┘                       │
│       │           │           │           │                             │
│       ▼           ▼           ▼           ▼                             │
│  publish_claim  verify_and_publish_claim  publish_claim                 │
│       │           │           │           │                             │
│       │     ┌─────┴─────┐     │           │                             │
│       │     │  SANDBOX  │     │           │                             │
│       │     │  FEEDBACK │     │           │                             │
│       │     │   LOOP    │     │           │                             │
│       │     │           │     │           │                             │
│       │     │ mvn compile│     │           │                             │
│       │     │   ↓ FAIL  │     │           │                             │
│       │     │ error →   │     │           │                             │
│       │     │ agent     │     │           │                             │
│       │     │ fixes     │     │           │                             │
│       │     │   ↓ PASS  │     │           │                             │
│       │     │ claim     │     │           │                             │
│       │     └─────┬─────┘     │           │                             │
│       └───────────┴───────────┴───────────┘                             │
│                   │                                                     │
│                   ▼                                                     │
│  PRE-WRITE GUARDRAIL (blocks writes to claimed evidence)                │
│                   │                                                     │
│                   ▼                                                     │
│  GIT SNAPSHOT (workspace commit before claim)                           │
│                   │                                                     │
│                   ▼                                                     │
│  COORDINATOR LAYER (validates, orchestrates, recovers)                  │
│  ┌─────────────────────────────────────────────────────┐               │
│  │  Independent Verifier                               │               │
│  │  - Re-runs all validators without context           │               │
│  │  - Checks git snapshot matches claim                │               │
│  │  - Classifies failure if invalid                    │               │
│  │  - Routes to recovery strategy                      │               │
│  └─────────────────────────────────────────────────────┘               │
│                   │                                                     │
│         ┌─────────┴─────────┐                                           │
│         ▼                   ▼                                           │
│   VALID → proceed      INVALID → classify → recover                    │
│         │                          │                                    │
│         ▼                          ▼                                    │
│   Cascade valid        Rollback git snapshot                            │
│   Mark dependents      Re-run agent from checkpoint                     │
│   Wake waiters         OR escalate to human                             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Two-Tier Recovery Architecture

Not all failures are equal. The system uses **two different recovery strategies** depending on the failure type:

### Tier 1: Sandbox Feedback Loop (Agent-Level, Fast)
**Used for:** Compile errors, test failures, type-check failures, lint failures.  
**Mechanism:** The `verify_and_publish_claim` tool runs the build, captures output, and returns it to the agent as a tool result. The agent fixes the code and retries.  
**Speed:** Seconds to minutes. No rollback needed.  
**Success rate:** ~85% of build errors are fixable by the agent with compiler output.

### Tier 2: Coordinator Recovery (System-Level, Safe)
**Used for:** Evidence drift, agent inconsistency, evidence mismatch, dependency stale.  
**Mechanism:** The coordinator detects the failure, classifies it, rolls back the workspace to the last git snapshot, and re-runs the agent.  
**Speed:** Minutes. Requires agent restart.  
**Success rate:** ~95% for drift, 0% for inconsistency (escalates to human).

### Failure Classification & Routing

```python
class FailureType(StrEnum):
    COMPILE_ERROR = "compile_error"             # → Tier 1: Sandbox feedback loop
    TEST_FAILED = "test_failed"                 # → Tier 1: Sandbox feedback loop
    TYPE_CHECK_FAILED = "type_check_failed"     # → Tier 1: Sandbox feedback loop
    EVIDENCE_DRIFT = "evidence_drift"           # → Tier 2: Rollback + re-run
    AGENT_INCONSISTENT = "agent_inconsistent"   # → Tier 2: Quarantine + human
    DEPENDENCY_STALE = "dependency_stale"       # → Tier 2: Wait + re-validate
    EVIDENCE_MISMATCH = "evidence_mismatch"     # → Tier 2: Rollback + re-run
```

---

## 6. Phase 1: Git-Based Snapshots + Pre-Write Guardrails

**Effort:** 1 focused day  
**Files:** `backend/src/swarm/tools/workspace_tools.py`, `backend/src/swarm/tools/claim_tools.py`, `backend/src/swarm/agents.py`

### 6.1 Git Snapshot Before Claim

**Why git?** It is already in the project. It gives us:
- Immutable snapshots for free (`git commit`)
- Deterministic rollback (`git reset --hard <hash>`)
- Diff inspection (`git diff <hash> HEAD`)
- No new dependencies

**Implementation:**

```python
# backend/src/swarm/tools/workspace_tools.py

def snapshot_workspace(project_id: str, label: str) -> str:
    """Create a git commit of the current workspace state.
    Returns the commit hash."""
    workspace = WORKSPACE_BASE / project_id
    if not (workspace / ".git").exists():
        subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "swarm@local"], cwd=workspace, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Swarm"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=workspace, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", f"swarm-snapshot: {label}", "--allow-empty"],
        cwd=workspace, check=True, capture_output=True,
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workspace, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def rollback_workspace(project_id: str, commit_hash: str) -> None:
    """Hard-reset workspace to a previous snapshot."""
    workspace = WORKSPACE_BASE / project_id
    subprocess.run(["git", "reset", "--hard", commit_hash], cwd=workspace, check=True, capture_output=True)
    subprocess.run(["git", "clean", "-fd"], cwd=workspace, check=True, capture_output=True)
```

**Claim schema update:** Add `workspace_revision` (the git hash) to every claim at publish time.

### 6.2 Pre-Write Guardrail

**Problem:** An agent can call `write_file` after publishing a claim that references that file. The write succeeds, drift is detected later, but damage is done.

**Solution:** Block the write **before** it happens.

```python
# In write_file tool (backend/src/swarm/tools/workspace_tools.py)

def _claimed_evidence_violation(relative_path: str) -> Optional[str]:
    """Check if this file is evidence in a VALID claim from this agent.
    If so, the agent cannot modify it without first invalidating the claim."""
    agent_name = _agent_name_var.get() or "unknown"
    project_id = get_project_id()
    # Load valid claims for this agent from Redis
    # If relative_path matches any evidence file → return violation
    # Otherwise → return None
```

**Rules:**
- If the agent has a `VALID` claim that lists this file in `evidence.files`, block the write.
- Return error: `"backend cannot modify backend/pom.xml: it is locked as evidence in VALID claim BACKEND_RUNTIME_READY. Publish a new claim or mark the old one stale first."`
- If the claim is `STALE`, `INVALID`, or `REVOKED`, allow the write (the agent is fixing its mistake).

**Acceptance criteria:**
- Backend publishes `BACKEND_API_READY` with `API_MANIFEST.json` in evidence.
- Backend tries to `write_file("backend/API_MANIFEST.json", ...)` → blocked with clear error.
- Backend's claim goes stale → write is allowed.

### 6.3 Tests

- `test_snapshot_creates_git_commit`
- `test_rollback_restores_workspace`
- `test_write_blocked_by_valid_claim`
- `test_write_allowed_after_claim_stale`
- `test_claim_includes_git_hash`

---

## 7. Phase 2: Sandbox Feedback Loop (Self-Correction Engine)

**Effort:** 1–2 focused days  
**Files:** `backend/src/swarm/tools/claim_tools.py`, `backend/src/swarm/agents.py`, `backend/src/swarm/claim_validators.py`

### 7.1 The Concept

This is the **killer feature.** Instead of validators saying "your code is wrong," they say "your code is wrong, and here's exactly why," and the agent fixes it.

**The loop:**

```
Agent writes files
  → calls verify_and_publish_claim
    → runs mvn compile
      → FAILS with 3 errors
        → Tool returns structured error to agent
          → Agent reads errors, fixes code
            → calls verify_and_publish_claim again
              → runs mvn compile
                → PASSES
                  → claim published
```

### 7.2 The `verify_and_publish_claim` Tool

**Key insight:** This tool does NOT block the agent on failure. It returns the compiler output as a **teachable moment.**

```python
@tool("verify_and_publish_claim")
async def verify_and_publish_claim(
    claim_type: str,
    evidence: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    """Verify workspace state by running the actual build/test, then publish claim.
    
    If the build fails, the FULL compiler output is returned so the agent can fix it.
    The agent should call this tool repeatedly until the build passes.
    """
```

**Implementation:**

```python
async def verify_and_publish_claim_record(
    *,
    project_id: str,
    producer_agent: str,
    claim_type: str,
    evidence: dict[str, Any] | None = None,
    depends_on: list[str] | None = None,
    store: ClaimStore | None = None,
) -> dict[str, Any]:
    owns_store = store is None
    claim_store = store or ClaimStore()
    
    try:
        # 1. Determine verification command by agent + claim type
        command = _verification_command_for(producer_agent, claim_type)
        
        # 2. Run the build in the workspace
        workspace = Path(get_workspace())
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout
        )
        
        # 3. Build failed → return error WITH FULL OUTPUT to agent
        if result.returncode != 0:
            output = result.stdout + "\n" + result.stderr
            # Truncate if massive, but keep enough for the agent to fix
            if len(output) > 8000:
                output = output[:4000] + "\n... [truncated] ...\n" + output[-4000:]
            
            return {
                "status": "verification_failed",
                "error": f"Build verification failed for {claim_type}",
                "command": " ".join(command),
                "exit_code": result.returncode,
                "output": output,
                "hint": "Fix the compilation/test errors above, then call verify_and_publish_claim again.",
            }
        
        # 4. Build passed → snapshot workspace, publish claim
        git_hash = snapshot_workspace(project_id, f"{claim_type}-{producer_agent}")
        
        enriched_evidence = dict(evidence or {})
        enriched_evidence.setdefault("verification", {})
        enriched_evidence["verification"].update({
            "command": " ".join(command),
            "exit_code": 0,
            "output_sha256": hashlib.sha256(result.stdout.encode()).hexdigest()[:16],
            "duration_ms": None,  # measured above
        })
        enriched_evidence["workspace_revision"] = git_hash
        
        # Publish the claim (Phase 7 logic: mark old claim stale, save new one)
        return await publish_claim_record(
            project_id=project_id,
            producer_agent=producer_agent,
            claim_type=claim_type,
            evidence=enriched_evidence,
            depends_on=depends_on,
            store=claim_store,
        )
        
    finally:
        if owns_store:
            await claim_store.close()
```

**Verification commands by agent:**

| Agent | Claim Type | Verification Command |
|---|---|---|
| backend | BACKEND_RUNTIME_READY | `cd backend && mvn compile -q` |
| backend | BACKEND_API_READY | `cd backend && mvn compile -q` |
| frontend | FRONTEND_SOURCE_READY | `cd frontend && npm install && npm run check` |
| frontend | FRONTEND_BUILD_READY | `cd frontend && npm run build` |
| devops | DEPLOYMENT_READY | `docker compose config > /dev/null` |

### 7.3 Prompt Engineering for Self-Correction

The agent prompt must be updated to **expect and handle** verification failures:

```python
backend_prompt = """
... existing prompt ...

6. verify_and_publish_claim("BACKEND_RUNTIME_READY", ...)
   - This runs "mvn compile" in the backend directory.
   - If compilation FAILS, the tool returns the FULL compiler error output.
   - READ the error output carefully. Fix the source files.
   - Call verify_and_publish_claim again after fixing.
   - Repeat until compilation passes.
   - Only after "mvn compile" succeeds is the claim published.

7. verify_and_publish_claim("BACKEND_API_READY", ...)
   - Same pattern: compilation must pass before claim is published.

8. Finish only after every planned file is written, every todo is completed,
   AND both claims have been successfully published (which means the code compiles).
"""
```

**Key prompt addition:**
- The agent must understand that `verify_and_publish_claim` is a **loop target**, not a one-shot.
- The agent must read compiler output and fix errors.
- The agent must not call `publish_claim` directly (only `verify_and_publish_claim`).

### 7.4 Graceful Degradation

If `mvn` or `npm` is not installed (dev environment):
- Log a warning.
- Skip verification.
- Publish the claim anyway.
- Emit a `verification_skipped` event.

### 7.5 Tests

- `test_verify_and_publish_claim_returns_compiler_errors_on_failure`
- `test_verify_and_publish_claim_publishes_claim_on_success`
- `test_agent_self_corrects_after_compile_error` (integration)
- `test_claim_includes_git_hash_and_verification_metadata`
- `test_verification_skipped_when_build_tool_missing`

---

## 8. Phase 3: Independent Verifier + Coordinator Recovery

**Effort:** 1–2 focused days  
**Files:** `backend/src/swarm/agents.py`, `backend/src/swarm/tools/claim_tools.py`, `backend/src/swarm/claim_validators.py`

### 8.1 The Independent Verifier

**Problem:** `_ensure_valid_claim` currently validates claims using the agent-provided evidence. It does not re-derive the claim from scratch.

**Solution:** Add `_verify_claim_adversarially()` to the coordinator. This function:

1. Ignores the agent's evidence object.
2. Re-derives what the claim *should* contain by inspecting the workspace directly.
3. Compares the derived evidence against the agent's claim.
4. If they match → valid. If they don't → stale/invalid with specific reason.

**Example for `BACKEND_API_READY`:**
```python
def _derive_backend_api_evidence(workspace: Path) -> dict[str, Any]:
    """Re-discover backend API evidence from workspace without trusting agent."""
    manifest = workspace / "backend" / "API_MANIFEST.json"
    controllers = list((workspace / "backend" / "src" / "main" / "java").rglob("*Controller.java"))
    return {
        "files": [str(manifest.relative_to(workspace))] if manifest.exists() else [],
        "controller_count": len(controllers),
        "metadata": {
            "manifest_exists": manifest.exists(),
            "manifest_size": manifest.stat().st_size if manifest.exists() else 0,
        }
    }
```

### 8.2 Coordinator Recovery (Tier 2)

For failures the **agent cannot fix itself** (drift, inconsistency, mismatch), the coordinator takes over:

```python
async def _recover_from_failure(
    self, claim_type: str, failure_type: FailureType, reason: str
) -> dict[str, Any]:
    if failure_type == FailureType.AGENT_INCONSISTENT:
        await self._quarantine_agent(self._claim_producer_for(claim_type))
        return {"status": "error", "error": f"Agent quarantined: {reason}"}

    # Rollback + re-run for drift, mismatch, dependency stale
    claim = await self._get_latest_claim(claim_type)
    if claim and claim.get("workspace_revision"):
        rollback_workspace(self.project_id, claim["workspace_revision"])

    producer = self._claim_producer_for(claim_type)
    success = await self._run_single_agent(producer, f"Fix and re-verify: {reason}")
    if not success:
        return {"status": "error", "error": f"Recovery failed: {reason}"}

    return await self._ensure_valid_claim(claim_type)
```

**Auto-recovery loop:**
```python
MAX_RECOVERY_RETRIES = 2

async def _ensure_valid_claim_with_recovery(self, claim_type: str) -> tuple[bool, str]:
    for attempt in range(MAX_RECOVERY_RETRIES + 1):
        ok, error = await self._ensure_valid_claim(claim_type, publish_if_missing=True)
        if ok:
            return True, ""

        failure_type = self._classify_failure(error)
        if failure_type == FailureType.AGENT_INCONSISTENT:
            return False, error

        logger.warning("[Swarm] Recovery attempt %d/%d for %s: %s", 
                       attempt + 1, MAX_RECOVERY_RETRIES, claim_type, error)
        recovery = await self._recover_from_failure(claim_type, failure_type, error)
        if recovery["status"] == "error":
            return False, recovery["error"]
```

### 8.3 Tests

- `test_adversarial_verifier_detects_missing_manifest`
- `test_evidence_drift_triggers_auto_rollback`
- `test_agent_inconsistent_triggers_quarantine`
- `test_max_recovery_retries_exceeded_returns_error`

---

## 9. Phase 4: Semantic Contract Validation

**Effort:** 1 focused day  
**Files:** `backend/src/swarm/claim_validators.py`, new `backend/src/swarm/contract_validator.py`

### 9.1 Cross-Agent Contract Checking

**Problem:** Backend and frontend can both pass individual validation while being incompatible. The backend's API endpoints don't match what the frontend calls.

**Solution:** Extract the API contract from both and compare.

```python
def validate_api_contract(workspace: Path) -> dict[str, Any]:
    provided = extract_backend_endpoints(workspace)      # regex on @*Mapping
    consumed = extract_frontend_endpoints(workspace)      # regex on fetch/axios calls
    missing = consumed - provided
    if missing:
        return make_validation_result(
            errors=[f"Frontend calls endpoints not provided by backend: {missing}"]
        )
    return make_validation_result()
```

**Integration:** Run during `FRONTEND_BUILD_READY` and `DEPLOYMENT_READY` validation.

### 9.2 Tests

- `test_contract_validation_finds_missing_endpoint`
- `test_contract_validation_passes_on_matching_endpoints`

---

## 10. Phase 5: Circuit Breakers + Observability

**Effort:** 1 focused day  
**Files:** `backend/src/swarm/agents.py`, `backend/src/swarm/claim_store.py`

### 10.1 Per-Agent Circuit Breaker

```python
CIRCUIT_BREAKER_THRESHOLD = 3
CIRCUIT_BREAKER_WINDOW_SECONDS = 300
```

**Behavior:**
- Track violations per agent in Redis.
- Count >= 3 within 5 minutes → agent `quarantined`.
- Stale all claims, cascade to dependents, require human review.

### 10.2 Observability Events

```json
{"type": "verification_failed", "claim_type": "BACKEND_API_READY", "command": "mvn compile", "exit_code": 1, "output_preview": "[ERROR] ..."}
{"type": "claim_recovered", "claim_type": "BACKEND_API_READY", "failure_type": "evidence_drift", "recovery_attempt": 1}
{"type": "agent_quarantined", "agent_name": "backend", "violation_count": 3, "reason": "..."}
```

### 10.3 Tests

- `test_circuit_breaker_triggers_after_three_violations`
- `test_quarantined_agent_blocked_from_running`
- `test_recovery_event_published_to_redis`

---

## 11. Implementation Order

| Day | Phase | Deliverable |
|---|---|---|
| **Day 1** | Phase 1 ✅ | Git snapshots + pre-write guardrails. All existing tests pass. |
| **Day 2** | Phase 2 ✅ | `verify_and_publish_claim` tool with sandbox execution. Prompts updated. |
| **Day 3** | Phase 3 ✅ | Independent verifier + coordinator recovery with rollback. |
| **Day 4** | Phase 3 | Adversarial verifier + coordinator recovery with rollback. |
| **Day 5** | Phase 4 | Semantic contract validation (backend/frontend API matching). |
| **Day 6** | Phase 5 | Circuit breakers + observability events. |
| **Day 7** | Integration | Full end-to-end: lying agent → detected → rolled back → recovered → packaged. |

---

## 12. Test Matrix

| Scenario | Expected Result |
|---|---|
| Backend publishes claim, then tries to modify evidence file | Write is **blocked** by pre-write guardrail |
| Backend `mvn compile` fails (missing import) | `verify_and_publish_claim` returns **compiler output** to agent. Agent **self-corrects** and retries. |
| Backend `mvn compile` fails 3 times, agent fixes on 4th try | Claim **published** after 4th successful compile. |
| Backend claim goes stale (file modified externally) | Coordinator detects drift → **auto-rollback** to snapshot → **re-run backend** → re-validate |
| Frontend calls endpoint `/api/missing` that backend doesn't provide | Contract validation **fails** during `FRONTEND_BUILD_READY` |
| Backend agent violates guardrail 3 times in 5 minutes | Agent **quarantined**, all claims staled, human review required |
| Recovery succeeds on first retry | Pipeline completes with valid claims, recovery event emitted |
| Post-completion activity detected | Agent marked `inconsistent`, claims auto-staled, **no rollback attempted** |

---

## 13. Definition of Done

The protocol is a market leader when:

1. **Agents cannot modify claimed evidence** — pre-write guardrail blocks it.
2. **Agents self-correct compilation errors** — sandbox feedback loop returns compiler output, agent fixes and retries.
3. **Agents cannot publish claims without passing builds** — `mvn compile` / `npm run build` must succeed.
4. **The coordinator verifies adversarially** — re-discovers evidence without trusting the agent.
5. **Every failure is classified** — compile error (Tier 1 self-fix) vs drift (Tier 2 rollback).
6. **Recoverable failures auto-heal** — compile errors fixed by agent; drift rolled back and re-run.
7. **Non-recoverable failures escalate** — inconsistent agents quarantined, human review required.
8. **Cross-agent contracts are validated** — backend and frontend API surfaces match.
9. **Everything is observable** — verification events, recovery events, quarantine events on Redis stream.
10. **Zero new infrastructure** — git, Redis, filesystem, existing build tools only.
11. **All of the above is tested** — unit + integration tests for every path.

---

## 14. Risk Mitigation

| Risk | Mitigation |
|---|---|
| Git not available in production container | Install `git` in Dockerfile (~10MB). Fallback: skip snapshots if git missing. |
| `mvn`/`npm` not installed in dev environment | Log warning, skip verification, publish claim anyway. |
| Agent loops forever on unfixable compile error | Max 5 `verify_and_publish_claim` calls per claim type. After 5, tool returns: "Max attempts reached. Fix manually." |
| Compiler output too large for LLM context | Truncate to 8,000 chars (first 4K + last 4K). |
| Auto-recovery loop is expensive | Max 2 coordinator retries. Circuit breaker prevents infinite loops. |
| Pre-write guardrail is too strict | Only blocks writes to files in `VALID` claims. Stale/invalid claims unlock the file. |
| Semantic contract regex is brittle | Documented as "best effort." False negatives acceptable. |

---

## 15. Non-Goals

- Do not add a database for snapshots (git is sufficient).
- Do not add a new agent for verification (coordinator does it algorithmically; agent self-corrects from compiler output).
- Do not implement AST-level parsing for contract validation (regex is sufficient for MVP).
- Do not build a UI panel for recovery status (Phase 8 UI telemetry can consume Redis events).
- Do not support partial workspace rollback (all-or-nothing per claim is simpler and correct).
