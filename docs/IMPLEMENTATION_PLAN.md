# Implementation Plan: Chorus AI Agent Swarm

## Complete Task Breakdown

**Version:** 1.0
**Date:** 2026-05-05
**Status:** Draft — Pending Implementation

---

## Overview

This plan details the implementation of a true decentralized agent swarm that generates production-ready Spring Boot + Svelte projects from natural language descriptions.

**Phases:**
- Phase 1: Frontend Chat UI + Mocked API (THIS PHASE ONLY)
- Phase 2: Real LangGraph Swarm + MiniMax M2.7
- Phase 3: Sandbox + Code Generation
- Phase 4: Swarm Refinement + Polish

---

## Phase 1: Frontend Chat UI + Mocked API

**Goal:** Build Svelte 5 chat UI with mocked API endpoints simulating realistic swarm behavior.

**Timeline:** 2-3 weeks

### Task 1.1: Project Setup

#### 1.1.1: Initialize Svelte 5 + SvelteKit Project

**Steps:**
1. Create new SvelteKit project with TypeScript
   ```bash
   npm create svelte@latest frontend -- --template skeleton --types typescript
   cd frontend && npm install
   ```

2. Verify project structure:
   ```
   frontend/
   ├── src/
   │   ├── routes/
   │   │   └── +page.svelte
   │   └── app.html
   ├── package.json
   ├── svelte.config.js
   └── vite.config.ts
   ```

3. Install core dependencies:
   ```bash
   npm install @sveltejs/kit@latest svelte@latest vite@latest
   ```

#### 1.1.2: Configure Tailwind CSS 4 + shadcn-svelte

**Steps:**
1. Install Tailwind CSS 4:
   ```bash
   npm install -D tailwindcss@4 @tailwindcss/postcss postcss autoprefixer
   ```

2. Configure PostCSS:
   ```javascript
   // postcss.config.js
   export default {
     plugins: {
       '@tailwindcss/postcss': {}
     }
   }
   ```

3. Initialize shadcn-svelte:
   ```bash
   npx shadcn-svelte init
   ```

4. Add required components:
   ```bash
   npx shadcn-svelte add button card input badge scroll-area dialog toast
   ```

5. Configure Tailwind theme in `app.css`:
   ```css
   @import "tailwindcss";

   @theme {
     --color-primary: #3b82f6;
     --color-secondary: #10b981;
     --color-agent-rootdep: #8b5cf6;
     --color-agent-backend: #3b82f6;
     --color-agent-frontend: #10b981;
     --color-agent-devops: #f59e0b;
     --color-agent-packager: #ef4444;
   }
   ```

#### 1.1.3: Configure Lucide Icons

**Steps:**
1. Install Lucide Svelte:
   ```bash
   npm install lucide-svelte
   ```

2. Add icon imports to components as needed (Bot, User, Send, Download, Play, etc.)

#### 1.1.4: Set Up Svelte 5 Runes State

**Steps:**
1. Create store directory:
   ```
   mkdir -p src/lib/stores
   ```

2. Create `chat.svelte.ts`:
   ```typescript
   interface Message {
     id: string;
     role: 'user' | 'assistant';
     content: string;
     timestamp: Date;
   }

   class ChatStore {
     messages = $state<Message[]>([]);
     sessionId = $state<string | null>(null);
     isStreaming = $state(false);

     addMessage(msg: Omit<Message, 'id' | 'timestamp'>) {
       const message: Message = {
         ...msg,
         id: crypto.randomUUID(),
         timestamp: new Date()
       };
       this.messages.push(message);
     }

     clearChat() {
       this.messages = [];
       this.sessionId = null;
     }

     setStreaming(value: boolean) {
       this.isStreaming = value;
     }
   }

   export const chatStore = new ChatStore();
   ```

3. Create `agent.svelte.ts`:
   ```typescript
   interface Activity {
     id: string;
     agent: string;
     status: string;
     timestamp: Date;
     type: 'thinking' | 'action' | 'step' | 'tool';
   }

   class AgentStore {
     activities = $state<Activity[]>([]);
     currentStep = $state<string>('');
     progress = $state<number>(0);
     thinking = $state<string>('');
     isComplete = $state(false);

     addActivity(agent: string, status: string, type: Activity['type'] = 'action') {
       const activity: Activity = {
         id: crypto.randomUUID(),
         agent,
         status,
         timestamp: new Date(),
         type
       };
       this.activities.push(activity);
     }

     updateThinking(text: string) {
       this.thinking = text;
     }

     setProgress(step: string, value: number) {
       this.currentStep = step;
       this.progress = value;
     }

     setComplete(value: boolean) {
       this.isComplete = value;
     }

     clear() {
       this.activities = [];
       this.currentStep = '';
       this.progress = 0;
       this.thinking = '';
       this.isComplete = false;
     }
   }

   export const agentStore = new AgentStore();
   ```

#### 1.1.5: Set Up FastAPI Backend Skeleton

**Steps:**
1. Create backend directory structure:
   ```
   backend/
   ├── main.py
   ├── api/
   │   ├── __init__.py
   │   ├── router.py
   │   └── schemas.py
   ├── mock/
   │   ├── __init__.py
   │   ├── agent_simulator.py
   │   └── event_generator.py
   ├── storage/
   │   ├── __init__.py
   │   └── sqlite.py
   └── requirements.txt
   ```

2. Create `requirements.txt`:
   ```
   fastapi>=0.136.0
   uvicorn>=0.46.0
   pydantic>=2.13.0
   python-multipart>=0.0.9
   sse-starlette>=2.0.0
   aiosqlite>=0.20.0
   ```

3. Create `main.py`:
   ```python
   from fastapi import FastAPI
   from fastapi.middleware.cors import CORSMiddleware
   from src.backend.api.router import router

   app = FastAPI(title="DeepSeek Mock API", version="1.0.0")

   app.add_middleware(
       CORSMiddleware,
       allow_origins=["http://localhost:5173", "http://localhost:3000"],
       allow_credentials=True,
       allow_methods=["*"],
       allow_headers=["*"],
   )

   app.include_router(router)

   @app.get("/health")
   async def health():
       return {"status": "ok"}
   ```

---

### Task 1.2: Chat UI Components

#### 1.2.1: Main Chat Page (`+page.svelte`)

**Steps:**
1. Create layout with sidebar and main content
2. Implement message list (scrollable, auto-scroll to bottom)
3. Add input field with send button
4. Add session indicator
5. Integrate ActivityFeed and ThinkingDisplay

**Component Structure:**
```svelte
<script lang="ts">
  import ChatMessage from '$lib/components/ChatMessage.svelte';
  import ActivityFeed from '$lib/components/ActivityFeed.svelte';
  import ThinkingDisplay from '$lib/components/ThinkingDisplay.svelte';
  import ProgressBar from '$lib/components/ProgressBar.svelte';
  import { chatStore } from '$lib/stores/chat.svelte';
  import { agentStore } from '$lib/stores/agent.svelte';

  let input = $state('');

  async function handleSend() {
    if (!input.trim()) return;
    chatStore.addMessage({ role: 'user', content: input });
    input = '';
    chatStore.setStreaming(true);
    // Trigger SSE connection and mock API call
  }
</script>

<div class="flex h-screen">
  <!-- Activity Feed Sidebar -->
  <aside class="w-80 border-r bg-muted/20">
    <ActivityFeed />
  </aside>

  <!-- Main Chat Area -->
  <main class="flex-1 flex flex-col">
    <!-- Header with Progress -->
    <header class="border-b p-4">
      <ProgressBar />
    </header>

    <!-- Thinking Display -->
    {#if agentStore.thinking}
      <ThinkingDisplay />
    {/if}

    <!-- Message List -->
    <div class="flex-1 overflow-y-auto p-4 space-y-4">
      {#each chatStore.messages as message (message.id)}
        <ChatMessage {message} />
      {/each}
    </div>

    <!-- Input Area -->
    <footer class="border-t p-4">
      <div class="flex gap-2">
        <input
          bind:value={input}
          onkeydown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Describe your project..."
          class="flex-1 input"
        />
        <button onclick={handleSend} class="btn btn-primary">
          <Send class="h-4 w-4" />
        </button>
      </div>
    </footer>
  </main>
</div>
```

#### 1.2.2: ChatMessage Component

**Steps:**
1. Create `src/lib/components/ChatMessage.svelte`
2. Style user messages (right-aligned, primary color)
3. Style agent messages (left-aligned, secondary color)
4. Display timestamp
5. Render markdown for agent responses

**Props:**
```typescript
interface Props {
  message: {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: Date;
  };
}
```

**Styling:**
- User messages: right-aligned, blue background, white text
- Assistant messages: left-aligned, gray background, dark text
- Timestamps: small, muted text below message
- Code blocks: syntax highlighting (optional, use `react-markdown` pattern)

#### 1.2.3: ActivityFeed Component

**Steps:**
1. Create `src/lib/components/ActivityFeed.svelte`
2. Display scrolling list of activities
3. Color-code by agent type:
   - RootDepAgent: purple
   - BackendAgent: blue
   - FrontendAgent: green
   - DevOpsAgent: amber
   - PackagerAgent: red
4. Auto-scroll to latest activity
5. Show timestamp for each activity

**Svelte 5 implementation:**
```svelte
<script lang="ts">
  import { agentStore } from '$lib/stores/agent.svelte';
  import { Bot, User, Cog, Package, Server } from 'lucide-svelte';

  const agentIcons = {
    RootDepAgent: Bot,
    BackendAgent: Server,
    FrontendAgent: User,
    DevOpsAgent: Cog,
    PackagerAgent: Package
  };

  const agentColors = {
    RootDepAgent: 'text-purple-500',
    BackendAgent: 'text-blue-500',
    FrontendAgent: 'text-green-500',
    DevOpsAgent: 'text-amber-500',
    PackagerAgent: 'text-red-500'
  };
</script>

<div class="flex flex-col h-full">
  <div class="p-3 border-b font-semibold">Agent Activity</div>
  <div class="flex-1 overflow-y-auto p-2 space-y-2">
    {#each agentStore.activities as activity (activity.id)}
      {@const Icon = agentIcons[activity.agent] || Bot}
      <div class="flex items-start gap-2 text-sm p-2 rounded hover:bg-muted/50">
        <Icon class="h-4 w-4 mt-0.5 {agentColors[activity.agent]}" />
        <div class="flex-1 min-w-0">
          <div class="font-medium">{activity.agent}</div>
          <div class="text-muted-foreground truncate">{activity.status}</div>
        </div>
        <div class="text-xs text-muted-foreground">
          {activity.timestamp.toLocaleTimeString()}
        </div>
      </div>
    {/each}
  </div>
</div>
```

#### 1.2.4: ThinkingDisplay Component

**Steps:**
1. Create `src/lib/components/ThinkingDisplay.svelte`
2. Show agent reasoning in real-time with typing effect
3. Collapsible (expand/collapse button)
4. Monospace font for thinking text
5. Cursor blink animation during typing

**Implementation:**
```svelte
<script lang="ts">
  import { agentStore } from '$lib/stores/agent.svelte';
  import { ChevronDown, ChevronUp } from 'lucide-svelte';

  let expanded = $state(true);
</script>

{#if agentStore.thinking}
  <div class="border-b bg-muted/30">
    <button
      onclick={() => expanded = !expanded}
      class="w-full flex items-center justify-between p-2 text-sm font-medium"
    >
      <span>🤔 Agent Thinking</span>
      {#if expanded}
        <ChevronUp class="h-4 w-4" />
      {:else}
        <ChevronDown class="h-4 w-4" />
      {/if}
    </button>
    {#if expanded}
      <div class="p-3 font-mono text-sm whitespace-pre-wrap">
        {agentStore.thinking}<span class="animate-pulse">▋</span>
      </div>
    {/if}
  </div>
{/if}
```

#### 1.2.5: ProgressBar Component

**Steps:**
1. Create `src/lib/components/ProgressBar.svelte`
2. Show current step name
3. Show progress percentage
4. Show agent status badges (active agent highlighted)
5. Smooth transition animations

**Implementation:**
```svelte
<script lang="ts">
  import { agentStore } from '$lib/stores/agent.svelte';

  const steps = ['RootDep', 'Backend', 'Frontend', 'DevOps', 'Packager'];
  const stepIndex = $derived(
    steps.findIndex(s => agentStore.currentStep.startsWith(s))
  );
</script>

<div class="space-y-2">
  <div class="flex justify-between text-sm">
    <span class="font-medium">
      {agentStore.currentStep || 'Waiting...'}
    </span>
    <span class="text-muted-foreground">
      {agentStore.progress}%
    </span>
  </div>
  <div class="h-2 bg-muted rounded-full overflow-hidden">
    <div
      class="h-full bg-primary transition-all duration-500"
      style="width: {agentStore.progress}%"
    ></div>
  </div>
  <div class="flex justify-between text-xs">
    {#each steps as step, i}
      <span
        class={i <= stepIndex ? 'text-primary' : 'text-muted-foreground'}
      >
        {step}
      </span>
    {/each}
  </div>
</div>
```

#### 1.2.6: DownloadButtons Component

**Steps:**
1. Create `src/lib/components/DownloadButtons.svelte`
2. ZIP download button (disabled until complete)
3. Docker run button (disabled until complete)
4. Loading spinner during generation
5. Success/error state display

**Implementation:**
```svelte
<script lang="ts">
  import { agentStore } from '$lib/stores/agent.svelte';
  import { Download, Play, Loader2, CheckCircle, XCircle } from 'lucide-svelte';

  interface Props {
    zipUrl?: string;
    dockerImage?: string;
  }

  let { zipUrl, dockerImage }: Props = $props();
</script>

<div class="flex gap-3">
  <button
    disabled={!agentStore.isComplete || !zipUrl}
    class="btn btn-secondary flex items-center gap-2"
  >
    {#if !agentStore.isComplete}
      <Loader2 class="h-4 w-4 animate-spin" />
      Generating...
    {:else if zipUrl}
      <Download class="h-4 w-4" />
      Download ZIP
    {:else}
      <XCircle class="h-4 w-4" />
      Failed
    {/if}
  </button>

  <button
    disabled={!agentStore.isComplete || !dockerImage}
    class="btn btn-primary flex items-center gap-2"
  >
    {#if !agentStore.isComplete}
      <Loader2 class="h-4 w-4 animate-spin" />
      Building...
    {:else if dockerImage}
      <Play class="h-4 w-4" />
      Run Docker
    {:else}
      <XCircle class="h-4 w-4" />
      Failed
    {/if}
  </button>
</div>
```

---

### Task 1.3: SSE Client Implementation

#### 1.3.1: AG-UI Event Parser (`lib/sse.ts`)

**Steps:**
1. Create `src/lib/sse.ts`
2. Implement EventSource connection management
3. Implement event handlers for all 17+ AG-UI event types
4. Add reconnection logic with exponential backoff
5. Add error handling and display

**Implementation:**
```typescript
import { chatStore } from './stores/chat.svelte';
import { agentStore } from './stores/agent.svelte';

interface AGUIEvent {
  type: string;
  [key: string]: unknown;
}

type EventHandler = (data: Record<string, unknown>) => void;

class SSEClient {
  private eventSource: EventSource | null = null;
  private handlers: Map<string, EventHandler> = new Map();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;

  connect(sessionId: string) {
    this.eventSource = new EventSource(`/api/stream/${sessionId}`);

    this.eventSource.onopen = () => {
      this.reconnectAttempts = 0;
      console.log('SSE connected');
    };

    this.eventSource.onerror = (error) => {
      console.error('SSE error:', error);
      this.handleReconnect(sessionId);
    };

    // AG-UI Event Listeners
    this.eventSource.addEventListener('RunStarted', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleRunStarted(data);
    });

    this.eventSource.addEventListener('RunFinished', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleRunFinished(data);
    });

    this.eventSource.addEventListener('RunError', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleRunError(data);
    });

    this.eventSource.addEventListener('StepStarted', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleStepStarted(data);
    });

    this.eventSource.addEventListener('StepFinished', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleStepFinished(data);
    });

    this.eventSource.addEventListener('ActivitySnapshot', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleActivitySnapshot(data);
    });

    this.eventSource.addEventListener('ReasoningStart', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleReasoningStart(data);
    });

    this.eventSource.addEventListener('ReasoningMessageContent', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleReasoningContent(data);
    });

    this.eventSource.addEventListener('ReasoningEnd', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleReasoningEnd(data);
    });

    this.eventSource.addEventListener('ToolCallStart', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleToolCallStart(data);
    });

    this.eventSource.addEventListener('ToolCallArgs', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleToolCallArgs(data);
    });

    this.eventSource.addEventListener('ToolCallEnd', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleToolCallEnd(data);
    });

    this.eventSource.addEventListener('ToolCallResult', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleToolCallResult(data);
    });

    this.eventSource.addEventListener('TextMessageStart', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleTextMessageStart(data);
    });

    this.eventSource.addEventListener('TextMessageContent', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleTextMessageContent(data);
    });

    this.eventSource.addEventListener('TextMessageEnd', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleTextMessageEnd(data);
    });

    this.eventSource.addEventListener('StateSnapshot', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleStateSnapshot(data);
    });

    this.eventSource.addEventListener('StateDelta', (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      this.handleStateDelta(data);
    });
  }

  private handleRunStarted(data: Record<string, unknown>) {
    agentStore.setProgress('Initializing', 0);
  }

  private handleRunFinished(data: Record<string, unknown>) {
    agentStore.setComplete(true);
    chatStore.setStreaming(false);

    const outcome = data.outcome as { type: string };
    if (outcome?.type === 'success') {
      agentStore.addActivity('System', 'Project generation complete!', 'step');
    }
  }

  private handleRunError(data: Record<string, unknown>) {
    chatStore.setStreaming(false);
    agentStore.addActivity('System', `Error: ${data.message}`, 'action');
  }

  private handleStepStarted(data: Record<string, unknown>) {
    const stepName = data.stepName as string;
    agentStore.setProgress(stepName, agentStore.progress);
    agentStore.addActivity(stepName, 'Starting...', 'step');
  }

  private handleStepFinished(data: Record<string, unknown>) {
    // Update progress
  }

  private handleActivitySnapshot(data: Record<string, unknown>) {
    const content = data.content as { agent?: string; status?: string };
    if (content?.agent && content?.status) {
      agentStore.addActivity(content.agent, content.status, 'action');
    }
  }

  private handleReasoningStart(data: Record<string, unknown>) {
    agentStore.updateThinking('');
  }

  private handleReasoningContent(data: Record<string, unknown>) {
    const delta = data.delta as string;
    agentStore.updateThinking(agentStore.thinking + delta);
  }

  private handleReasoningEnd(_data: Record<string, unknown>) {
    // Optionally clear or keep thinking
  }

  private handleToolCallStart(data: Record<string, unknown>) {
    const toolName = data.toolCallName as string;
    const toolCallId = data.toolCallId as string;
    agentStore.addActivity('System', `Calling tool: ${toolName}`, 'tool');
  }

  private handleToolCallArgs(data: Record<string, unknown>) {
    // Optional: display tool arguments
  }

  private handleToolCallEnd(_data: Record<string, unknown>) {
    // Tool call complete
  }

  private handleToolCallResult(data: Record<string, unknown>) {
    const content = data.content as string;
    agentStore.addActivity('System', `Tool result: ${content}`, 'tool');
  }

  private handleTextMessageStart(data: Record<string, unknown>) {
    // Start of text message
  }

  private handleTextMessageContent(data: Record<string, unknown>) {
    const delta = data.delta as string;
    // Append to last assistant message or create new
    const messages = chatStore.messages;
    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.role === 'assistant') {
      lastMsg.content += delta;
    }
  }

  private handleTextMessageEnd(_data: Record<string, unknown>) {
    // Text message complete
  }

  private handleStateSnapshot(data: Record<string, unknown>) {
    // Update global state
  }

  private handleStateDelta(data: Record<string, unknown>) {
    // Apply state delta
  }

  private handleReconnect(sessionId: string) {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
      setTimeout(() => this.connect(sessionId), delay);
    }
  }

  disconnect() {
    this.eventSource?.close();
    this.eventSource = null;
  }
}

export const sseClient = new SSEClient();
```

#### 1.3.2: State Integration

**Steps:**
1. Map SSE events to Svelte stores
2. ActivityFeed updates on `ActivitySnapshot`
3. ThinkingDisplay updates on `ReasoningMessageContent`
4. Progress updates on `StepStarted`/`StepFinished`
5. ChatMessage updates on `TextMessageContent`

---

### Task 1.4: Mock Backend API

#### 1.4.1: Pydantic Schemas (`api/schemas.py`)

**Steps:**
1. Create request/response models
2. Create AG-UI event models

**Implementation:**
```python
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime
from enum import Enum

# Chat
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    session_id: str
    message: str

class Message(BaseModel):
    id: str
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime

class ChatHistoryResponse(BaseModel):
    session_id: str
    messages: list[Message]

# AG-UI Events
class RunStartedEvent(BaseModel):
    type: str = "RunStarted"
    runId: str
    threadId: str
    parentRunId: Optional[str] = None
    input: Optional[dict] = None

class RunFinishedEvent(BaseModel):
    type: str = "RunFinished"
    outcome: dict  # {"type": "success"} or {"type": "interrupt", "interrupts": [...]}
    result: Optional[dict] = None

class RunErrorEvent(BaseModel):
    type: str = "RunError"
    message: str
    code: Optional[str] = None

class StepStartedEvent(BaseModel):
    type: str = "StepStarted"
    stepName: str

class StepFinishedEvent(BaseModel):
    type: str = "StepFinished"
    stepName: str

class ActivitySnapshotEvent(BaseModel):
    type: str = "ActivitySnapshot"
    messageId: str
    activityType: str
    content: dict
    replace: Optional[bool] = True

class ReasoningStartEvent(BaseModel):
    type: str = "ReasoningStart"
    messageId: str

class ReasoningMessageContentEvent(BaseModel):
    type: str = "ReasoningMessageContent"
    messageId: str
    delta: str

class ReasoningEndEvent(BaseModel):
    type: str = "ReasoningEnd"
    messageId: str

class ToolCallStartEvent(BaseModel):
    type: str = "ToolCallStart"
    toolCallId: str
    toolCallName: str
    parentMessageId: Optional[str] = None

class ToolCallArgsEvent(BaseModel):
    type: str = "ToolCallArgs"
    toolCallId: str
    delta: str

class ToolCallEndEvent(BaseModel):
    type: str = "ToolCallEnd"
    toolCallId: str

class ToolCallResultEvent(BaseModel):
    type: str = "ToolCallResult"
    messageId: str
    toolCallId: str
    content: str
    role: Optional[str] = "tool"

class TextMessageStartEvent(BaseModel):
    type: str = "TextMessageStart"
    messageId: str
    role: str

class TextMessageContentEvent(BaseModel):
    type: str = "TextMessageContent"
    messageId: str
    delta: str

class TextMessageEndEvent(BaseModel):
    type: str = "TextMessageEnd"
    messageId: str
```

#### 1.4.2: Agent Simulator (`mock/agent_simulator.py`)

**Steps:**
1. Create realistic agent behavior simulation
2. Implement timing delays
3. Generate all AG-UI events
4. Support cancellation

**Implementation:**
```python
import asyncio
import random
from typing import AsyncGenerator

from .event_generator import EventGenerator

# Realistic timing configuration
TIMING = {
    'thinking': (0.5, 2.0),       # agent thinking delay
    'step': (2.0, 5.0),           # time per agent step
    'tool_call': (0.5, 1.5),      # time per tool invocation
    'stagger': (0.3, 0.8),        # delay between events
    'total_flow': 45,             # total simulation time (seconds)
}

AGENTS = [
    {
        'name': 'RootDepAgent',
        'color': 'purple',
        'statuses': [
            'Building shared schemas...',
            'Creating DTOs...',
            'Generating auth models...',
            'Building base classes...',
        ]
    },
    {
        'name': 'BackendAgent',
        'color': 'blue',
        'statuses': [
            'Writing REST controllers...',
            'Implementing services...',
            'Creating repositories...',
            'Configuring security...',
        ]
    },
    {
        'name': 'FrontendAgent',
        'color': 'green',
        'statuses': [
            'Creating Svelte components...',
            'Setting up routes...',
            'Building stores...',
            'Configuring Tailwind...',
        ]
    },
    {
        'name': 'DevOpsAgent',
        'color': 'amber',
        'statuses': [
            'Writing Dockerfile...',
            'Creating docker-compose...',
            'Building Docker image...',
        ]
    },
    {
        'name': 'PackagerAgent',
        'color': 'red',
        'statuses': [
            'Creating ZIP archive...',
            'Verifying contents...',
            'Preparing download...',
        ]
    }
]

class AgentSimulator:
    def __init__(self):
        self.event_gen = EventGenerator()
        self.is_cancelled = False

    async def generate(self, session_id: str) -> AsyncGenerator[dict, None]:
        """Generate realistic mock events for a project generation."""
        self.is_cancelled = False

        # RunStarted
        yield self.event_gen.run_started(run_id=session_id, thread_id=session_id)

        # Simulate thinking
        await self._sleep(*TIMING['thinking'])
        yield self.event_gen.reasoning_start(message_id='reason-001')

        thinking_chunks = [
            "Analyzing project requirements...",
            " Parsing request for tech stack...",
            " Determining project structure...",
            " Planning agent workflow...",
        ]
        for chunk in thinking_chunks:
            if self.is_cancelled:
                return
            yield self.event_gen.reasoning_content(message_id='reason-001', delta=chunk)
            await self._sleep(random.uniform(0.3, 0.7))

        yield self.event_gen.reasoning_end(message_id='reason-001')

        # Simulate each agent
        total_agents = len(AGENTS)
        for agent_idx, agent in enumerate(AGENTS):
            if self.is_cancelled:
                return

            agent_progress_start = (agent_idx / total_agents) * 100
            agent_progress_end = ((agent_idx + 1) / total_agents) * 100

            # Activity snapshot
            yield self.event_gen.activity_snapshot(
                message_id=f'act-{agent_idx}',
                activity_type='CODING',
                content={'agent': agent['name'], 'status': agent['statuses'][0]}
            )

            # Step started
            step_name = agent['name'].replace('Agent', '')
            yield self.event_gen.step_started(step_name=step_name)

            # Simulate agent work
            for status_idx, status in enumerate(agent['statuses']):
                if self.is_cancelled:
                    return

                # Update activity
                yield self.event_gen.activity_snapshot(
                    message_id=f'act-{agent_idx}-{status_idx}',
                    activity_type='CODING',
                    content={'agent': agent['name'], 'status': status}
                )

                # Tool call
                yield self.event_gen.tool_call_start(
                    tool_call_id=f'tc-{agent_idx}-{status_idx}',
                    tool_call_name=self._get_tool_name(agent['name'], status_idx)
                )

                # Simulate tool args
                await self._sleep(random.uniform(*TIMING['tool_call']))

                yield self.event_gen.tool_call_args(
                    tool_call_id=f'tc-{agent_idx}-{status_idx}',
                    delta=self._get_tool_args(agent['name'], status_idx)
                )

                yield self.event_gen.tool_call_end(
                    tool_call_id=f'tc-{agent_idx}-{status_idx}'
                )

                yield self.event_gen.tool_call_result(
                    message_id=f'msg-{agent_idx}-{status_idx}',
                    tool_call_id=f'tc-{agent_idx}-{status_idx}',
                    content=f'Created: {self._get_output_file(agent["name"], status_idx)}'
                )

                # Stagger delay
                await self._sleep(random.uniform(*TIMING['stagger']))

            # Step finished
            yield self.event_gen.step_finished(step_name=step_name)

 # Run finished
        yield self.event_gen.run_finished(
            outcome={'type': 'success'},
            result={
                'message': 'Project generated successfully!',
                'zip_url': f'/api/download/{session_id}.zip',
                'docker_image': f'deepseek-{session_id[:8]}:latest'
            }
        )

    def _get_tool_name(self, agent_name: str, idx: int) -> str:
        tools = {
            'RootDepAgent': ['write_schema', 'generate_dto', 'create_auth_model', 'build_base_class'],
            'BackendAgent': ['write_controller', 'write_service', 'write_repository', 'create_config'],
            'FrontendAgent': ['write_component', 'write_route', 'write_store', 'configure_tailwind'],
            'DevOpsAgent': ['write_dockerfile', 'write_docker_compose', 'build_image'],
            'PackagerAgent': ['create_zip', 'verify_archive', 'trigger_docker_run']
        }
        return tools.get(agent_name, ['unknown'])[idx]

    def _get_tool_args(self, agent_name: str, idx: int) -> str:
        return f'{{"file": "src/{agent_name.lower()}/file_{idx}.java"}}'

    def _get_output_file(self, agent_name: str, idx: int) -> str:
        files = {
            'RootDepAgent': ['schemas/001.sql', 'dto/UserDTO.java', 'auth/User.java', 'base/BaseEntity.java'],
            'BackendAgent': ['UserController.java', 'UserService.java', 'UserRepository.java', 'application.yml'],
            'FrontendAgent': ['UserList.svelte', '+page.svelte', 'userStore.ts', 'tailwind.config.js'],
            'DevOpsAgent': ['Dockerfile', 'docker-compose.yml', 'image-built'],
            'PackagerAgent': ['project.zip', 'verified', 'container-started']
        }
        return files.get(agent_name, ['unknown'])[idx]

    async def _sleep(self, min_t: float, max_t: float):
        await asyncio.sleep(random.uniform(min_t, max_t))

    def cancel(self):
        self.is_cancelled = True
```

#### 1.4.3: Event Generator (`mock/event_generator.py`)

**Steps:**
1. Create all AG-UI event generators
2. Ensure proper JSON serialization
3. Maintain event consistency

**Implementation:**
```python
import json
import uuid
from datetime import datetime
from typing import Optional, Any

class EventGenerator:
    def run_started(self, run_id: str, thread_id: str, parent_run_id: Optional[str] = None, input: Optional[dict] = None) -> dict:
        event = {
            'type': 'RunStarted',
            'runId': run_id,
            'threadId': thread_id,
            'timestamp': datetime.utcnow().isoformat()
        }
        if parent_run_id:
            event['parentRunId'] = parent_run_id
        if input:
            event['input'] = input
        return event

    def run_finished(self, outcome: dict, result: Optional[dict] = None) -> dict:
        event = {
            'type': 'RunFinished',
            'outcome': outcome,
            'timestamp': datetime.utcnow().isoformat()
        }
        if result:
            event['result'] = result
        return event

    def run_error(self, message: str, code: Optional[str] = None) -> dict:
        event = {
            'type': 'RunError',
            'message': message,
            'timestamp': datetime.utcnow().isoformat()
        }
        if code:
            event['code'] = code
        return event

    def step_started(self, step_name: str) -> dict:
        return {
            'type': 'StepStarted',
            'stepName': step_name,
            'timestamp': datetime.utcnow().isoformat()
        }

    def step_finished(self, step_name: str) -> dict:
        return {
            'type': 'StepFinished',
            'stepName': step_name,
            'timestamp': datetime.utcnow().isoformat()
        }

    def activity_snapshot(self, message_id: str, activity_type: str, content: dict, replace: bool = True) -> dict:
        return {
            'type': 'ActivitySnapshot',
            'messageId': message_id,
            'activityType': activity_type,
            'content': content,
            'replace': replace,
            'timestamp': datetime.utcnow().isoformat()
        }

    def activity_delta(self, message_id: str, activity_type: str, patch: list) -> dict:
        return {
            'type': 'ActivityDelta',
            'messageId': message_id,
            'activityType': activity_type,
            'patch': patch,
            'timestamp': datetime.utcnow().isoformat()
        }

    def reasoning_start(self, message_id: str) -> dict:
        return {
            'type': 'ReasoningStart',
            'messageId': message_id,
            'timestamp': datetime.utcnow().isoformat()
        }

    def reasoning_content(self, message_id: str, delta: str) -> dict:
        return {
            'type': 'ReasoningMessageContent',
            'messageId': message_id,
            'delta': delta,
            'timestamp': datetime.utcnow().isoformat()
        }

    def reasoning_end(self, message_id: str) -> dict:
        return {
            'type': 'ReasoningEnd',
            'messageId': message_id,
            'timestamp': datetime.utcnow().isoformat()
        }

    def tool_call_start(self, tool_call_id: str, tool_call_name: str, parent_message_id: Optional[str] = None) -> dict:
        event = {
            'type': 'ToolCallStart',
            'toolCallId': tool_call_id,
            'toolCallName': tool_call_name,
            'timestamp': datetime.utcnow().isoformat()
        }
        if parent_message_id:
            event['parentMessageId'] = parent_message_id
        return event

    def tool_call_args(self, tool_call_id: str, delta: str) -> dict:
        return {
            'type': 'ToolCallArgs',
            'toolCallId': tool_call_id,
            'delta': delta,
            'timestamp': datetime.utcnow().isoformat()
        }

    def tool_call_end(self, tool_call_id: str) -> dict:
        return {
            'type': 'ToolCallEnd',
            'toolCallId': tool_call_id,
            'timestamp': datetime.utcnow().isoformat()
        }

    def tool_call_result(self, message_id: str, tool_call_id: str, content: str, role: str = 'tool') -> dict:
        return {
            'type': 'ToolCallResult',
            'messageId': message_id,
            'toolCallId': tool_call_id,
            'content': content,
            'role': role,
            'timestamp': datetime.utcnow().isoformat()
        }

    def text_message_start(self, message_id: str, role: str) -> dict:
        return {
            'type': 'TextMessageStart',
            'messageId': message_id,
            'role': role,
            'timestamp': datetime.utcnow().isoformat()
        }

    def text_message_content(self, message_id: str, delta: str) -> dict:
        return {
            'type': 'TextMessageContent',
            'messageId': message_id,
            'delta': delta,
            'timestamp': datetime.utcnow().isoformat()
        }

    def text_message_end(self, message_id: str) -> dict:
        return {
            'type': 'TextMessageEnd',
            'messageId': message_id,
            'timestamp': datetime.utcnow().isoformat()
        }

    def state_snapshot(self, snapshot: dict) -> dict:
        return {
            'type': 'StateSnapshot',
            'snapshot': snapshot,
            'timestamp': datetime.utcnow().isoformat()
        }

    def state_delta(self, delta: list) -> dict:
        return {
            'type': 'StateDelta',
            'delta': delta,
            'timestamp': datetime.utcnow().isoformat()
        }
```

#### 1.4.4: Chat Persistence (`storage/sqlite.py`)

**Steps:**
1. Create SQLite database for chat history
2. Implement session CRUD
3. Implement message CRUD

**Implementation:**
```python
import aiosqlite
import json
from datetime import datetime
from typing import Optional
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / 'data' / 'chat.db'

async def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        ''')
        await db.commit()

async def create_session(session_id: str, user_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO sessions (id, user_id) VALUES (?, ?)',
            (session_id, user_id)
        )
        await db.commit()
        return {'id': session_id, 'user_id': user_id}

async def get_session(session_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id, user_id, created_at FROM sessions WHERE id = ?',
            (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {'id': row[0], 'user_id': row[1], 'created_at': row[2]}
            return None

async def add_message(session_id: str, role: str, content: str) -> dict:
    msg_id = str(datetime.utcnow().timestamp())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT INTO messages (id, session_id, role, content) VALUES (?, ?, ?, ?)',
            (msg_id, session_id, role, content)
        )
        await db.commit()
        return {'id': msg_id, 'session_id': session_id, 'role': role, 'content': content}

async def get_messages(session_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id, role, content, created_at FROM messages WHERE session_id = ? ORDER BY created_at',
            (session_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {'id': row[0], 'role': row[1], 'content': row[2], 'created_at': row[3]}
                for row in rows
            ]
```

#### 1.4.5: API Router (`api/router.py`)

**Steps:**
1. Create `/api/chat` POST endpoint
2. Create `/api/stream/{session_id}` SSE endpoint
3. Create `/api/history/{session_id}` GET endpoint
4. Create `/api/project/{session_id}` GET endpoint

**Implementation:**
```python
import asyncio
import json
import uuid
from datetime import datetime
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .schemas import ChatRequest, ChatResponse, ChatHistoryResponse
from ..mock.agent_simulator import AgentSimulator
from ..storage.sqlite import create_session, get_messages, add_message, get_session

router = APIRouter(prefix="/api")

# In-memory storage for active simulators
active_simulators: dict[str, AgentSimulator] = {}


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Accept a chat message and start project generation."""
    session_id = request.session_id or str(uuid.uuid4())

    # Ensure session exists
    if not await get_session(session_id):
        await create_session(session_id, user_id="anonymous")

    # Save user message
    await add_message(session_id, "user", request.message)

    # Start simulator
    simulator = AgentSimulator()
    active_simulators[session_id] = simulator

    return ChatResponse(session_id=session_id, message="Project generation started")


@router.get("/stream/{session_id}")
async def stream_events(session_id: str):
    """SSE stream of AG-UI events for a session."""

    simulator = active_simulators.get(session_id)
    if not simulator:
        # Try to get existing session
        session = await get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        simulator = active_simulators.get(session_id)
        if not simulator:
            return

        try:
            async for event in simulator.generate(session_id):
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0.01)  # Small delay to prevent flooding
        finally:
            if session_id in active_simulators:
                del active_simulators[session_id]

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/history/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_history(session_id: str):
    """Get chat history for a session."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await get_messages(session_id)
    return ChatHistoryResponse(session_id=session_id, messages=messages)


@router.get("/project/{session_id}")
async def get_project_status(session_id: str):
    """Get project status and download links."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        'session_id': session_id,
        'status': 'completed',  # In mock, always completed after flow
        'zip_url': f'/api/download/{session_id}.zip',
        'docker_image': f'deepseek-{session_id[:8]}:latest'
    }
```

---

### Task 1.5: Mock SSE Event Sequence

#### 1.5.1: Realistic Timing Configuration

**Steps:**
1. Define timing constants in `agent_simulator.py`
2. Ensure total flow is 30-60 seconds
3. Add randomness for realism

**Configuration:**
```python
TIMING = {
    'thinking': (0.5, 2.0),       # agent thinking delay
    'step': (2.0, 5.0),           # time per agent step
    'tool_call': (0.5, 1.5),      # time per tool invocation
    'stagger': (0.3, 0.8),        # delay between events
    'total_flow': 45,             # total simulation time (seconds)
}
```

#### 1.5.2: Event Sequence

```
t=0.0s   → RunStarted(runId="abc123", threadId="session-001")
t=0.5s   → ReasoningStart(messageId="reason-001")
t=0.8s   → ReasoningMessageContent(delta="Analyzing project request...")
t=1.2s   → ReasoningMessageContent(delta=" Parsing requirements...")
t=1.8s   → ReasoningEnd(messageId="reason-001")
t=2.2s   → ActivitySnapshot(activityType="CODING", content={agent:"RootDepAgent", status:"Building shared schemas..."})
t=2.5s   → StepStarted(stepName="RootDep")
t=3.0s   → ToolCallStart(toolCallId="tc-001", toolCallName="write_schema")
t=3.3s   → ToolCallArgs(delta="package com.example")
t=3.8s   → ToolCallEnd(toolCallId="tc-001")
t=4.0s   → ToolCallResult(content="Created: schemas/001.sql")
... (continues for all agents)
t=45s    → RunFinished(outcome={type:"success"}, result={zip_url:"/download/abc123.zip", docker_image:"project-abc123:latest"})
```

---

### Task 1.6: Styling & Polish

#### 1.6.1: Tailwind Theme Configuration

**Steps:**
1. Add custom colors for agent types
2. Configure dark mode
3. Add responsive breakpoints

**Configuration:**
```javascript
// tailwind.config.js
export default {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        agent: {
          rootdep: 'hsl(262, 83%, 58%)',
          backend: 'hsl(217, 91%, 60%)',
          frontend: 'hsl(160, 84%, 39%)',
          devops: 'hsl(38, 92%, 50%)',
          packager: 'hsl(0, 84%, 60%)',
        }
      }
    }
  }
}
```

#### 1.6.2: Animations

**CSS additions:**
```css
@keyframes typing {
  50% { opacity: 1; }
}

.animate-typing {
  animation: typing 1s infinite;
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.animate-fade-in {
  animation: fade-in 0.3s ease-out;
}
```

#### 1.6.3: Error States

**Steps:**
1. Handle SSE disconnection
2. Show retry button
3. Display error messages

---

## Phase 2: Real LangGraph Swarm + MiniMax M2.7

**Timeline:** 3-4 weeks

### Task 2.1: LangGraph Swarm Setup

#### 2.1.1: Install Dependencies

```bash
pip install langgraph>=0.2.70 langgraph-sdk langgraph-cli
pip install langchain-minimax  # when available, or use HTTP API
```

#### 2.1.2: Define Swarm State

```python
from typing import TypedDict, Annotated, List
from langgraph.graph import add_messages

class SwarmState(TypedDict):
    messages: Annotated[List, add_messages]
    project_spec: dict
    dependencies_ready: bool
    current_agent: str
    completed_tasks: List[str]
    pending_tasks: List[str]
    votes: dict
```

#### 2.1.3: Create Agent Definitions

Each agent defined as function with tool bindings.

#### 2.1.4: Implement Handoff Tools

```python
from langgraph.swarm import create_handoff_tool

handoff_to_backend = create_handoff_tool(
    agent_name="backend_agent",
    description="Handoff to Backend Agent for REST API generation"
)
```

### Task 2.2: Redis Blackboard Integration

- Task queue with priority
- Gossip pub/sub
- Agent heartbeat
- File locks
- Prompt caching

### Task 2.3: PostgreSQL + pgvector Setup

- PostgreSQL for persistent storage
- pgvector extension for embeddings
- Create RAG tables (documents, embeddings)
- Initialize schema

### Task 2.4: RAG Pipeline Implementation

#### 2.4.1: Document Ingestion
```python
async def ingest_documents(source: str, documents: list[dict]):
    """
    1. Chunk documents (512 tokens each)
    2. Generate embeddings via nomic-embed-text
    3. Store chunks in rag_documents
    4. Store embeddings in rag_embeddings
    """
```

#### 2.4.2: Retrieval
```python
async def retrieve_knowledge(query: str, top_k: int = 5) -> list[dict]:
    """
    1. Embed query
    2. Cosine similarity search in pgvector
    3. Retrieve relevant chunks
    4. Return with metadata
    """
```

#### 2.4.3: RAG-Enhanced Agent Context
```python
async def augment_agent_context(agent_type: str, request: str) -> str:
    """
    1. Retrieve relevant docs (Spring Boot patterns, Svelte patterns, etc.)
    2. Build context string with retrieved knowledge
    3. Inject into agent prompt
    """
```

#### 2.4.4: Knowledge Base Corpus (Initial Ingestion)

| Corpus | Source | Chunks |
|--------|--------|--------|
| Spring Boot 4 Docs | Official docs (HTML) | ~500 |
| Svelte 5 Docs | Official docs (MDN) | ~300 |
| Tailwind 4 Docs | Official docs | ~200 |
| Architecture Patterns | Curated best practices | ~100 |
| Security Best Practices | OWASP, JWT guides | ~100 |

### Task 2.5: Dynamic Agent Spawning

- Queue monitoring
- Agent pool management
- Backlog detection

### Task 2.6: Consensus Termination

- Voting mechanism
- Threshold-based completion

---

## Phase 2: Real LangGraph Swarm + MiniMax M2.7

**Status:** ✅ Completed (2026-05-05)

---

## Phase 3: Sandbox + Code Generation

**Status:** 🔄 In Progress

**Timeline:** 4-6 weeks

### Task 3.1: Seatbelt/bubblewrap Sandbox Setup

- Platform detection (Darwin = Seatbelt, Linux = bubblewrap)
- Workspace isolation per project
- Resource limits (CPU, RAM, pids via cgroups)
- Network proxy for allowlisted domains
- Project build & zip execution in sandbox

### Task 3.2: Code Generation Engine

- Project spec parser
- Spring Boot generator
- Svelte 5 generator

### Task 3.3: Dependency Management

- File locks
- Dependency graph

### Task 3.4: Build & Package

- Docker image build
- ZIP creation

---

## Phase 4: Swarm Refinement

**Timeline:** 2-3 weeks

### Task 4.1: Error Recovery

- Retry mechanism
- Fallback generation
- State checkpoints

### Task 4.2: Self-Healing

- Dead agent detection
- Task redistribution

### Task 4.3: Performance Optimization

- Prompt caching
- Token optimization

---

## Success Criteria

### Phase 1 Success Criteria
1. User can send a chat message and see real-time agent activity feed
2. All 17+ AG-UI event types are properly rendered in the UI
3. Mock backend simulates 30-60 second realistic project generation flow
4. Chat history is persisted and retrievable
5. Activity feed shows: agent thinking → agent action → step progress → tool calls → completion

### Overall Success Criteria
1. True swarm architecture (no supervisor bottleneck)
2. All agents powered by MiniMax M2.7
3. Full AG-UI protocol streaming to frontend
4. Redis + PostgreSQL blackboard pattern
5. RAG-enhanced code generation (pgvector knowledge base)
6. Projects generated from scratch (Spring Boot 4 + Svelte 5)
7. ZIP + Docker image output
8. Fully autonomous with consensus termination

---

**End of Implementation Plan**