"""Regression guard: extraction must not get worse on the answer-key filings.

Runs on the local database (filings are not in git), so it is skipped on a fresh checkout. Raise
MIN_ACCURACY when the engine improves; never lower it to make a change pass.
"""
import pytest

from efe import config, db, evaluate

MIN_ACCURACY = 0.95       # correct / values extracted, on the filled answer-key rows
MAX_WRONG_UNFLAGGED = 0   # an error nothing flagged is the one that reaches a memo


@pytest.mark.skipif(not config.DB_PATH.exists(), reason="no local database")
def test_answer_key_accuracy():
    with db.connect() as conn:
        r = evaluate.run(conn)
    if not r["filled_key_rows"]:
        pytest.skip("answer key empty")
    assert r["results"].get("wrong_unflagged", 0) <= MAX_WRONG_UNFLAGGED, r["errors"]
    assert r["accuracy_on_extracted"] >= MIN_ACCURACY, r["errors"]
