from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict


MM_TO_PT = 72.0 / 25.4


def mm_to_pt(mm: float) -> float:
    return float(mm) * MM_TO_PT


DEFAULT_CONFIG: Dict[str, Any] = {
    "schema_version": 1,
    "meta": {"title": "Worksheet"},
    "seed": None,
    "page": {
        "size": "A4",
        "orientation": "portrait",
        "margin_mm": {"top": 12, "right": 12, "bottom": 12, "left": 12},
        },
    "typography": {
        "font_name": "Times-Roman",
        "font_size": 14,
        "line_gap": 4,
        },
    "layout": {
        "mode": "table_by_columns",
        "rows_per_column": 47,
        "show_column_headers": False,
        "overflow_policy": "regenerate",  # regenerate | shrink_font | error
        "max_attempts_per_cell": 2000,
        "cell_padding_pt": 6,
        },
    "generators": {},
    "columns": [],
    "answers": {
        "enabled": False,
        "separate_pdf": True,
        "suffix": "_answers",
        "show_work": False,
    },
}


class ConfigError(ValueError):
    pass


REQUIRED_TOP_LEVEL = ["generators", "columns"]


def _ensure(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_defaults(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return deep_merge(DEFAULT_CONFIG, cfg)


def validate_config(cfg: Dict[str, Any]) -> None:
    _ensure(isinstance(cfg, dict), "Config must be a JSON object")

    for k in REQUIRED_TOP_LEVEL:
        _ensure(k in cfg, f"Missing required key: '{k}'")

    _ensure(isinstance(cfg.get("generators"), dict), "'generators' must be an object")
    _ensure(isinstance(cfg.get("columns"), list) and cfg["columns"], "'columns' must be a non-empty array")

    layout = cfg.get("layout", {})
    _ensure(isinstance(layout.get("rows_per_column"), int) and layout["rows_per_column"] > 0,
            "layout.rows_per_column must be a positive integer")
    _ensure(isinstance(layout.get("max_attempts_per_cell"), int) and layout["max_attempts_per_cell"] > 0,
            "layout.max_attempts_per_cell must be a positive integer")

    page = cfg.get("page", {})
    _ensure(page.get("size") in ("A4",), "page.size currently supports only 'A4'")
    _ensure(page.get("orientation") in ("portrait", "landscape"), "page.orientation must be 'portrait' or 'landscape'")

    m = page.get("margin_mm", {})
    for side in ("top", "right", "bottom", "left"):
        _ensure(side in m and isinstance(m[side], (int, float)) and m[side] >= 0,
                f"page.margin_mm.{side} must be a non-negative number")

    typography = cfg.get("typography", {})
    _ensure(isinstance(typography.get("font_name"), str) and typography["font_name"], "typography.font_name must be a string")
    _ensure(isinstance(typography.get("font_size"), (int, float)) and typography["font_size"] > 0,
            "typography.font_size must be > 0")

    # Validate columns refer to generators
    gen_names = set(cfg["generators"].keys())
    for i, col in enumerate(cfg["columns"]):
        _ensure(isinstance(col, dict), f"columns[{i}] must be an object")
        g = col.get("generator")
        _ensure(isinstance(g, str) and g, f"columns[{i}].generator must be a string")
        _ensure(g in gen_names, f"columns[{i}].generator '{g}' not found in generators")

    # Validate generators minimally
    for name, g in cfg["generators"].items():
        _ensure(isinstance(g, dict), f"generators.{name} must be an object")
        _ensure(g.get("type") in ("single_op", "mixed"), f"generators.{name}.type must be 'single_op' or 'mixed'")
        _ensure(isinstance(g.get("n_numbers"), int) and g["n_numbers"] >= 2,
                f"generators.{name}.n_numbers must be an integer >= 2")

        if g["type"] == "single_op":
            _ensure(g.get("op") in ("+", "-", "*", "/"), f"generators.{name}.op must be one of + - * /")
            operands = g.get("operands")
            _ensure(isinstance(operands, dict), f"generators.{name}.operands must be an object")
            _ensure(isinstance(operands.get("min"), int) and isinstance(operands.get("max"), int),
                    f"generators.{name}.operands.min/max must be integers")
            _ensure(operands["min"] <= operands["max"], f"generators.{name}.operands.min must be <= max")

        if g["type"] == "mixed":
            ops = g.get("operators")
            _ensure(isinstance(ops, list) and ops and all(o in ("+", "-", "*", "/") for o in ops),
                    f"generators.{name}.operators must be a non-empty array of + - * /")

