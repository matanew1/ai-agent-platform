"""Make workspace members importable in local reload processes.

uv editable installs normally provide these paths. This explicit fallback keeps
the checked-out modular monolith runnable when macOS skips an editable .pth
entry in a recreated virtual environment.
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_settings_module_path() -> None:
    source = Path(__file__).resolve().parents[1] / "modules" / "settings" / "src"
    if source.is_dir() and str(source) not in sys.path:
        sys.path.insert(0, str(source))
