"""Portable paths. Importing this module never creates directories or reads secrets."""
import os
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = PROJECT_ROOT / "src"
HOME = Path(os.path.expandvars(os.environ.get("JARVIS_HOME", str(PROJECT_ROOT / "runtime")))).expanduser().resolve()
PROJECTS_DIR = Path(os.path.expandvars(os.environ.get("JARVIS_PROJECTS", str(Path.home() / "Projects")))).expanduser()
