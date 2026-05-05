import asyncio
import uuid
import logging
import os
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent.parent
sys.path.append(str(project_root))

from backend.src.swarm.agents import AgentSwarm
from backend.src.blackboard.redis_blackboard import RedisBlackboard
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s'
)
logger = logging.getLogger("test_parallel")

async def test_parallel_execution():
    project_id = f"para-{uuid.uuid4().hex[:8]}"
    user_message = "build a library management system with books, authors, and rentals"
    
    logger.info(f"Starting True Parallel Swarm test for project: {project_id}")
    
    blackboard = RedisBlackboard()
    await blackboard.connect()
    
    swarm = AgentSwarm(llm_provider="minimax", blackboard=blackboard)
    
    # Task definitions for the agents
    task_definitions = {
        "rootdep": [user_message],
    }
    
    # Subscribe to events to monitor parallelism
    async def monitor_events():
        pubsub = blackboard._redis.pubsub()
        channel = f"project:{project_id}:events"
        await pubsub.subscribe(channel)
        
        active_agents = set()
        
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    import json
                    data = json.loads(message["data"])
                    agent = data.get("agent_name", "unknown")
                    etype = data.get("type", "unknown")
                    
                    if etype == "thinking" or etype == "tool_start":
                        if agent not in active_agents:
                            active_agents.add(agent)
                            if len(active_agents) > 1:
                                logger.info(f"PARALLELISM DETECTED! Active agents: {active_agents}")
                    
                    if etype == "complete":
                        if agent in active_agents:
                            active_agents.remove(agent)
                    
                    if agent == "packager" and etype == "complete":
                        break
        except Exception as e:
            logger.error(f"Monitor error: {e}")

    monitor_task = asyncio.create_task(monitor_events())
    
    try:
        await swarm.initialize(project_id, {"message": user_message})
        # This now triggers the new parallel logic
        await swarm.execute_parallel(task_definitions)
        
        logger.info("Parallel execution completed successfully!")
        
    except Exception as e:
        logger.error(f"Parallel Test Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await swarm.shutdown()
        monitor_task.cancel()

if __name__ == "__main__":
    asyncio.run(test_parallel_execution())
