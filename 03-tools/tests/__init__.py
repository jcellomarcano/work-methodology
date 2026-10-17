"""Import bootstrap for the suite: puts the tools repo root on
sys.path before any test imports `lib.*`, independent of what
directory `python3 -m unittest discover tests` is invoked from, and turns
persistent memory off so a receipt or handoff test never reaches the real
engram database."""
import os
import sys
from pathlib import Path

os.environ.setdefault("METODO_MEMORY", "off")

TOOLS_ROOT = Path(__file__).resolve().parent.parent
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
