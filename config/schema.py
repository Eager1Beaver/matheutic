from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any

MM_TO_PT = 72.0 / 25.4


def mm_to_pt(mm: float) -> float:
    return float(mm) * MM_TO_PT


DEFAULT_CONFIG: dict[str, Any] = {
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


MAX_EXERCISES = 10_000
MAX_ATTEMPTS = 10_000
MAX_NUMBERS = 16
MAX_OPERAND = 10**9
MAX_GENERATION_BUDGET = 10_000_000


class ConfigError(ValueError):
    pass


def _ensure(cond: bool, msg: str) -> None:
    if not cond:
        raise ConfigError(msg)


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out


def apply_defaults(cfg: dict[str, Any]) -> dict[str, Any]:
    _ensure(isinstance(cfg, dict), "Config must be a JSON object")
    return deep_merge(DEFAULT_CONFIG, cfg)


def _object(value: Any, path: str, allowed: set[str]) -> dict:
    _ensure(isinstance(value, dict), f'{path} must be an object')
    _ensure(not (set(value) - allowed), f'{path} contains unsupported keys: {set(value) - allowed}')
    return value


def _integer(value: Any, path: str, lo: int, hi: int) -> None:
    _ensure(type(value) is int and lo <= value <= hi, f'{path} must be an integer in [{lo}, {hi}]')


def _number(value: Any, path: str, minimum: float, *, positive: bool = False) -> None:
    try:
        finite = type(value) in (int, float) and isfinite(value)
    except OverflowError:
        finite = False
    _ensure(
        finite
        and (value > minimum if positive else value >= minimum),
        f'{path} must be a finite number {">" if positive else ">="} {minimum}'
        )


def _boolean(value: Any, path: str) -> None:
    _ensure(type(value) is bool, f'{path} must be a boolean')


def _operand_range(value: Any, path: str) -> None:
    obj = _object(value, path, {'min', 'max'})
    for key in ('min', 'max'):
        _integer(obj.get(key), f'{path}.{key}', -MAX_OPERAND, MAX_OPERAND)
    _ensure(obj['min'] <= obj['max'], f'{path}.min must be <= max')


def operand_range(gen_cfg: dict, op: str) -> tuple[int, int]:
    """Mixed ranges use the operator to the left; operand zero uses the first op.

    Ranges constrain input operands, not computed intermediate values.
    """
    obj = (gen_cfg.get('operands_by_operator') or {}).get(op)
    if obj is None:
        obj = gen_cfg.get('operands', {'min': 1, 'max': 100})
    return obj['min'], obj['max']


def validate_generator_config(g: dict, path: str = 'generator') -> None:
    common = {'type', 'n_numbers', 'operands', 'rules', 'limits'}
    _ensure(isinstance(g, dict), f'{path} must be an object')
    kind = g.get('type')
    _ensure(kind in ('single_op', 'mixed'), f'{path}.type must be single_op or mixed')
    _object(g, path, common | ({'op'} 
                               if kind == 'single_op' 
                               else {'operators', 'operator_weights', 'operands_by_operator', 'brackets'}))
    _integer(g.get('n_numbers'), f'{path}.n_numbers', 2, MAX_NUMBERS)
    if kind == 'single_op':
        _ensure(g.get('op') in ('+', '-', '*', '/'), f'{path}.op must be one of + - * /')
        _operand_range(g.get('operands'), f'{path}.operands')
        ops = [g['op']]
    else:
        ops = g.get('operators')
        _ensure(
            isinstance(ops, list) and ops and all(op in ('+', '-', '*', '/') for op in ops),
            f'{path}.operators must be a non-empty array of + - * /'
            )
        _ensure(len(set(ops)) == len(ops), f'{path}.operators must not contain duplicates')
        if 'operands' in g:
            _operand_range(g['operands'], f'{path}.operands')
        if 'operands_by_operator' in g:
            ranges = _object(g['operands_by_operator'], f'{path}.operands_by_operator', set(ops))
            for op, value in ranges.items():
                _operand_range(value, f'{path}.operands_by_operator.{op}')
        if 'operator_weights' in g:
            weights = _object(g['operator_weights'], f'{path}.operator_weights', set(ops))
            for op, weight in weights.items():
                _number(weight, f'{path}.operator_weights.{op}', 0)
            total = sum(weights.get(op, 1.0) for op in ops)
            _number(total, f'{path}.operator_weights total', 0, positive=True)
        if 'brackets' in g:
            brackets = _object(g['brackets'], f'{path}.brackets', {'enabled', 'probability'})
            _boolean(brackets.get('enabled', False), f'{path}.brackets.enabled')
            probability = brackets.get('probability', 0.35)
            _number(probability, f'{path}.brackets.probability', 0)
            _ensure(probability <= 1, f'{path}.brackets.probability must be <= 1')
    rules = _object(
        g.get('rules', {}), 
        f'{path}.rules',
        {'non_negative', 'non_negative_intermediate', 'require_integer_division'}
        )
    for key, value in rules.items():
        _boolean(value, f'{path}.rules.{key}')
    _ensure(rules.get('require_integer_division', True), 'only integer division is supported')
    limits = _object(
        g.get('limits', {}), 
        f'{path}.limits',
        {'max_operand_digits', 'max_intermediate_digits', 'max_final_digits',
         'max_intermediate_value', 'max_final_value'},
         )
    for key, value in limits.items():
        _integer(
            value, 
            f'{path}.limits.{key}', 
            1 if key.endswith('digits') else 0,
            144 if key.endswith('digits') else MAX_OPERAND**MAX_NUMBERS)
    if '/' in ops:
        lo, hi = operand_range(g, '/')
        _ensure(hi >= 1, f'{path}: division requires a positive divisor in the operand range')
        if kind == 'single_op' and lo > 0:
            _ensure(
                lo ** (g['n_numbers'] - 1) <= hi,
                f'{path}: operand range cannot contain a dividend for this division chain',
                )


def normalize_config(cfg: dict) -> dict:
    """Validate an in-memory preset, applying defaults without mutating its input."""
    normalized = apply_defaults(cfg)
    validate_config(normalized)
    return normalized


def validate_config(cfg: dict[str, Any]) -> None:
    _object(cfg, 'Config', set(DEFAULT_CONFIG))
    _ensure(type(cfg.get('schema_version')) is int and cfg['schema_version'] == 1,
            'schema_version must be 1')
    _ensure(cfg.get('seed') is None or type(cfg['seed']) is int, 'seed must be an integer or null')
    meta = _object(cfg.get('meta', {}), 'meta', {'title'})
    _ensure(isinstance(meta.get('title', ''), str), 'meta.title must be a string')
    _ensure(isinstance(cfg.get('generators'), dict), 'generators must be an object')
    _ensure(isinstance(cfg.get('columns'), list) and cfg['columns'], 'columns must be a non-empty array')

    layout = _object(cfg.get('layout'), 'layout', set(DEFAULT_CONFIG['layout']))
    _integer(layout.get('rows_per_column'), 'layout.rows_per_column', 1, MAX_EXERCISES)
    _integer(layout.get('max_attempts_per_cell'), 'layout.max_attempts_per_cell', 1, MAX_ATTEMPTS)
    _ensure(layout.get('mode') == 'table_by_columns', 'only table_by_columns layout is supported')
    _ensure(
        layout.get('overflow_policy') in ('regenerate', 'error'),
        'overflow_policy must be regenerate or error; shrink_font is not implemented',
        )
    _boolean(layout.get('show_column_headers'), 'layout.show_column_headers')
    _ensure(not layout['show_column_headers'], 'column headers are not implemented')
    _number(layout.get('cell_padding_pt'), 'layout.cell_padding_pt', 0)

    page = _object(cfg.get('page'), 'page', set(DEFAULT_CONFIG['page']))
    _ensure(page.get('size') == 'A4', 'page.size currently supports only A4')
    _ensure(page.get('orientation') in ('portrait', 'landscape'), 'invalid page.orientation')
    m = _object(page.get('margin_mm'), 'page.margin_mm', {'top', 'right', 'bottom', 'left'})
    for side in ('top', 'right', 'bottom', 'left'):
        _number(m.get(side), f'page.margin_mm.{side}', 0)
    width, height = (210, 297) if page['orientation'] == 'portrait' else (297, 210)
    _ensure(m['left'] + m['right'] < width and m['top'] + m['bottom'] < height,
            'page margins must leave usable page space')

    typography = _object(cfg.get('typography'), 'typography', set(DEFAULT_CONFIG['typography']))
    _ensure(
        isinstance(typography.get('font_name'), str) and typography['font_name'],
        'typography.font_name must be a non-empty string',
        )
    _number(typography.get('font_size'), 'typography.font_size', 0, positive=True)
    _number(typography.get('line_gap'), 'typography.line_gap', 0)

    answers = _object(cfg.get('answers'), 'answers', set(DEFAULT_CONFIG['answers']))
    for key in ('enabled', 'separate_pdf', 'show_work'):
        _boolean(answers.get(key), f'answers.{key}')
    _ensure(answers['separate_pdf'], 'inline answer keys are not implemented')
    _ensure(not answers['show_work'], 'PDF solution steps are not implemented')
    _ensure(
        isinstance(answers.get('suffix'), str) and answers['suffix']
        and not any(c in answers['suffix'] for c in ('/', '\\', '\0')),
        'answers.suffix must be a non-empty filename suffix',
        )

    _integer(len(cfg['columns']), 'column count', 1, 16)
    count = len(cfg['columns']) * layout['rows_per_column']
    _ensure(count <= MAX_EXERCISES, f'worksheet count must be <= {MAX_EXERCISES}')
    _ensure(
        count * layout['max_attempts_per_cell'] <= MAX_GENERATION_BUDGET,
        f'worksheet generation budget must be <= {MAX_GENERATION_BUDGET}',
        )
    gen_names = set(cfg['generators'])
    for i, col in enumerate(cfg['columns']):
        _object(col, f'columns[{i}]', {'generator'})
        name = col.get('generator')
        _ensure(
            isinstance(name, str) and name and name in gen_names,
            f'columns[{i}].generator must refer to a configured generator',
            )
    for name, g in cfg['generators'].items():
        _ensure(
            isinstance(name, str) 
            and name, 'generator names must be non-empty strings',
            )
        validate_generator_config(g, f'generators.{name}')
