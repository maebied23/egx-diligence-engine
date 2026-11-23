-- Schema follows docs/05_schema.md. Raw source records are never updated in place;
-- corrections are new rows that point back to what they correct.

CREATE TABLE IF NOT EXISTS documents (
    id                    INTEGER PRIMARY KEY,
    ticker                TEXT NOT NULL,
    fiscal_year           INTEGER NOT NULL,
    period                TEXT NOT NULL,        -- Q1 / H1 / 9M / FY
    period_end            TEXT NOT NULL,        -- ISO date
    scope                 TEXT NOT NULL,        -- consolidated / separate
    framework             TEXT,                 -- EAS / IFRS / '' if not yet known
    language              TEXT,                 -- en / ar
    doc_type              TEXT NOT NULL,        -- financial_statements / annual_report / earnings_release / ...
    source                TEXT NOT NULL,        -- company_ir / mubasher / egx / lse_rns
    source_url            TEXT NOT NULL UNIQUE,
    local_path            TEXT,
    sha256                TEXT,
    bytes                 INTEGER,
    downloaded_at         TEXT,
    page_count            INTEGER,
    -- Document-level facts read from the filing (filled at extraction, with provenance in `facts`)
    auditor               TEXT,
    audit_opinion         TEXT,                 -- unqualified / qualified / adverse / disclaimer
    functional_currency   TEXT,
    presentation_currency TEXT
);

CREATE TABLE IF NOT EXISTS pages (
    document_id     INTEGER NOT NULL REFERENCES documents(id),
    page_no         INTEGER NOT NULL,           -- 1-based, as in the PDF
    text_chars      INTEGER NOT NULL,
    has_text_layer  INTEGER NOT NULL,           -- 0/1
    arabic_share    REAL,                       -- share of letters that are Arabic, NULL if no text
    kind            TEXT NOT NULL,              -- text / scanned
    statement       TEXT,                       -- set by the page map
    PRIMARY KEY (document_id, page_no)
);

-- Positioned words per page, from the PDF text layer or OCR. Cached so OCR runs once.
CREATE TABLE IF NOT EXISTS page_words (
    document_id INTEGER NOT NULL REFERENCES documents(id),
    page_no     INTEGER NOT NULL,
    source      TEXT NOT NULL,                  -- text_pdf / ocr
    ocr_lang    TEXT,
    words_json  TEXT NOT NULL,                  -- [[text, x0, x1, top, bottom, conf], ...] in PDF points
    text        TEXT NOT NULL,                  -- words joined into lines, for searching
    created_at  TEXT NOT NULL,
    PRIMARY KEY (document_id, page_no)
);

-- Topics found on a page (note topics, auditor's report). A page can carry several.
CREATE TABLE IF NOT EXISTS page_tags (
    document_id INTEGER NOT NULL REFERENCES documents(id),
    page_no     INTEGER NOT NULL,
    tag         TEXT NOT NULL,
    evidence    TEXT,                           -- the matched phrase
    PRIMARY KEY (document_id, page_no, tag)
);

-- Table rows read from statement pages, before mapping to standard fields.
CREATE TABLE IF NOT EXISTS raw_rows (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    page_no     INTEGER NOT NULL,
    statement   TEXT NOT NULL,
    line_no     INTEGER NOT NULL,
    label       TEXT NOT NULL,
    note_ref    TEXT,
    values_json TEXT NOT NULL,                  -- [{"column": "2024-12-31", "raw": "...", "value": 123.0}, ...]
    line_text   TEXT NOT NULL,                  -- the whole printed line, kept as provenance
    source      TEXT NOT NULL,                  -- text_pdf / ocr
    field       TEXT,                           -- standard field once mapped, NULL if unmapped
    created_at  TEXT NOT NULL
);

-- One row per extracted number (docs/05 "value record").
CREATE TABLE IF NOT EXISTS facts (
    id               INTEGER PRIMARY KEY,
    document_id      INTEGER NOT NULL REFERENCES documents(id),
    ticker           TEXT NOT NULL,
    fiscal_year      INTEGER NOT NULL,
    period           TEXT NOT NULL,
    period_end       TEXT NOT NULL,
    column_period_end TEXT NOT NULL,            -- current year or comparative column
    scope            TEXT NOT NULL,
    field            TEXT NOT NULL,
    value            REAL,                      -- as reported, sign as reported; NULL if missing
    value_normalised REAL,                      -- in currency units, sign convention applied
    currency         TEXT NOT NULL,
    unit             TEXT NOT NULL,             -- units / thousands / millions
    source_page      INTEGER,
    source_text      TEXT,
    source_language  TEXT,
    method           TEXT NOT NULL,             -- text_pdf / ocr / vision_model / excel / manual
    confidence       TEXT NOT NULL,             -- high / medium / low
    missing_reason   TEXT,
    is_restated      INTEGER DEFAULT 0,
    supersedes_id    INTEGER REFERENCES facts(id),  -- set when a review corrects an earlier row
    entered_by       TEXT,                      -- model/tool name, or reviewer for manual rows
    created_at       TEXT NOT NULL,
    notes            TEXT
);

CREATE TABLE IF NOT EXISTS checks (
    id          INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    check_name  TEXT NOT NULL,
    status      TEXT NOT NULL,                  -- passed / failed / not_checked
    detail      TEXT,
    fact_ids    TEXT,                           -- comma-separated facts.id used by the check
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS facts_lookup ON facts(ticker, fiscal_year, period, field);

-- Calculated figures (docs/02 definitions). Never stored in `facts`: each row keeps its formula and inputs.
CREATE TABLE IF NOT EXISTS metrics (
    ticker         TEXT NOT NULL,
    fiscal_year    INTEGER NOT NULL,
    metric         TEXT NOT NULL,
    value          REAL,                        -- NULL when it cannot be calculated
    unit           TEXT NOT NULL,               -- EGP / USD / % / x / days / pp
    formula        TEXT NOT NULL,               -- with the numbers used
    inputs         TEXT,                        -- JSON list of facts.id (and macro rows) used
    confidence     TEXT NOT NULL,               -- weakest input; capped by failed checks
    missing_reason TEXT,
    notes          TEXT,
    computed_at    TEXT NOT NULL,
    PRIMARY KEY (ticker, fiscal_year, metric)
);

-- Devaluation-exposure signals (docs/04) and the resulting profile, per company.
CREATE TABLE IF NOT EXISTS signals (
    ticker         TEXT NOT NULL,
    signal         TEXT NOT NULL,               -- S1..S7, or 'profile'
    value          REAL,
    points         INTEGER,                     -- -1 exposed, 0 neutral/inconclusive, +1 protected
    rule           TEXT NOT NULL,
    evidence       TEXT,                        -- the yearly figures used, with metric names
    confidence     TEXT,
    missing_reason TEXT,
    computed_at    TEXT NOT NULL,
    PRIMARY KEY (ticker, signal)
);

-- Red flags and diligence questions, each with the evidence that raised it.
CREATE TABLE IF NOT EXISTS flags (
    id          INTEGER PRIMARY KEY,
    ticker      TEXT NOT NULL,
    fiscal_year INTEGER,
    severity    TEXT NOT NULL,                  -- high / medium / low
    category    TEXT NOT NULL,                  -- audit / data / earnings_quality / leverage / working_capital / fx
    finding     TEXT NOT NULL,
    question    TEXT NOT NULL,                  -- what to ask management or the auditor
    evidence    TEXT NOT NULL,
    computed_at TEXT NOT NULL
);
