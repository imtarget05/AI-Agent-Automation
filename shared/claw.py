"""Optional claw-code CLI adapter used by the Gateway."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from shared.config import Settings, get_settings

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ClawWrapper:
    """Invoke a configured claw binary without assuming a specific provider."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        binary_path: Optional[str] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.binary_path = (
            binary_path
            or self.settings.claw_binary_path
            or self._find_binary()
        )

    @staticmethod
    def _find_binary() -> str:
        executable = "claw.exe" if os.name == "nt" else "claw"
        build_root = PROJECT_ROOT / "claw-code" / "rust" / "target"
        for build_type in ("release", "debug"):
            candidate = build_root / build_type / executable
            if candidate.exists():
                return str(candidate)
        return shutil.which("claw") or "claw"

    def execute(self, args: list[str], cwd: Optional[str] = None) -> str:
        """Execute claw and return stdout, surfacing CLI failures."""
        command = [self.binary_path, *args]
        working_directory = (
            cwd
            or self.settings.claw_working_directory
            or str(PROJECT_ROOT)
        )
        env = os.environ.copy()
        if self.settings.anthropic_api_key:
            env.setdefault("ANTHROPIC_API_KEY", self.settings.anthropic_api_key)
        if self.settings.openai_api_key:
            env.setdefault("OPENAI_API_KEY", self.settings.openai_api_key)
        env["CI"] = "true"

        logger.info("Executing claw command: %s", command[0])
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                env=env,
                cwd=working_directory,
                timeout=self.settings.claw_timeout_seconds,
            )
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr or exc.stdout or str(exc)
            raise RuntimeError(f"claw failed: {detail}") from exc
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"claw timed out after {self.settings.claw_timeout_seconds}s"
            ) from exc
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"claw binary not found: {self.binary_path}"
            ) from exc
        return result.stdout

    def prompt(self, message: str) -> str:
        """Run a non-interactive claw prompt."""
        return self.execute(["prompt", message])

    def doctor(self) -> str:
        """Run claw diagnostics."""
        return self.execute(["doctor"])
