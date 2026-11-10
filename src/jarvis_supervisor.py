"""Supervisor entry point started by start_jarvis.vbs; the code lives in jarvis.app.supervisor."""
from jarvis.app.supervisor import entry, main, run, spawn_worker

__all__ = ["entry", "main", "run", "spawn_worker"]

if __name__ == "__main__":
    entry()
