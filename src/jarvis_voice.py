"""Jarvis voice listener entry point (started by jarvis_supervisor); the code lives in the jarvis package."""
import os

# Before numpy, onnxruntime and torch load: keep their thread pools small on a laptop.
for _k, _v in {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "1"}.items(): os.environ.setdefault(_k, _v)

from jarvis.app.main import run  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run())
