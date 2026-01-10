from __future__ import annotations

import argparse
from pathlib import Path

from config.loader import load_config
from engine.workbook import generate_workbook
from export.pdf import export_worksheet_pdf


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog='mathsheet', description='Generate printable math worksheets from JSON configs.')
    p.add_argument('--config', '-c', required=True, help='Path to JSON config/preset file')
    p.add_argument('--out', '-o', default='worksheet.pdf', help='Output PDF path')
    p.add_argument('--answers-out', default=None, help='Answer key PDF output path (if answers.enabled)')
    return p.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)

    columns, answers = generate_workbook(cfg)

    title = (cfg.get('meta') or {}).get('title')

    out_path = Path(args.out)
    export_worksheet_pdf(cfg, columns, out_path, answers=None, title=title)

    if answers is not None:
        ans_cfg = cfg.get('answers') or {}
        if args.answers_out:
            ans_path = Path(args.answers_out)
        else:
            suffix = ans_cfg.get('suffix', '_answers')
            ans_path = out_path.with_name(out_path.stem + str(suffix) + out_path.suffix)

        export_worksheet_pdf(cfg, columns, ans_path, answers=answers, title=(str(title) + ' - Answers') if title else 'Answers')


if __name__ == '__main__':
    main()
