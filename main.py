from __future__ import annotations

import argparse

from config.loader import load_config
from config.schema import ConfigError
from engine.generation import GenerationError
from export.worksheet import write_workbook


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog='matheutic', description='Generate printable math worksheets from JSON configs.')
    p.add_argument('--config', '-c', required=True, help='Path to JSON config/preset file')
    p.add_argument('--out', '-o', default='worksheet.pdf', help='Output PDF path')
    p.add_argument('--answers-out', default=None, help='Answer key PDF output path (if answers.enabled)')
    return p.parse_args()


def main() -> None:
    args = parse_args()
    try:
        cfg = load_config(args.config)
        write_workbook(cfg, args.out, answers_out=args.answers_out)
    except (ConfigError, GenerationError, OSError, ValueError) as error:
        raise SystemExit(f'matheutic: {error}') from error


if __name__ == '__main__':
    main()
