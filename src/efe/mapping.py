"""Map printed labels to standard fields using data/label_map.csv (first matching row wins).

Unmatched labels are left unmapped for review; nothing is guessed. Add new variants to the CSV.
"""
import csv
import re
from dataclasses import dataclass
from functools import lru_cache

from efe import config

LABEL_MAP = config.DATA / "label_map.csv"


@dataclass(frozen=True)
class Rule:
    statement: str
    section: re.Pattern | None
    pattern: re.Pattern
    field: str


def normalise_label(label: str) -> str:
    s = label.lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"[•▪*:]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return s


@lru_cache(maxsize=1)
def rules() -> tuple[Rule, ...]:
    with open(LABEL_MAP, newline="", encoding="utf-8") as fh:
        return tuple(
            Rule(r["statement"], re.compile(r["section"], re.I) if r["section"] else None,
                 re.compile(r["pattern"], re.I), r["field"])
            for r in csv.DictReader(fh)
        )


def map_label(statement: str, label: str, section: str | None) -> str | None:
    norm = normalise_label(label)
    sec = normalise_label(section) if section else ""
    for rule in rules():
        if rule.statement != statement:
            continue
        if rule.section and not rule.section.search(sec):
            continue
        if rule.pattern.search(norm):
            return rule.field
    return None


VOCAB = set("""total assets asset current non liabilities liability equity and cash equivalents net profit loss
income revenue revenues sales cost costs gross operating operations activities investing financing expenses
administrative general selling distribution marketing tax taxes before after for the year period inventories
inventory receivables receivable payables payable trade other property plant equipment borrowings loans provisions
reserves retained earnings capital paid issued interests controlling deferred lease leases credit facilities
intangible projects construction under progress finance depreciation amortization amortisation dividends
comprehensive attributable owners parent company shareholders change increase decrease beginning end notes
advances customers from used generated provided flows flow balances debtors creditors bank banks investments
investment joint venture associates portion long short term related parties due expected losses impairment
share premium legal treasury shares translation differences foreign currency exchange""".split())


def ocr_correct(label: str) -> str:
    """Correct OCR misreadings word by word against a fixed vocabulary of statement words
    ('Jotal non-current assers' -> 'total non-current assets'). Short words and numbers are left alone."""
    import difflib
    out = []
    for token in re.split(r"(\W+)", normalise_label(label)):
        if len(token) >= 4 and token.isalpha() and token not in VOCAB:
            match = difflib.get_close_matches(token, VOCAB, n=1, cutoff=0.75)
            out.append(match[0] if match else token)
        else:
            out.append(token)
    return "".join(out)


def map_label_ocr(statement: str, label: str, section: str | None) -> tuple[str | None, str | None]:
    """map_label, then an OCR-corrected retry. Returns (field, corrected label if the correction was needed)."""
    field = map_label(statement, label, section)
    if field or not label:
        return field, None
    corrected = ocr_correct(label)
    sec = ocr_correct(section) if section else None
    field = map_label(statement, corrected, sec)
    return (field, corrected) if field else (None, None)


# Sign convention for value_normalised: costs negative, balance-sheet amounts positive,
# everything else as reported (profits, cash flows and changes can be either sign).
COST_FIELDS = {"cost_of_sales", "selling_expenses", "admin_expenses", "other_operating_expenses",
               "impairment_receivables", "finance_costs", "income_tax", "capex", "capex_intangibles",
               "dividends_paid", "interest_paid", "income_tax_paid", "employee_profit_share_paid"}
SIGNED_BS_FIELDS = {"retained_earnings", "total_equity", "equity_parent", "non_controlling_interest_equity"}


def normalise_sign(statement: str, field: str, value: float) -> float:
    if field in COST_FIELDS:
        return -abs(value)
    if statement == "balance_sheet" and field not in SIGNED_BS_FIELDS:
        return abs(value)
    return value
