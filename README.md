# Matheutic

Config-driven generator for **printable math equation worksheets** — designed for **children** (skill-building) and **older adults** (maintenance/therapeutic practice).  
The focus is simple on purpose: lots of clean, solvable equations with sensible constraints, ready to print and use.

> **Note:** Matheutic is an educational/practice tool. It is **not** a medical device and does not provide medical advice or treatment.

---

## What it does

Matheutic generates sets of arithmetic equations (worksheets) such as:

- Addition / subtraction / multiplication / division
- Single-operation sets or mixed-operation sets
- Options to keep results in a certain range, avoid negatives (if desired), and ensure clean integer division (if desired)
- Optional **answer key** output

Everything is driven by **JSON presets** so you can generate consistent worksheets without editing code.

---

## Features

- **Preset-based workflow**: save and reuse worksheet configurations (`presets/*.json`)
- **Printable output**: produces clean pages suitable for classroom, home practice, or caregiver use
- **Constraint-friendly generation**: ranges, counts, operation selection, "no negatives", integer division, etc.
- **Reproducibility** (optional): use a seed to regenerate the exact same worksheet again

---

## Repository layout

```
.
├─ main.py                 # main generator entry point (CLI)
├─ presets/                # ready-to-use JSON presets
├─ sheets/                 # generated worksheets (gitignored)
├─ requirements.txt        # Python dependencies
└─ README.md
```

---

## Quick start

### 1) Requirements
- **Python 3.10+** recommended

### 2) Install
```bash
git clone https://github.com/Eager1Beaver/matheutic.git
cd matheutic

python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
# .venv\Scripts\activate

pip install -r requirements.txt
```

### 3) Generate a worksheet
```bash
python main.py --config presets/default.json --out output/worksheet.pdf
```

 `--help` will show all available options:
```bash
python main.py --help
```

---

## Presets

Presets are JSON files stored in `presets/`. They define *what* to generate (operations, ranges, number of problems, layout, answers).

Example preset:

```json
{
  "seed": 2026,

  "page": {
    "size": "A4",
    "orientation": "portrait",
    "margin_mm": { "top": 14, "right": 12, "bottom": 14, "left": 12 }
    },

  "typography": {
    "font_name": "Times-Roman",
    "font_size": 16,
    "line_gap": 6
    },

  "layout": {
    "mode": "table_by_columns",
    "rows_per_column": 26,
    "overflow_policy": "regenerate",
    "max_attempts_per_cell": 5000,
    "cell_padding_pt": 6
    },

  "answers": { "enabled": false },

  "generators": {
    "mixed_4": {
      "type": "mixed",
      "n_numbers": 4,
      "operators": ["+", "-", "*", "/"],
      "operator_weights": { "+": 4, "-": 4, "*": 2, "/": 1 },
      "operands_by_operator": {
        "+": { "min": 10, "max": 999 },
        "-": { "min": 10, "max": 999 },
        "*": { "min": 2, "max": 25 },
        "/": { "min": 2, "max": 25 }
        },
      "brackets": { "enabled": false },
      "rules": {
        "non_negative": true,
        "non_negative_intermediate": true,
        "require_integer_division": true
        },
      "limits": {
        "max_operand_digits": 3,
        "max_intermediate_digits": 4,
        "max_final_digits": 4
        }
      }
    },

  "columns": [
    { "generator": "mixed_4" },
    { "generator": "mixed_4" },
    { "generator": "mixed_4" }
  ]
}
```

---

## Design goals

- **Low friction**: one command → a ready-to-print worksheet
- **Clarity over cleverness**: clean arithmetic, obvious formatting, minimal distractions
- **Human-friendly**: works for kids, adults, and seniors; suitable for caregivers/teachers

---

## Roadmap

Matheutic is under development - more features ahead!

---

## License

See the `LICENSE` file in this repository.

---

## Acknowledgements

Built with the simple idea that a little daily arithmetic can be a gentle, effective mental workout.
