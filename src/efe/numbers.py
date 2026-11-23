"""Parse numbers as printed in Egyptian financial statements.

Handles: space, comma or Arabic separators between thousands; negatives in brackets,
including reversed brackets ")4 709 357 845 (" produced by Arabic-to-English layout;
leading minus; nil markers ("-", "--", "—"); Arabic-Indic and Persian digits.
Returns None when the token is not a number, so callers never get a guessed value.
"""
import re

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NIL = {"-", "--", "---", "—", "–", "nil", "−"}
# Thousands separators seen in filings: space, comma, Arabic thousands separator, NBSP, thin space.
_SEP = re.compile(r"[ ,٬   ]")
_NUMBER = re.compile(r"^\d+(\.\d+)?$")


def normalise_digits(s: str) -> str:
    return s.translate(_DIGITS).replace("٫", ".")  # Arabic decimal separator


def parse_number(token: str) -> float | None:
    s = normalise_digits(token.strip())
    if not s:
        return None
    if s.lower() in _NIL or re.fullmatch(r"[-–—−](\s*[-–—−])+", s):  # "-", "--", "- -"
        return 0.0
    negative = "(" in s or ")" in s or s.startswith("-") or s.startswith("−")
    core = s.replace("(", "").replace(")", "").lstrip("-−").strip()
    # OCR sometimes reads the last group separator as a dot ("1 687 062.873"). A dot before exactly
    # three digits, after space-separated three-digit groups, is a separator: real decimals in
    # statements (per-share figures) are not printed in digit groups.
    if re.fullmatch(r"\d{1,3}( \d{3})+\.\d{3}", core):
        core = core.replace(".", " ")
    core = _SEP.sub("", core)
    if not _NUMBER.match(core):
        return None
    value = float(core)
    return -value if negative else value


def looks_numeric(token: str) -> bool:
    """True for tokens that can be part of a printed number (digit groups, brackets, nil marks)."""
    s = normalise_digits(token.strip())
    if s.lower() in _NIL:
        return True
    return bool(s) and bool(re.fullmatch(r"[\(\)]?-?[\d,.٬]+[\(\)]?|[\(\)]", s))


NOTE_REF = re.compile(r"^\(?\d{1,2}(\s*-\s*\d{1,2})?\)?(,\s*\(?\d{1,2}(-\d{1,2})?\)?)*$")


def is_note_ref(token: str) -> bool:
    """Note references like (5), (14-1), 25-3, (12),(29). Only meaningful inside the note column."""
    return bool(NOTE_REF.match(normalise_digits(token.strip())))
