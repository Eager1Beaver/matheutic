from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from config.schema import apply_defaults, validate_config


def load_config(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    with p.open('r', encoding='utf-8') as f:
        cfg = json.load(f)

    cfg = apply_defaults(cfg)
    validate_config(cfg)
    return cfg
