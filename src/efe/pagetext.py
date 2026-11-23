"""Positioned words for a page, from the PDF text layer when usable, otherwise from OCR.

Both sources produce the same Word records in PDF points, so table reading does not care
where the words came from. Results are cached in `page_words`.
"""
import datetime as dt
import functools
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium

from efe import config

OCR_DPI = 300


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    conf: float = 100.0  # OCR confidence 0-100; text-layer words are 100

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2


def words_to_text(words: list[Word]) -> str:
    """Join words into lines (by vertical position) for keyword search."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.cy, w.x0)):
        if lines and abs(lines[-1][0].cy - w.cy) <= max(3.0, 0.5 * (w.bottom - w.top)):
            lines[-1].append(w)
        else:
            lines.append([w])
    return "\n".join(" ".join(x.text for x in sorted(line, key=lambda w: w.x0)) for line in lines)


def vision_available() -> bool:
    """Apple Vision OCR (macOS, free, local). English only on macOS 14; no Arabic."""
    try:
        import Vision  # noqa: F401  (pyobjc, installed with ocrmac)
        return True
    except ImportError:
        return False


def tesseract_available() -> bool:
    import shutil
    return shutil.which("tesseract") is not None


def ocr_available(lang: str = "eng") -> bool:
    return tesseract_available() or (lang == "eng" and vision_available())


FAST_DPI = 150      # page mapping only needs titles; accurate recognition at low resolution
SECOND_DPI = 400    # second reading of statement pages; values that differ between readings are flagged


def prepare(image, prep: str | None):
    """Image clean-up before OCR. Tested on Misr Cement FY2022 (small sans-serif scan): sharpening and
    binarising each fixed different misread labels, so the two OCR readings use one each."""
    from PIL import ImageFilter

    if prep == "sharpen":
        return image.convert("L").filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN)
    if prep == "binarize":
        return image.convert("L").point(lambda x: 255 if x > 160 else 0)
    return image


def deskew(words: list[Word], slopes: list[float]) -> list[Word]:
    """Straighten a slightly tilted scan: Vision's long lines give the page's slope, and each word is
    moved vertically by slope x distance from the page's left edge, so a row's numbers at the right
    edge stay on the row's line. Below 0.1% tilt nothing changes."""
    if len(slopes) < 5:
        return words
    slopes = sorted(slopes)
    slope = slopes[len(slopes) // 2]
    if abs(slope) < 0.001:
        return words
    return [Word(w.text, w.x0, w.x1, w.top - slope * w.x0, w.bottom - slope * w.x0, w.conf) for w in words]


def vision_results(image, fast: bool = False) -> list:
    """Apple Vision text observations for a PIL image. Language correction is off so numbers are not 'fixed'."""
    import io

    import Vision
    from Foundation import NSData

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelFast if fast
                                 else Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)
    request.setRecognitionLanguages_(["en-US"])
    ok, err = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision OCR failed: {err}")
    return list(request.results() or [])


def from_vision(path: Path, page_no: int, dpi: int = OCR_DPI, fast: bool = False, prep: str | None = None) -> list[Word]:
    """Word boxes from Apple Vision: each recognised line is split into words, and Vision reports
    the box of each word's character range."""
    from Foundation import NSRange

    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[page_no - 1]
        w_pt, h_pt = page.get_size()
        image = prepare(page.render(scale=dpi / 72).to_pil(), prep)
    finally:
        pdf.close()
    words, backwards, forwards, slopes = [], 0, 0, []
    for obs in vision_results(image, fast):
        cand = obs.topCandidates_(1)[0]
        text = cand.string()
        conf = float(cand.confidence()) * 100
        pos = 0
        line_words = []
        for token in text.split():
            start = text.index(token, pos)
            pos = start + len(token)
            box, _ = cand.boundingBoxForRange_error_(NSRange(start, len(token)), None)
            if box is None:
                continue
            bb = box.boundingBox()  # normalised, origin bottom-left
            x0 = bb.origin.x * w_pt
            x1 = (bb.origin.x + bb.size.width) * w_pt
            top = (1 - bb.origin.y - bb.size.height) * h_pt
            bottom = (1 - bb.origin.y) * h_pt
            line_words.append(Word(token, x0, x1, top, bottom, conf))
        if len(line_words) >= 2 and abs(line_words[-1].cy - line_words[0].cy) < 0.05 * h_pt:
            span = line_words[-1].x0 - line_words[0].x0
            if abs(span) > 0.3 * w_pt:
                slopes.append((line_words[-1].cy - line_words[0].cy) / span)
        if len(line_words) >= 2:  # Vision gives each line in reading order
            if line_words[0].x0 > line_words[-1].x0:
                backwards += 1
            else:
                forwards += 1
        words += line_words
    words = deskew(words, slopes)
    if backwards > forwards:
        # The image was upside down (e.g. a scan stored with /Rotate): Vision still reads it, but its
        # boxes are in the image's frame, which reverses reading order. Turn the page the right way up.
        words = [Word(w.text, w_pt - w.x1, w_pt - w.x0, h_pt - w.bottom, h_pt - w.top, w.conf) for w in words]
    return words


CELL_DPIS = (600, 450)  # re-readings of single doubtful cells, at two resolutions


@functools.lru_cache(maxsize=4)
def page_image(path: Path, page_no: int, dpi: int):
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[page_no - 1]
        return page.render(scale=dpi / 72).to_pil(), page.get_size()
    finally:
        pdf.close()


def read_cell(path: Path, page_no: int, box: tuple[float, float, float, float], dpi: int = 600,
              digits: bool = True) -> str | None:
    """Re-reading of one table cell: the box (x0, top, x1, bottom in PDF points) is cropped from a
    high-resolution render and read alone, away from the rule lines and neighbouring figures that confuse a
    whole-page reading. Returns the text of the line nearest the box's vertical centre, or None.
    Pages stored upside down (words were turned the right way up) are tried with the box turned too."""
    from PIL import ImageOps

    image, (w_pt, h_pt) = page_image(path, page_no, dpi)
    s = dpi / 72
    x0, top, x1, bottom = box
    for flipped in (False, True):
        b = (w_pt - x1, h_pt - bottom, w_pt - x0, h_pt - top) if flipped else (x0, top, x1, bottom)
        crop = image.crop(tuple(int(v * s) for v in b))
        if flipped:
            crop = crop.rotate(180)
        crop = ImageOps.expand(crop, border=int(6 * s), fill="white")
        pieces = []
        for obs in vision_results(crop):
            bb = obs.boundingBox()
            cy = 1 - (bb.origin.y + bb.size.height / 2)  # 0 = top of the padded crop
            pieces.append((abs(cy - 0.5), bb.origin.x, obs.topCandidates_(1)[0].string()))
        if not pieces:
            continue
        nearest = min(p[0] for p in pieces)
        text = " ".join(t for d, _, t in sorted(pieces, key=lambda p: p[1]) if d - nearest < 0.12)
        if any(ch.isdigit() for ch in text) or (not digits and any(ch.isalpha() for ch in text)):
            return text
    return None


_open_pdf: tuple[Path, "pdfplumber.PDF"] | None = None


def from_text_layer(path: Path, page_no: int) -> list[Word]:
    # Keep the last document open: pages are read in order, and re-opening per page is slow.
    global _open_pdf
    if _open_pdf is None or _open_pdf[0] != path:
        if _open_pdf:
            _open_pdf[1].close()
        _open_pdf = (path, pdfplumber.open(path))
    page = _open_pdf[1].pages[page_no - 1]
    words = [Word(w["text"], w["x0"], w["x1"], w["top"], w["bottom"]) for w in page.extract_words()]
    page.flush_cache()
    return words


def from_tesseract(path: Path, page_no: int, lang: str, dpi: int = OCR_DPI) -> list[Word]:
    import pytesseract  # imported here so text-only runs work without the tesseract binary

    pdf = pdfium.PdfDocument(path)
    try:
        image = pdf[page_no - 1].render(scale=dpi / 72).to_pil()
    finally:
        pdf.close()
    data = pytesseract.image_to_data(image, lang=lang, config="--psm 6", output_type=pytesseract.Output.DICT)
    k = 72 / dpi
    words = []
    for text, left, top, width, height, conf in zip(data["text"], data["left"], data["top"],
                                                    data["width"], data["height"], data["conf"]):
        if text.strip() and float(conf) >= 0:
            words.append(Word(text, left * k, (left + width) * k, top * k, (top + height) * k, float(conf)))
    return words


def ocr(path: Path, page_no: int, lang: str = "eng", dpi: int = OCR_DPI, fast: bool = False,
        prep: str | None = None) -> tuple[list[Word], str]:
    """OCR with the best free engine available: Apple Vision for English, Tesseract otherwise.
    Returns (words, engine)."""
    if lang == "eng" and vision_available():
        return from_vision(path, page_no, dpi=dpi, fast=fast, prep=prep), "vision"
    if tesseract_available():
        return from_tesseract(path, page_no, lang, dpi=dpi), "tesseract"
    raise RuntimeError(f"no OCR engine for language {lang!r}: install Tesseract (brew install tesseract tesseract-lang)")


def doc_path(conn: sqlite3.Connection, doc_id: int) -> Path:
    return config.ROOT / conn.execute("SELECT local_path FROM documents WHERE id=?", (doc_id,)).fetchone()["local_path"]


def get_words(conn: sqlite3.Connection, doc_id: int, page_no: int, ocr_lang: str = "eng",
              force_ocr: bool = False, fast: bool = False) -> tuple[list[Word], str]:
    """Returns (words, source) with source 'text_pdf', 'ocr' or 'ocr_fast'. Uses the cache when it is
    good enough: a fast reading is replaced by an accurate one when accuracy is asked for, and
    force_ocr replaces a text-layer entry."""
    row = conn.execute("SELECT source, words_json FROM page_words WHERE document_id=? AND page_no=?",
                       (doc_id, page_no)).fetchone()
    if row:
        stale = (force_ocr and row["source"] == "text_pdf") or (not fast and row["source"] == "ocr_fast")
        if not stale:
            return [Word(*w) for w in json.loads(row["words_json"])], row["source"]
        conn.execute("DELETE FROM page_words WHERE document_id=? AND page_no=?", (doc_id, page_no))
    p = conn.execute("SELECT kind FROM pages WHERE document_id=? AND page_no=?", (doc_id, page_no)).fetchone()
    path = doc_path(conn, doc_id)
    if p["kind"] == "text" and not force_ocr:
        words, source, lang = from_text_layer(path, page_no), "text_pdf", None
    else:
        # 'fast' means low resolution only: Vision's fast recognition level cannot read titles (tested on ARCC, LCSW, MCQE)
        words, engine = ocr(path, page_no, ocr_lang, dpi=FAST_DPI if fast else OCR_DPI,
                            prep=None if fast else "sharpen")
        source, lang = ("ocr_fast" if fast else "ocr"), f"{engine}:{ocr_lang}"
    conn.execute(
        "INSERT INTO page_words (document_id, page_no, source, ocr_lang, words_json, text, created_at) VALUES (?,?,?,?,?,?,?)",
        (doc_id, page_no, source, lang,
         json.dumps([[w.text, round(w.x0, 1), round(w.x1, 1), round(w.top, 1), round(w.bottom, 1), w.conf] for w in words]),
         words_to_text(words), dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
    )
    conn.commit()
    return words, source


def get_text(conn: sqlite3.Connection, doc_id: int, page_no: int, ocr_lang: str = "eng", fast: bool = False) -> str:
    get_words(conn, doc_id, page_no, ocr_lang, fast=fast)
    return conn.execute("SELECT text FROM page_words WHERE document_id=? AND page_no=?", (doc_id, page_no)).fetchone()["text"]
