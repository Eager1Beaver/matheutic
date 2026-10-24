# Worksheet development guide

This guide covers installation, configuration, and development for printable worksheet generation.

## Install and generate a worksheet

Requires Python **3.12 or later**. Run these commands from the repository root:

```bash
uv sync --locked
uv run --locked matheutic --config presets/kids_easy.json --out sheets/worksheet.pdf
uv run --locked matheutic --help
```

Output directories are created automatically. Worksheet generation runs locally without API credentials.

You can also install the package with pip:

```bash
python -m pip install -e .
matheutic --config presets/kids_easy.json --out sheets/worksheet.pdf
```

The Python entry point accepts the same arguments:

```bash
uv run --locked python main.py --config presets/elderly_gentle.json --out sheets/gentle.pdf
```

## CLI options

| Option | Purpose |
| --- | --- |
| `--config`, `-c` | Required path to a JSON preset. |
| `--out`, `-o` | Worksheet PDF path; defaults to `worksheet.pdf`. |
| `--answers-out` | Answer-key PDF path when `answers.enabled` is true. |
| `--help` | Shows command usage. |

Answer keys are separate PDFs. With `answers.enabled` set to `true`, the default answer-key name adds `_answers` before the worksheet extension. Set `answers.suffix` to change that suffix, or pass an explicit path:

```bash
uv run --locked matheutic --config my-preset.json \
  --out sheets/practice.pdf --answers-out sheets/solutions.pdf
```

The worksheet and answer key must have different paths.

## Presets

The [presets directory](../presets/) contains ready-to-use JSON configurations:

| Preset | Exercises and layout |
| --- | --- |
| [kids_easy.json](../presets/kids_easy.json) | Four columns of addition and subtraction, with 32 exercises per column. |
| [elderly_gentle.json](../presets/elderly_gentle.json) | Three columns of mixed arithmetic, with 28 exercises per column. |
| [test_style.json](../presets/test_style.json) | A configurable worksheet style example. |

Copy a preset to customise it. A minimal configuration for 40 subtraction exercises with an answer key is:

```json
{
  "schema_version": 1,
  "seed": 42,
  "layout": {"rows_per_column": 40},
  "answers": {"enabled": true},
  "generators": {
    "subtraction": {
      "type": "single_op",
      "op": "-",
      "n_numbers": 2,
      "operands": {"min": 1, "max": 99},
      "rules": {
        "non_negative": true,
        "non_negative_intermediate": true
      }
    }
  },
  "columns": [{"generator": "subtraction"}]
}
```

Schema version 1 is required. Omitted settings receive defaults; invalid values and unknown keys are rejected. Each entry in `columns` refers to a named generator. The total exercise count is the number of columns multiplied by `layout.rows_per_column`.

### Arithmetic configuration

Generators support addition (`+`), subtraction (`-`), multiplication (`*`), and exact integer division (`/`). Expressions follow normal operator precedence and may contain one pair of brackets.

- `single_op` uses one `op` throughout an expression.
- `mixed` selects from `operators`, with optional `operator_weights`.
- `n_numbers` sets the number of input operands.
- `operands.min` and `operands.max` bound every input operand, including a division's dividend.
- Mixed generators can use `operands_by_operator`. The first operand uses the first operator's range; each subsequent operand uses the operator immediately to its left.
- Mixed generators can enable brackets with `brackets.enabled` and set their frequency with `brackets.probability`.

Division must be exact at every division step. Setting `rules.require_integer_division` to `false` is rejected.

`rules.non_negative` requires a nonnegative final answer. `rules.non_negative_intermediate` applies that requirement to all calculation steps and defaults to the value of `non_negative`.

Use `limits` to constrain input and result sizes:

| Setting | Constraint |
| --- | --- |
| `max_operand_digits` | Maximum digits in each input operand. |
| `max_intermediate_digits` | Maximum digits in each calculation result, including the final result. |
| `max_final_digits` | Maximum digits in the final answer. |
| `max_intermediate_value` | Maximum absolute value of each calculation result, including the final result. |
| `max_final_value` | Maximum absolute value of the final answer. |

### Page layout

Worksheets use A4 paper in portrait or landscape orientation. The main presentation settings are:

| Setting | Purpose |
| --- | --- |
| `meta.title` | Title printed above the exercises. |
| `page.orientation` | `portrait` or `landscape`. |
| `page.margin_mm` | Top, right, bottom, and left margins in millimetres. |
| `typography.font_name` | A font registered with ReportLab; defaults to `Times-Roman`. |
| `typography.font_size` | Font size in points. |
| `typography.line_gap` | Additional vertical spacing between rows, in points. |
| `layout.rows_per_column` | Exercises generated for each column. |
| `layout.cell_padding_pt` | Horizontal padding inside each column, in points. |
| `layout.overflow_policy` | `regenerate` retries exercises that are too wide; `error` stops generation. |
| `layout.max_attempts_per_cell` | Maximum candidate attempts for each exercise. |

Rows continue onto additional pages when necessary. When answer keys are enabled, width checks include the answer text.

## Generate worksheets from Python

Load a preset and write its worksheet and optional answer key:

```python
from config.loader import load_config
from export.worksheet import write_workbook

config = load_config("presets/kids_easy.json")
config["answers"]["enabled"] = True
files = write_workbook(config, "sheets/practice.pdf")
print(files.worksheet)
print(files.answers)
```

For an in-memory configuration, `config.schema.normalize_config()` applies defaults and validates it without changing the input dictionary.

To generate arithmetic exercises before arranging them for printing:

```python
from engine.generation import generate_exercises

generator = {
    "type": "single_op",
    "op": "-",
    "n_numbers": 2,
    "operands": {"min": 1, "max": 99},
    "rules": {"non_negative": True},
}
exercises = generate_exercises(generator, count=40, seed=2026)
first = exercises[0]
print(first.expression, first.answer, first.steps)
```

This API returns immutable exercise records containing operands, operators, optional brackets, the computed answer, and solution steps. It does not import ReportLab. For batches sharing a random stream, use `generate_exercise(rng, generator)` with a `random.Random` instance.

## Reproducibility and generation limits

A fixed seed and unchanged generator configuration reproduce the same structured exercises within an engine version. Record the version, seed, and configuration when repeatability matters.

PDF generation also depends on fonts, margins, column count, and whether answers must fit: the `regenerate` overflow policy can select different exercises when those settings change.

Generation is bounded to:

- 10,000 exercises per request.
- 16 columns per worksheet.
- 16 operands per expression.
- Input operand magnitudes of at most 1,000,000,000.
- 10,000 candidate attempts per exercise.
- A total candidate budget of 10,000,000, calculated as the exercise count multiplied by the attempt limit.

Unsatisfiable constraints raise `GenerationError` with a reason and attempt count. If an exercise cannot fit, reduce the font size, column count, or horizontal margins. If arithmetic generation fails, check that operand ranges and result limits allow valid expressions before increasing the attempt limit.

## Verify worksheet changes

Run the worksheet and arithmetic tests from the repository root:

```bash
uv run --locked pytest -q tests/test_arithmetic.py tests/test_config.py \
  tests/test_generation.py tests/test_worksheet.py
```

These tests cover exact arithmetic, preset validation, bounded generation, reproducibility, PDF export, answer keys, and CLI behaviour. Include regression coverage when changing arithmetic rules, configuration semantics, or PDF output.

See [LICENSE](../LICENSE) for the project licence.
