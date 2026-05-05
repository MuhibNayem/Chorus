from typing import TypedDict, Annotated, List, Optional, Dict, Any
from langgraph.graph import add_messages
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres import PostgresSaver
from datetime import datetime


class AgentTask(TypedDict):
    task_id: str
    agent_name: str
    description: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime]
    result: Optional[Dict[str, Any]]


class Vote(TypedDict):
    agent_name: str
    vote: str
    reason: str
    timestamp: datetime


class SwarmState(TypedDict):
    messages: Annotated[List, add_messages]
    project_spec: Dict[str, Any]
    project_id: str
    dependencies_ready: bool
    current_agents: List[str]
    completed_tasks: List[str]
    pending_tasks: List[str]
    votes: Dict[str, Vote]
    task_results: Dict[str, Any]
    errors: List[Dict[str, Any]]
    is_complete: bool


class AgentContext(TypedDict):
    agent_name: str
    project_id: str
    capabilities: List[str]
    spawned_agents: List[str]
