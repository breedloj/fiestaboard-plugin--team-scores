from __future__ import annotations

import os
import sys
from pathlib import Path

root = os.environ.get("FIESTABOARD_ROOT")
if root:
    sys.path.insert(0, str(Path(root)))
