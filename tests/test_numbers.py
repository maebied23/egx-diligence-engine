import pytest

from efe.numbers import is_note_ref, looks_numeric, parse_number


@pytest.mark.parametrize("token,expected", [
    ("6 644 687 614", 6644687614),
    ("6,644,687,614", 6644687614),
    (")4 709 357 845 (", -4709357845),     # reversed brackets from Arabic layout
    ("(25 388 998)", -25388998),
    ("-1,234", -1234),
    ("--", 0.0),
    ("- -", 0.0),
    ("-", 0.0),
    ("٦٬٦٤٤٬٦٨٧", 6644687),                 # Arabic-Indic digits and separator
    ("11.87", 11.87),
    ("12.5%", None),
    ("EGP", None),
    ("", None),
])
def test_parse_number(token, expected):
    assert parse_number(token) == expected


def test_looks_numeric():
    assert looks_numeric("644")
    assert looks_numeric("845(")
    assert looks_numeric(")")
    assert looks_numeric("--")
    assert not looks_numeric("sales")


def test_note_refs():
    for t in ("(5)", "(14-1)", "25-3", "(12),(29)", "5"):
        assert is_note_ref(t), t
    assert not is_note_ref("(2 543 351)")


def test_dot_misread_as_group_separator():
    assert parse_number("1 687 062.873") == 1687062873
    assert parse_number("3.02") == 3.02          # per-share figures keep their decimals
    assert parse_number("12.500") == 12.5        # no digit groups: a real decimal
