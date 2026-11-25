"""
text_cleaning.py
================

Text Cleaning stage for the "Authenticity Validator for Academia" project.

Pipeline position:

    Document Upload
        -> Universal Preprocessing   (backend/processing/preprocessing.py)
        -> OCR / Text Extraction     (backend/processing/ocr.py)
        -> Text Cleaning             <-- this module
        -> Information Extraction
        -> Authenticity Verification
        -> Similarity / Plagiarism Analysis
        -> AI Analysis
        -> Scoring
        -> Final Verification Result

PURPOSE
-------
Take the raw text produced by the OCR stage (which may contain typed
text, scanned-document OCR, or handwriting-OCR output, across one or
more pages) and normalize its *formatting* -- spacing, line breaks,
stray symbols, typographic punctuation -- without ever rewriting,
autocorrecting, or inventing words.

This module is intentionally conservative. Academic documents rely on
exact preservation of names, student/enrollment IDs, certificate
numbers, dates, marks/grades, email addresses, URLs, institution and
course names, and signature-related text. None of those are altered:
this module only touches whitespace, stray punctuation/noise symbols,
and safe typographic normalization, and it explicitly shields anything
that looks like an email, URL, date, or alphanumeric ID from every
cleaning step before those steps run.

This module does NOT:
    - Use an LLM or any external/cloud API.
    - Autocorrect spelling or rewrite words.
    - Perform information extraction, authenticity verification,
      plagiarism/similarity detection, AI analysis, or scoring.
    - Expose FastAPI routes, database access, or authentication.
    - Modify `preprocessing.py` or `ocr.py`, or depend on their internals
      (it only expects plain text, optionally containing the
      "----- Page N -----" markers that `ocr.py.combine_pages` produces).

No third-party packages are required -- only the Python standard
library (`re`, `unicodedata`, `dataclasses`, `pathlib`, `logging`).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

logger = logging.getLogger(__name__)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


# --------------------------------------------------------------------------- #
# Custom exceptions
# --------------------------------------------------------------------------- #

class TextCleaningError(Exception):
    """Base exception for all text-cleaning failures."""


class InvalidInputError(TextCleaningError):
    """Raised when the input to `clean_text` / `clean_text_file` is invalid."""


class EncodingError(TextCleaningError):
    """Raised when text cannot be read/decoded/encoded as UTF-8."""


# --------------------------------------------------------------------------- #
# Result structures
# --------------------------------------------------------------------------- #

@dataclass
class CleaningStatistics:
    """Counts of how many times each cleaning operation actually fired."""

    pages_processed: int = 0
    repeated_spaces_collapsed: int = 0
    blank_lines_removed: int = 0
    punctuation_spacing_fixed: int = 0
    noise_symbols_removed: int = 0
    duplicated_characters_fixed: int = 0
    typography_normalized: int = 0


@dataclass
class TextCleaningResult:
    """Structured result returned by `clean_text` / `clean_text_file`."""

    original_text: str
    cleaned_text: str
    status: str  # "success" | "partial" | "empty" | "failed"
    warnings: List[str]
    statistics: CleaningStatistics
    original_char_count: int
    cleaned_char_count: int
    original_word_count: int
    cleaned_word_count: int


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# Matches the page-boundary markers produced by ocr.py's `combine_pages`,
# e.g. "----- Page 1 -----". Kept loose (variable dash count/spacing) so
# minor formatting differences don't break page-boundary preservation.
PAGE_MARKER_PATTERN = re.compile(r"^-{2,}\s*Page\s+(\d+)\s*-{2,}$")

# Tokens that must never be altered by cleaning. Matched and masked
# before any other step runs, then restored verbatim at the end.
_EMAIL_PATTERN = r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+"
_URL_PATTERN = r"(?:https?://|www\.)\S+"
_DATE_PATTERN = r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b"
# Alphanumeric tokens of 5+ characters containing BOTH a letter and a
# digit (e.g. student IDs, enrollment numbers, certificate numbers like
# "20CS1234" or "CERT-2023-0098"). Plain words and plain numbers are
# untouched by this pattern.
_ID_PATTERN = r"\b(?=[A-Za-z0-9-]{5,}\b)(?=[A-Za-z0-9-]*[0-9])(?=[A-Za-z0-9-]*[A-Za-z])[A-Za-z0-9-]+\b"

_PROTECTED_TOKEN_PATTERN = re.compile(
    f"(?P<email>{_EMAIL_PATTERN})|(?P<url>{_URL_PATTERN})|"
    f"(?P<date>{_DATE_PATTERN})|(?P<id>{_ID_PATTERN})"
)

# Private-use-area characters used as mask delimiters. Chosen because
# they cannot legitimately appear in OCR text, so they are safe to use
# as unique, whitespace-free placeholders during cleaning.
_MASK_START = "\uE000"
_MASK_END = "\uE001"

# Safe typographic normalizations: curly quotes/dashes -> plain ASCII
# equivalents, ellipsis -> three dots. These do not change meaning.
_TYPOGRAPHY_REPLACEMENTS: Dict[str, str] = {
    "\u2018": "'", "\u2019": "'", "\u201A": "'", "\u201B": "'",
    "\u201C": '"', "\u201D": '"', "\u201E": '"', "\u201F": '"',
    "\u2013": "-", "\u2014": "-",
    "\u2026": "...",
}


# --------------------------------------------------------------------------- #
# Page splitting (preserves page boundaries & order)
# --------------------------------------------------------------------------- #

def _split_pages(text: str) -> List[Tuple[Optional[str], str]]:
    """
    Split text into (marker, body) segments using ocr.py's page markers.

    If no page markers are present, the whole text is treated as a
    single segment with a `None` marker, so this function works equally
    well for single-page and multi-page OCR output.

    Args:
        text: Full OCR text, possibly containing "----- Page N -----"
            marker lines.

    Returns:
        An ordered list of (marker_line_or_None, page_body_text) tuples.
    """
    lines = text.split("\n")
    segments: List[Tuple[Optional[str], List[str]]] = []
    leading_lines: List[str] = []
    current_marker: Optional[str] = None
    current_lines: List[str] = []
    seen_marker = False

    for line in lines:
        if PAGE_MARKER_PATTERN.match(line.strip()):
            if not seen_marker:
                if any(candidate.strip() for candidate in leading_lines):
                    segments.append((None, leading_lines))
            else:
                segments.append((current_marker, current_lines))
            current_marker = line.strip()
            current_lines = []
            seen_marker = True
        else:
            (current_lines if seen_marker else leading_lines).append(line)

    if seen_marker:
        segments.append((current_marker, current_lines))
    else:
        segments.append((None, leading_lines))

    return [(marker, "\n".join(body_lines)) for marker, body_lines in segments]


# --------------------------------------------------------------------------- #
# Protected-token masking
# --------------------------------------------------------------------------- #

def _mask_protected_tokens(text: str) -> Tuple[str, Dict[str, str]]:
    """
    Replace emails, URLs, dates, and ID-like alphanumeric tokens with
    unique placeholders so subsequent cleaning steps cannot alter them.

    Returns:
        (masked_text, mapping) where `mapping` maps each placeholder back
        to its original substring for later restoration.
    """
    mapping: Dict[str, str] = {}
    counter = 0

    def _replace(match: re.Match) -> str:
        nonlocal counter
        counter += 1
        placeholder = f"{_MASK_START}{counter}{_MASK_END}"
        mapping[placeholder] = match.group(0)
        return placeholder

    masked_text = _PROTECTED_TOKEN_PATTERN.sub(_replace, text)
    return masked_text, mapping


def _unmask_protected_tokens(text: str, mapping: Dict[str, str]) -> str:
    """Restore every masked placeholder to its original, untouched text."""
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text


# --------------------------------------------------------------------------- #
# Individual cleaning operations (each returns (new_text, change_count))
# --------------------------------------------------------------------------- #

def _strip_control_characters(text: str) -> Tuple[str, int]:
    """Remove non-printable Unicode control/format characters (keeps \\n, \\t)."""
    kept_chars: List[str] = []
    removed = 0
    for char in text:
        if char in ("\n", "\t"):
            kept_chars.append(char)
            continue
        if unicodedata.category(char).startswith("C"):
            removed += 1
            continue
        kept_chars.append(char)
    return "".join(kept_chars), removed


def _normalize_typography(text: str) -> Tuple[str, int]:
    """Normalize curly quotes, en/em dashes, and ellipsis to plain ASCII."""
    count = 0
    for original, replacement in _TYPOGRAPHY_REPLACEMENTS.items():
        occurrences = text.count(original)
        if occurrences:
            text = text.replace(original, replacement)
            count += occurrences
    return text, count


def _collapse_excessive_punctuation(text: str) -> Tuple[str, int]:
    """
    Collapse long runs of the same punctuation mark (4 or more) down to
    three, e.g. "!!!!!!" -> "!!!". Short runs like ".." or the common
    ellipsis "..." are left alone since they can be intentional.
    """
    pattern = re.compile(r"([!?.,;:])\1{3,}")
    return pattern.subn(lambda m: m.group(1) * 3, text)


def _fix_space_before_punctuation(text: str) -> Tuple[str, int]:
    """Remove stray whitespace before punctuation, e.g. 'word ,' -> 'word,'."""
    pattern = re.compile(r"[ \t]+([,.;:!?)])")
    return pattern.subn(r"\1", text)


def _fix_space_after_punctuation(text: str) -> Tuple[str, int]:
    """
    Insert a single space after sentence punctuation when it is directly
    glued to the next word, e.g. 'Hello,World' -> 'Hello, World'.

    Restricted to punctuation immediately followed by a LETTER (not a
    digit) so decimal numbers (e.g. "8.5"), dates, and masked tokens are
    never affected.
    """
    pattern = re.compile(r"([,.;:!?])(?=[A-Za-z])")
    return pattern.subn(r"\1 ", text)


def _collapse_repeated_spaces(text: str) -> Tuple[str, int]:
    """
    Collapse any run of 2+ spaces (within a line) down to a single space.

    This is the common OCR artifact seen in names like "Shayna    Verma"
    or headings with stretched character spacing. An earlier version of
    this function tried to detect and preserve "table-like" wide gaps,
    but that heuristic misfired on ordinary paragraphs that simply had
    several stray wide gaps from OCR noise, producing double spaces
    where a single space was expected. Reliable table-column recovery
    from whitespace alone is fragile with OCR text and is left to the
    downstream information-extraction stage; here we prioritize the
    predictable, correct behavior for normal text.
    """
    return re.subn(r" {2,}", " ", text)


def _collapse_blank_lines(text: str) -> Tuple[str, int]:
    """
    Collapse egregious runs of blank lines (3 or more consecutive blank
    lines) down to a single blank line. Normal single/double blank lines
    -- the usual paragraph separators -- are left untouched so paragraph
    structure is preserved.
    """
    pattern = re.compile(r"\n{4,}")
    return pattern.subn("\n\n", text)


# --------------------------------------------------------------------------- #
# Page-level cleaning orchestration
# --------------------------------------------------------------------------- #

def _clean_page_text(text: str, stats: CleaningStatistics) -> str:
    """
    Run the full, ordered cleaning pipeline on a single page's body text.

    Order matters:
        1. Unicode normalization (NFC) -- canonical form, no visible change.
        2. Newline normalization (\\r\\n / \\r -> \\n).
        3. Control-character stripping (on the real text, before masking).
        4. Protected-token masking (emails/URLs/dates/IDs shielded).
        5. Typographic normalization (quotes/dashes/ellipsis).
        6. Excessive punctuation-run collapsing.
        7. Punctuation spacing fixes.
        8. Repeated-space collapsing (table-aware).
        9. Trailing-whitespace trim per line.
        10. Excessive blank-line collapsing.
        11. Protected-token restoration (unmask).
    """
    if not text or not text.strip():
        # Nothing meaningful to clean (e.g. a blank page, or ocr.py's own
        # "[No text extracted]" placeholder) -- leave it exactly as-is.
        return text

    working = unicodedata.normalize("NFC", text)
    working = working.replace("\r\n", "\n").replace("\r", "\n")

    working, removed = _strip_control_characters(working)
    stats.noise_symbols_removed += removed

    working, mapping = _mask_protected_tokens(working)

    working, count = _normalize_typography(working)
    stats.typography_normalized += count

    working, count = _collapse_excessive_punctuation(working)
    stats.duplicated_characters_fixed += count

    working, count_before = _fix_space_before_punctuation(working)
    working, count_after = _fix_space_after_punctuation(working)
    stats.punctuation_spacing_fixed += count_before + count_after

    working, count = _collapse_repeated_spaces(working)
    stats.repeated_spaces_collapsed += count

    working = "\n".join(line.rstrip() for line in working.split("\n"))

    working, count = _collapse_blank_lines(working)
    stats.blank_lines_removed += count

    working = working.strip("\n")

    return _unmask_protected_tokens(working, mapping)


# --------------------------------------------------------------------------- #
# Noise detection (informational only -- never triggers text modification)
# --------------------------------------------------------------------------- #

def _detect_noise_warnings(text: str) -> List[str]:
    """
    Produce human-readable warnings about likely OCR quality issues.

    This is purely diagnostic: it never causes additional text to be
    altered or removed, per the requirement to avoid aggressively
    modifying uncertain text.
    """
    warnings: List[str] = []

    total_chars = len(text)
    if total_chars > 0:
        alnum_chars = sum(1 for char in text if char.isalnum())
        alnum_ratio = alnum_chars / total_chars
        if alnum_ratio < 0.4:
            warnings.append(
                f"Low alphanumeric character ratio ({alnum_ratio:.0%}) detected; "
                f"OCR output may be noisy, handwritten, or of poor quality."
            )

    no_text_pages = text.count("[No text extracted]")
    if no_text_pages:
        warnings.append(
            f"{no_text_pages} page(s) had no text extracted by OCR."
        )

    return warnings


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def clean_text(ocr_text: Optional[str]) -> TextCleaningResult:
    """
    Clean and normalize OCR-extracted text while strictly preserving
    factual content (names, IDs, dates, marks, emails, URLs, headings,
    etc.). This is the main entry point for the text-cleaning stage.

    Args:
        ocr_text: The full extracted text from the OCR stage (e.g.
            `OCRResult.combined_text` from ocr.py), which may span
            multiple pages separated by "----- Page N -----" markers, or
            be plain single-page text with no markers at all.

    Returns:
        A `TextCleaningResult` with the cleaned text, per-run
        statistics, warnings, and a status of "success", "partial",
        "empty", or "failed".

    Raises:
        InvalidInputError: If `ocr_text` is None or not a string.
        EncodingError: If a Unicode error occurs while normalizing text.
        TextCleaningError: On any other unexpected failure.
    """
    try:
        if ocr_text is None:
            raise InvalidInputError("OCR text input is None; expected a string.")
        if not isinstance(ocr_text, str):
            raise InvalidInputError(
                f"OCR text must be a string, got {type(ocr_text).__name__}."
            )

        original_text = ocr_text
        original_char_count = len(original_text)
        original_word_count = len(original_text.split())

        if not original_text.strip():
            logger.warning("Received empty OCR text; skipping cleaning.")
            return TextCleaningResult(
                original_text=original_text,
                cleaned_text=original_text,
                status="empty",
                warnings=["OCR text is empty; no cleaning was performed."],
                statistics=CleaningStatistics(),
                original_char_count=original_char_count,
                cleaned_char_count=original_char_count,
                original_word_count=original_word_count,
                cleaned_word_count=original_word_count,
            )

        warnings = _detect_noise_warnings(original_text)
        stats = CleaningStatistics()

        pages = _split_pages(original_text)
        stats.pages_processed = len(pages)

        page_outputs: List[str] = []
        for marker, body in pages:
            cleaned_body = _clean_page_text(body, stats)
            if marker is not None:
                page_outputs.append(f"{marker}\n{cleaned_body}" if cleaned_body else marker)
            else:
                page_outputs.append(cleaned_body)

        cleaned_text = "\n\n".join(part for part in page_outputs).strip("\n")

        if not cleaned_text.strip():
            # Safety net: cleaning should never leave a non-empty document
            # empty. If that would happen, fall back to the original text
            # rather than inventing or discarding content.
            logger.warning(
                "Cleaning produced empty output for non-empty input; "
                "falling back to original text."
            )
            warnings.append(
                "Cleaning would have removed all content; original text was "
                "preserved as a safety fallback."
            )
            cleaned_text = original_text
            status = "failed"
        elif warnings:
            status = "partial"
        else:
            status = "success"

        cleaned_char_count = len(cleaned_text)
        cleaned_word_count = len(cleaned_text.split())

        logger.info(
            "Text cleaning complete: status=%s, pages=%d, chars %d -> %d, "
            "warnings=%d.",
            status, stats.pages_processed, original_char_count,
            cleaned_char_count, len(warnings),
        )

        return TextCleaningResult(
            original_text=original_text,
            cleaned_text=cleaned_text,
            status=status,
            warnings=warnings,
            statistics=stats,
            original_char_count=original_char_count,
            cleaned_char_count=cleaned_char_count,
            original_word_count=original_word_count,
            cleaned_word_count=cleaned_word_count,
        )

    except InvalidInputError:
        raise
    except UnicodeError as exc:
        raise EncodingError(f"Encoding error while cleaning text: {exc}") from exc
    except TextCleaningError:
        raise
    except Exception as exc:
        logger.exception("Unexpected error during text cleaning")
        raise TextCleaningError(f"Unexpected error during text cleaning: {exc}") from exc


def clean_text_file(input_path: Path, output_path: Optional[Path] = None) -> TextCleaningResult:
    """
    Convenience wrapper around `clean_text` for file-based integration.

    Reads UTF-8 OCR text from `input_path` (e.g. the `ocr_extracted_text.txt`
    file written by ocr.py), cleans it, and optionally writes the cleaned
    result to `output_path`. The original input file is never modified.

    Args:
        input_path: Path to a UTF-8 text file containing OCR output.
        output_path: Optional path to save the cleaned text to. Parent
            directories are created automatically if needed.

    Returns:
        A `TextCleaningResult`, exactly as from `clean_text`.

    Raises:
        InvalidInputError: If the input file does not exist or is not a file.
        EncodingError: If the file cannot be decoded as UTF-8.
        TextCleaningError: If the file cannot be read, or the cleaned
            output cannot be written.
    """
    if not isinstance(input_path, Path):
        input_path = Path(input_path)

    if not input_path.exists() or not input_path.is_file():
        raise InvalidInputError(f"Input text file does not exist: {input_path}")

    try:
        raw_text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise EncodingError(f"Failed to decode file as UTF-8: {input_path}") from exc
    except OSError as exc:
        raise TextCleaningError(f"Failed to read input file: {input_path}") from exc

    result = clean_text(raw_text)

    if output_path is not None:
        if not isinstance(output_path, Path):
            output_path = Path(output_path)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result.cleaned_text, encoding="utf-8")
        except OSError as exc:
            raise TextCleaningError(f"Failed to write cleaned text to: {output_path}") from exc

    return result


__all__ = [
    "TextCleaningError",
    "InvalidInputError",
    "EncodingError",
    "CleaningStatistics",
    "TextCleaningResult",
    "clean_text",
    "clean_text_file",
]