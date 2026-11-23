"""Read a statement page into rows: label, note reference, one value per period column.

Works on positioned words from either the text layer or OCR:
1. group words into lines by vertical position;
2. find the period columns from the header years (e.g. 2024, 2023);
3. join adjacent numeric tokens into numbers ("6 644 687 614") and assign each to the nearest column;
4. treat short bracketed tokens left of the value columns as note references;
5. attach label-only lines to a following value line with no label (wrapped labels),
   and remember section headers (e.g. 'Current Liabilities') for mapping.
Nothing is inferred: a cell that cannot be parsed keeps its raw text and value None.
"""
import re
from dataclasses import dataclass, field

from efe.numbers import is_note_ref, looks_numeric, parse_number
from efe.pagetext import Word

YEAR = re.compile(r"^(?:.*\D)?((?:19|20)\d{2})[,.]?$")  # '2024', and glued OCR tokens like '31December2021'
SECTION = re.compile(
    r"^(total )?(non[- ]?current assets|current assets|non[- ]?current liabilities|current liabilities|"
    r"equity( and liabilities)?|assets|liabilities|"
    r"cash flows? (from|used in)? ?(operating|investing|financing) activities|"
    r"(operating|investing|financing) activities)",
    re.I,
)


@dataclass
class Cell:
    column: int          # 0 = first period column (left), 1 = second, ...
    raw: str
    value: float | None


@dataclass
class Row:
    line_no: int
    label: str
    note_ref: str | None
    cells: list[Cell]
    line_text: str
    section: str | None = None
    top: float = 0.0
    words: list[Word] = field(default_factory=list, repr=False)


@dataclass
class Table:
    years: list[int]             # header year per column, left to right
    rows: list[Row]
    unit_hint: str | None        # header text mentioning units/currency, if found
    label_only_lines: int = 0    # lines with a label but no values (section headers, or missing numbers)


def group_lines(words: list[Word]) -> list[list[Word]]:
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.cy, w.x0)):
        h = max(w.bottom - w.top, 1.0)
        if lines and abs(sum(x.cy for x in lines[-1]) / len(lines[-1]) - w.cy) <= max(2.5, 0.45 * h):
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def find_columns(lines: list[list[Word]]) -> tuple[list[float], list[int], int]:
    """Column centres from the first line, in the first half of the lines, holding two or more years.
    Counted in lines, not page position, so pages whose content starts low still work."""
    for i, line in enumerate(lines[: max(10, len(lines) // 2)]):
        years = [(w, YEAR.match(w.text)) for w in line if YEAR.match(w.text) and len(w.text) <= 16]
        if len(years) >= 2:
            # glued tokens ('31December2021') put the year at the right end; use the year's own position
            centres = [w.x1 - (w.x1 - w.x0) * 2 / max(len(w.text), 1) for w, _ in years]
            return centres, [int(m.group(1)) for _, m in years], i
    return [], [], -1


def numeric_groups(words: list[Word]) -> list[list[Word]]:
    """Join neighbouring numeric tokens: digit groups of one number sit closer than one character width."""
    groups: list[list[Word]] = []
    for w in words:
        if groups:
            prev = groups[-1][-1]
            char_w = (prev.x1 - prev.x0) / max(len(prev.text), 1)
            if w.x0 - prev.x1 <= max(4.0, 1.1 * char_w):
                groups[-1].append(w)
                continue
        groups.append([w])
    return groups


def merge_value_lines(lines: list[list[Word]], value_left: float) -> list[list[Word]]:
    """OCR sometimes returns a row's numbers as a separate line, slightly offset vertically.
    Attach each numbers-only line to the nearest label-only neighbour (above or below) when their
    centres are within one line height."""
    def cy(line):
        return sum(w.cy for w in line) / len(line)

    def numbers_only(line):
        return all(looks_numeric(w.text) or is_note_ref(w.text) for w in line) and \
            any(w.x0 >= value_left and looks_numeric(w.text) for w in line)

    def label_only(line):
        return not any(w.x0 >= value_left and looks_numeric(w.text) for w in line)

    def marker(line):  # '(Less)', 'Add/(Less):', 'Deduct:' introduce lines; they carry no figures
        text = " ".join(w.text for w in line if w.x0 < value_left).lower()
        return bool(re.fullmatch(r"[\W_]*(less|add|deduct|add ?/ ?\(?(less|deduct)\)?|\(?less\)? ?/ ?add)[\W_]*", text))

    out = [list(line) for line in lines]
    merged = [False] * len(out)
    for i, line in enumerate(out):
        if merged[i] or not numbers_only(line) or any(w.x0 < value_left and not is_note_ref(w.text) for w in line):
            continue
        height = max(w.bottom - w.top for w in line)
        candidates = [j for j in (i - 1, i + 1) if 0 <= j < len(out) and not merged[j] and label_only(out[j])
                      and not marker(out[j])]
        if not candidates:
            continue
        j = min(candidates, key=lambda k: abs(cy(out[k]) - cy(line)))
        if abs(cy(out[j]) - cy(line)) < 0.9 * height:
            out[j] = sorted(out[j] + line, key=lambda w: w.x0)
            merged[i] = True
    return [line for line, m in zip(out, merged) if not m]


def read_table(words: list[Word]) -> Table | None:
    lines = group_lines(words)
    centres, years, header_idx = find_columns(lines)
    if not centres:
        return None
    half_gap = (min(b - a for a, b in zip(centres, centres[1:])) / 2) if len(centres) > 1 else 60
    first_col_left = centres[0] - half_gap * 1.6
    # The note column, from its header word; anything under it is a note reference, never a value.
    note_span = None
    for line in lines[max(0, header_idx - 2): header_idx + 3]:
        for w in line:
            if re.fullmatch(r"notes?|note\s*no\.?|إيضاح|ايضاح|رقم", w.text.strip(), re.I) and w.x1 < centres[0]:
                note_span = (w.x0 - 10, w.x1 + 10)
                break
        if note_span:
            break
    unit_hint = None
    for line in lines[: header_idx + 3]:
        text = " ".join(w.text for w in line)
        if re.search(r"thousand|million|'000|000s|EGP|L\.E|USD|جنيه|بالألف", text, re.I):
            unit_hint = (unit_hint + " | " if unit_hint else "") + text

    body = merge_value_lines(lines[header_idx + 1:], first_col_left)
    rows: list[Row] = []
    pending_label: list[str] = []
    pending_bottom = 0.0
    section = None
    label_only = 0
    for i, line in enumerate(body, start=header_idx + 1):
        # Split the line into label words, a note reference, and value words.
        label_words, note, value_words = [], None, []
        for w in line:
            in_note_col = note_span and note_span[0] <= (w.x0 + w.x1) / 2 <= note_span[1]
            if in_note_col and is_note_ref(w.text.replace(" ", "")):
                note = w.text if note is None else note + "," + w.text
            elif not note_span and is_note_ref(w.text) and (w.x0 + w.x1) / 2 < centres[0] - 0.75 * half_gap \
                    and len(w.text) <= 8 and label_words:
                note = w.text if note is None else note + "," + w.text
            elif w.x1 < first_col_left:
                if note is None and is_note_ref(w.text) and label_words and w.x0 > label_words[-1].x1 + 15:
                    note = w.text
                elif note is None:
                    label_words.append(w)
            elif looks_numeric(w.text):
                value_words.append(w)
            else:
                label_words.append(w)  # stray text in the value area is kept in the label, not dropped
        label = " ".join(w.text for w in label_words).strip()
        line_text = " ".join(w.text for w in line)

        cells = []
        for g in numeric_groups(value_words):
            raw = " ".join(w.text for w in g)
            cx = (g[0].x0 + g[-1].x1) / 2
            col = min(range(len(centres)), key=lambda k: abs(centres[k] - cx))
            cells.append(Cell(col, raw, parse_number(raw)))

        if not cells:
            if label and SECTION.fullmatch(label.strip()):
                section = label
            if label:
                pending_label.append(label)
                pending_bottom = max(w.bottom for w in line)
                label_only += 1
            continue
        height = max(w.bottom - w.top for w in line)
        close_above = pending_label and line[0].top - pending_bottom < 0.6 * height
        if not label and close_above:
            label = " ".join(pending_label)   # wrapped label printed just above its numbers
        elif label and close_above and pending_label[-1][-1:] in (",", "-"):
            label = pending_label[-1] + " " + label
        pending_label = []
        if label and SECTION.fullmatch(label.strip()) and not label.lower().startswith("total"):
            section = label
        rows.append(Row(i, label, note, cells, line_text, section, line[0].top, line))
    return Table(years, rows, unit_hint, label_only)
