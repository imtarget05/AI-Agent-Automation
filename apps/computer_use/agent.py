"""
Computer Use Agent - Desktop automation and UI control
Supports both Anthropic Computer Use API and PyAutoGUI fallback
"""

import logging
import base64

from shared.config import get_settings
from shared.models import ComputerTask, ComputerResult
from shared.llm import get_llm_router

logger = logging.getLogger(__name__)
settings = get_settings()


class ComputerUseAgent:
    """Agent that controls computer desktop"""

    def __init__(self):
        self.llm = get_llm_router()
        self.use_anthropic = True  # Try Anthropic first

    async def initialize(self):
        """Initialize agent"""
        try:
            import anthropic

            self.anthropic_client = anthropic.AsyncAnthropic(
                api_key=settings.anthropic_api_key
            )
            logger.info("✅ Anthropic Computer Use initialized")
        except ImportError:
            logger.warning(
                "⚠️  Anthropic SDK not available, will use PyAutoGUI fallback"
            )
            self.use_anthropic = False

    async def execute(self, task: ComputerTask) -> ComputerResult:
        """
        Execute computer use task

        Args:
            task: ComputerTask with objective and optional app name

        Returns:
            ComputerResult with screenshot and output
        """
        logger.info(f"💻 [COMPUTER_USE] Starting task: {task.objective}")

        try:
            if self.use_anthropic:
                return await self._execute_anthropic(task)
            else:
                return await self._execute_pyautogui(task)

        except Exception as e:
            logger.error(f"❌ Computer use task failed: {e}")
            return ComputerResult(
                success=False,
                error=str(e),
            )

    async def _execute_anthropic(self, task: ComputerTask) -> ComputerResult:
        """
        Use Anthropic Computer Use API
        Requires: Claude 3.5 Sonnet
        """
        try:
            # Build prompt
            system_prompt = """You are an expert at using computers. You have the ability to:
- Take screenshots to see the current state of the screen
- Click on specific coordinates
- Type text
- Press keyboard shortcuts
- Use the mouse

When given a task, you should:
1. First take a screenshot to see what's on screen
2. Analyze the current state
3. Click on relevant UI elements
4. Type when needed
5. Press keys for navigation
6. Take screenshots to verify progress
7. Repeat until task is complete

Always be precise with coordinates and careful with dangerous actions."""

            user_message = f"Task: {task.objective}"
            if task.app_name:
                user_message += f"\nApp to use: {task.app_name}"
            if task.steps:
                user_message += "\nSteps provided:\n" + "\n".join(task.steps)

            # Call Anthropic with Computer Use tool
            response = await self.anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4096,
                system=system_prompt,
                tools=[
                    {
                        "type": "computer_20241022",
                        "name": "computer",
                        "display_width_px": 1920,
                        "display_height_px": 1080,
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": user_message,
                    }
                ],
                betas=["computer-use-2024-10-22"],
            )

            # Extract result
            final_screenshot = None
            output_text = ""

            for content_block in response.content:
                if content_block.type == "text":
                    output_text += content_block.text

            logger.info("✅ Anthropic Computer Use completed")

            return ComputerResult(
                success=True,
                output=output_text,
                screenshot=final_screenshot,
            )

        except Exception as e:
            logger.error(f"Anthropic Computer Use error: {e}")
            raise

    async def _execute_pyautogui(self, task: ComputerTask) -> ComputerResult:
        """
        Lightweight fallback using PyAutoGUI
        """
        try:
            import pyautogui
            import time
            from PIL import ImageGrab

            pyautogui.FAILSAFE = True  # Move to corner to abort

            logger.info("🖱️  Using PyAutoGUI fallback")

            # Take initial screenshot
            screenshot_1 = ImageGrab.grab()
            self._image_to_base64(screenshot_1)

            # Parse objective to execute steps
            steps = task.steps or self._parse_objective(task.objective)

            output_log = []

            for step in steps:
                logger.info(f"  Executing: {step}")

                # Simple command parser
                if step.startswith("click"):
                    # Example: "click 100 200"
                    parts = step.split()
                    if len(parts) >= 3:
                        x, y = int(parts[1]), int(parts[2])
                        pyautogui.click(x, y)
                        output_log.append(f"Clicked ({x}, {y})")
                        time.sleep(0.5)

                elif step.startswith("type"):
                    # Example: "type hello world"
                    text = " ".join(step.split()[1:])
                    pyautogui.typewrite(text)
                    output_log.append(f"Typed: {text}")

                elif step.startswith("hotkey"):
                    # Example: "hotkey ctrl+a"
                    keys = step.split()[1].split("+")
                    pyautogui.hotkey(*keys)
                    output_log.append(f"Pressed: {' + '.join(keys)}")
                    time.sleep(0.3)

                elif step.startswith("wait"):
                    # Example: "wait 2"
                    seconds = int(step.split()[1])
                    time.sleep(seconds)
                    output_log.append(f"Waited {seconds}s")

                else:
                    output_log.append(f"Unknown command: {step}")

            # Take final screenshot
            time.sleep(1)
            screenshot_2 = ImageGrab.grab()
            screenshot_2_b64 = self._image_to_base64(screenshot_2)

            logger.info("✅ PyAutoGUI execution completed")

            return ComputerResult(
                success=True,
                screenshot=screenshot_2_b64,
                output="\n".join(output_log),
            )

        except Exception as e:
            logger.error(f"PyAutoGUI error: {e}")
            raise

    def _parse_objective(self, objective: str) -> list[str]:
        """
        Simple parser to convert objective to steps
        This is very basic - in production use proper NLP
        """
        steps = []

        if "open" in objective.lower():
            if "chrome" in objective.lower():
                steps.append("hotkey win")
                steps.append("type chrome")
                steps.append("hotkey return")
            elif "vscode" in objective.lower() or "code" in objective.lower():
                steps.append("hotkey win")
                steps.append("type code")
                steps.append("hotkey return")

        return steps or ["wait 1"]  # Default: just wait

    def _image_to_base64(self, image) -> str:
        """Convert PIL Image to base64"""
        import io

        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode()


# ──---- Standalone Functions ----


async def run_computer_task(task: ComputerTask) -> ComputerResult:
    """Standalone function to run a computer use task"""
    agent = ComputerUseAgent()
    await agent.initialize()
    return await agent.execute(task)


# Common task templates


async def open_application(app_name: str) -> ComputerResult:
    """Open an application"""
    task = ComputerTask(
        objective=f"Open {app_name} application",
        app_name=app_name,
        steps=[
            "hotkey win",
            f"type {app_name.lower()}",
            "hotkey return",
            "wait 2",
        ],
    )
    return await run_computer_task(task)


async def take_screenshot() -> ComputerResult:
    """Just take a screenshot of current desktop"""
    task = ComputerTask(
        objective="Take a screenshot of current desktop",
    )
    return await run_computer_task(task)


async def click_position(x: int, y: int, description: str = "") -> ComputerResult:
    """Click at specific position"""
    task = ComputerTask(
        objective=f"Click at position ({x}, {y}) {description}",
        steps=[f"click {x} {y}"],
    )
    return await run_computer_task(task)
