"""Regenerate the command table in docs/COMMANDS.md from src/jarvis_registry.py."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import jarvis_registry as R  # noqa: E402

DOC = ROOT / "docs" / "COMMANDS.md"
BLOCK = re.compile(r"<!-- registry:start.*?<!-- registry:end -->", re.S)


def render(doc: str) -> str:
    block = R.render_markdown()
    if BLOCK.search(doc):
        return BLOCK.sub(lambda _: block, doc)
    return doc.rstrip("\n") + "\n\n## Все команды\n\n" + block + "\n"


if __name__ == "__main__":
    text = DOC.read_text(encoding="utf-8")
    DOC.write_text(render(text), encoding="utf-8", newline="\n")
    print("updated", DOC)
