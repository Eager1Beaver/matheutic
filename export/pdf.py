from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import any, dict, list, optional

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from config.schema import mm_to_pt


def _pagesize(cfg: dict[str, any]) -> tuple[float, float]:
    w, h = A4
    if cfg.get('orientation') == 'landscape':
        w, h = landscape(A4)
    return float(w), float(h)


def _string_width(text: str, font_name: str, font_size: float) -> float:
    try:
        return pdfmetrics.stringWidth(text, font_name, font_size)
    except KeyError as error:
        raise ValueError(f'PDF font is not registered: {font_name}') from error


def export_worksheet_pdf(
        cfg: dict[str, any],
        columns: list[list[str]],
        out_path: str | Path,
        answers: optional[list[list[str]]] | None = None,
        title: optional[str] | None = None,
        ) -> None:
    """Export worksheet as a PDF.

    columns: list of columns, each a list of strings length = rows_per_column
    answers: if provided, parallel structure (same dimensions) to print as 'equation answer'
    """

    out_path = Path(out_path)
    if not columns or not columns[0] or any(len(col) != len(columns[0]) for col in columns):
        raise ValueError('Worksheet columns must be non-empty and have equal row counts')
    if answers is not None and (len(answers) != len(columns)
            or any(len(a) != len(c) for a, c in zip(answers, columns))):
        raise ValueError('Answer key dimensions must match the worksheet')
    page_cfg = cfg['page']
    layout = cfg['layout']
    typo = cfg['typography']

    page_w, page_h = _pagesize(page_cfg)
    m = page_cfg['margin_mm']
    margin_top = mm_to_pt(m['top'])
    margin_right = mm_to_pt(m['right'])
    margin_bottom = mm_to_pt(m['bottom'])
    margin_left = mm_to_pt(m['left'])

    font_name = typo['font_name']
    font_size = float(typo['font_size'])
    line_gap = float(typo.get('line_gap', 4))
    row_h = font_size + line_gap

    cell_pad = float(layout.get('cell_padding_pt', 6))

    n_cols = len(columns)
    rows_total = len(columns[0]) if columns else 0

    usable_w = page_w - margin_left - margin_right
    col_w = usable_w / max(n_cols, 1)

    usable_h = page_h - margin_top - margin_bottom

    header_h = 0.0
    if title:
        header_h = row_h * 1.5

    rows_per_page = int((usable_h - header_h) // row_h)
    if rows_per_page <= 0:
        raise ValueError('Not enough vertical space for even one row - check margins/font_size')

    n_pages = ceil(rows_total / rows_per_page) if rows_total else 1

    c = canvas.Canvas(str(out_path), pagesize=(page_w, page_h))

    def draw_page(page_index: int) -> None:
        c.setFont(font_name, font_size)

        if title:
            c.setFont(font_name, font_size + 2)
            c.drawString(margin_left, page_h - margin_top - (font_size + 2), title)
            c.setFont(font_name, font_size)

        start_row = page_index * rows_per_page
        end_row = min(rows_total, start_row + rows_per_page)

        y0 = page_h - margin_top - header_h - font_size

        for r in range(start_row, end_row):
            y = y0 - (r - start_row) * row_h
            for col_idx in range(n_cols):
                x = margin_left + col_idx * col_w + cell_pad
                text = columns[col_idx][r]
                if answers is not None:
                    text = f"{text}  {answers[col_idx][r]}"
                c.drawString(x, y, text)

        # footer: page number
        footer = f"{page_index + 1}/{n_pages}"
        c.setFont(font_name, 10)
        c.drawRightString(page_w - margin_right, margin_bottom * 0.6, footer)
        c.setFont(font_name, font_size)

    for p in range(n_pages):
        draw_page(p)
        c.showPage()

    c.save()


def measure_fits(text: str, cfg: dict[str, any], n_cols: int) -> bool:
    """Check whether a string fits a column in the current layout."""
    page_cfg = cfg['page']
    layout = cfg['layout']
    typo = cfg['typography']

    page_w, _ = _pagesize(page_cfg)
    m = page_cfg['margin_mm']
    margin_right = mm_to_pt(m['right'])
    margin_left = mm_to_pt(m['left'])

    cell_pad = float(layout.get('cell_padding_pt', 6))
    usable_w = page_w - margin_left - margin_right
    col_w = usable_w / max(n_cols, 1)

    font_name = typo['font_name']
    font_size = float(typo['font_size'])

    w = _string_width(text, font_name, font_size)
    return w <= (col_w - 2 * cell_pad)
