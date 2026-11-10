"""Jarvis voice assistant: layered package (core, adapters, commands, app).

See docs/ARCHITECTURE.md. All code lives here; ``src/`` keeps only three thin entry points for
external callers: ``jarvis_supervisor.py`` (the launcher), ``jarvis_voice.py`` (the listener
process) and ``fatsecret_call.py`` (the FatSecret CLI).
"""

__version__ = "3.20.0"
