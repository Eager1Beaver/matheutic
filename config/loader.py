from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config.schema import normalize_config


def load_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    with p.open('r', encoding='utf-8') as f:
        cfg = json.load(f)

    return normalize_config(cfg)
