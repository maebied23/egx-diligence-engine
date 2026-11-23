"""Notes reader: the shapes of currency disclosure seen in LCSW and ARCC filings."""
import pytest

from efe import notes, tables
from efe.pagetext import Word


def line(top, *items):
    return [Word(t, x, x + 6 * len(t), top, top + 9) for t, x in items]


def figure(top, text, x):
    out = []
    for part in text.split():
        out += line(top, (part, x))
        x += 6 * len(part) + 3
    return out


@pytest.mark.parametrize("sentence", [
    "foreign currency assets and liabilities as of December 31, 2024 amounted to the equivalent of "
    "EGP 736 221 832 and EGP 370 548 104 respectively.",
    "foreign currency assets and liabilities as of 31 December 2024 amounted to the equivalent of "
    "736 221 832 EGP and 370 548 104 EGP"])
def test_sentence_gives_totals(sentence):
    got = {(i["field"], i["year"]): i["parts"][0]["value"] for i in notes.read_sentence(sentence)}
    assert got == {("fx_monetary_assets", 2024): 736221832, ("fx_monetary_liabilities", 2024): 370548104}


def test_assets_and_liabilities_by_currency_rows():
    """ARCC: 'Liabilities' and 'Assets' over two years each, one row per currency; rows are summed."""
    w = line(100, ("EGP", 100), ("Liabilities", 250), ("Assets", 430))
    w += line(112, ("December", 200), ("31,", 240), ("December", 290), ("31,", 330),
              ("December", 380), ("31,", 420), ("December", 470), ("31,", 510))
    w += line(124, ("2024", 240), ("2023", 330), ("2024", 420), ("2023", 510))
    w += line(140, ("Currency-USD", 100)) + figure(140, "343 480 899", 215) + figure(140, "754 424 405", 305) \
        + figure(140, "1 034 217 391", 385) + figure(140, "266 908 148", 485)
    w += line(152, ("Currency-EUR", 100)) + figure(152, "572 636 922", 215) + figure(152, "238 115", 320) \
        + figure(152, "57 875 417", 400) + figure(152, "2 440 736", 490)
    w += line(170, ("29.6.1", 60), ("Foreign", 90), ("currency", 130), ("sensitivity", 180))
    got = {(i["field"], i["year"]): sum(p["value"] for p in i["parts"])
           for i in notes.read_assets_liabilities(tables.group_lines(w))}
    assert got[("fx_monetary_liabilities", 2024)] == 343480899 + 572636922
    assert got[("fx_monetary_liabilities", 2023)] == 754424405 + 238115
    assert got[("fx_monetary_assets", 2024)] == 1034217391 + 57875417


def test_currency_columns_with_total():
    """LCSW: one column per currency and a total in EGP; rows for totals and bank facilities."""
    w = line(90, ("December", 92), ("31,", 138), ("2024", 153))
    w += line(100, ("Item", 24), ("USD", 188), ("EUR", 267), ("GBP", 345), ("Total", 519))
    w += line(115, ("Total", 24), ("Assets", 49), ("in", 78), ("Currency", 89)) + figure(115, "5 456 198", 182) \
        + figure(115, "6 614 998", 259) + figure(115, "1 523 636", 333) + figure(115, "736 221 832", 498)
    w += line(127, ("Bank", 24), ("Credit", 49), ("Facilities", 79)) + figure(127, "(1 389 617)", 174) \
        + figure(127, "(98 251 747)", 495)
    w += line(139, ("Total", 24), ("Liabilities", 49), ("in", 94), ("Currency", 105)) \
        + figure(139, "(1 697 254)", 174) + figure(139, "(370 548 104)", 495)
    got = {(i["field"], i["year"]): i["parts"][0]["value"] for i in notes.read_currency_columns(tables.group_lines(w))}
    assert got == {("fx_monetary_assets", 2024): 736221832, ("fx_borrowings", 2024): 98251747,
                   ("fx_monetary_liabilities", 2024): 370548104}


def test_confirm_accepts_a_figure_inside_noise():
    assert notes.figures_in("266 908 148 ЛЛAЛТОС") == {266908148.0}
    assert notes.figures_in("1 034 217391 67") != {1034217391.0}
