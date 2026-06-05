import asyncio
import logging
import sys
from apps.gateway.orchestrator import get_orchestrator
from shared.models import ModuleType

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    print("=== Claw Agent Integration Demo ===")
    
    orchestrator = get_orchestrator()
    session_id = "demo-session-claw"
    
    # Simple code-related task
    user_input = "Analyze the file 'tools/claw_wrapper.py' and tell me what it does"
    
    print(f"\nUser Request: {user_input}")
    print("Processing (this may take a moment as it invokes the orchestrator)...")
    
    try:
        # We allow only CLAW and RAG for this demo to ensure it picks the right agent
        # though the supervisor should be smart enough anyway.
        response = await orchestrator.execute(
            user_input=user_input,
            session_id=session_id,
            allowed_modules=[ModuleType.CLAW, ModuleType.RAG]
        )
        
        print("\n=== Orchestration Results ===")
        if response.get("error"):
            print(f"Error: {response['error']}")
        else:
            plan = response.get("plan")
            if plan:
                print(f"Plan ID: {plan.id}")
                for task in plan.tasks:
                    print(f"  - Task {task.id}: Agent={task.agent.value}, Instruction='{task.instruction}'")
            
            print("\n=== Final Answer ===")
            print(response.get("final_answer"))
            
            # Print individual task results if available
            results = response.get("results", {})
            if results:
                print("\n=== Detailed Task Results ===")
                for task_id, result in results.items():
                    print(f"Task {task_id} ({result.agent.value}): Status={result.status.value}")
                    # Only print a snippet of the output
                    output_str = str(result.output)
                    if len(output_str) > 200:
                        output_str = output_str[:200] + "..."
                    print(f"Output: {output_str}")

    except Exception as e:
        logger.error(f"Demo failed: {e}")
        print(f"\nAn error occurred during the demo: {e}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
