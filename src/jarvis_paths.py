"""Portable paths. Importing this module never creates directories or reads secrets.

Every location can be moved with an environment variable, so an existing installation
(logs, caches, secrets) keeps working while the code runs from a git checkout.
"""
import os
import re
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "src"


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(os.path.expandvars(value)).expanduser() if value else default


HOME = _env_path("JARVIS_HOME", PROJECT_ROOT / "runtime").resolve()
PROJECTS_DIR = _env_path("JARVIS_PROJECTS", Path.home() / "Projects")
DEFAULT_CREDENTIAL_PREFIX = "JarvisVoiceAssistant."
_PREFIX_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}\.")


def log_dir() -> Path:
    """Listener and supervisor logs (JARVIS_LOG_DIR, default HOME/logs)."""
    return _env_path("JARVIS_LOG_DIR", HOME / "logs")


def screenshots_dir(base: Optional[Path] = None) -> Path:
    """Screenshots (JARVIS_SCREENSHOTS, default <base or HOME>/screenshots)."""
    return _env_path("JARVIS_SCREENSHOTS", Path(base or HOME) / "screenshots")


def credential_prefix() -> str:
    """Windows Credential Manager service prefix (JARVIS_CREDENTIAL_PREFIX)."""
    value = os.environ.get("JARVIS_CREDENTIAL_PREFIX", "").strip()
    return value if _PREFIX_RE.fullmatch(value) else DEFAULT_CREDENTIAL_PREFIX
