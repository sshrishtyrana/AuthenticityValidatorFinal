from __future__ import annotations

import concurrent.futures
import logging
import os
import re
import shutil
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from .preprocessing import (
    DocumentMetadata,
    DocumentPreprocessingError,
    DocumentType,
    PageMetadata,
    binarize_image,
)

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

class OCRProcessingError(Exception):
    """Base exception for all OCR / text-extraction failures."""


class TesseractNotFoundError(OCRProcessingError):
    """Raised when the Tesseract OCR engine cannot be located or executed."""


class OCRImageError(OCRProcessingError):
    """Raised when an image intended for OCR is missing, invalid, or corrupted."""


class OCRDependencyError(OCRProcessingError):
    """Raised when a required Python OCR dependency is not installed."""


class OCRModelError(OCRProcessingError):
    """
    Raised when an optional OCR model (EasyOCR, TrOCR) fails to load,
    download, or run inference.

    This is always treated as non-fatal for the overall page/document:
    callers catch it, record a warning, and fall back to whatever
    result is already available.
    """


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# Default OCR language. Additional languages (e.g. "eng+hin") can be
# passed via the `lang` parameter of `run_ocr` / `ocr_image`, provided
# the corresponding Tesseract language data files are installed.
DEFAULT_OCR_LANGUAGE = "eng"

# Per-image OCR timeout, in seconds, passed straight to Tesseract.
OCR_TIMEOUT_SECONDS = 60

# Timeouts for the optional heavier engines. These run in a worker
# thread so a hang cannot stall the whole document indefinitely.
EASYOCR_TIMEOUT_SECONDS = 90
TROCR_TIMEOUT_SECONDS = 120

# Handwriting OCR model. Downloaded once from Hugging Face Hub and
# cached locally (~/.cache/huggingface) on first use.
TROCR_MODEL_NAME = "microsoft/trocr-base-handwritten"

# Filename used for the combined OCR/text-extraction output.
OCR_OUTPUT_FILENAME = "ocr_extracted_text.txt"

# Well-known Tesseract install locations, checked in addition to PATH.
_WINDOWS_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
_UNIX_TESSERACT_CANDIDATES = [
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
]

# Cached, resolved path to the Tesseract binary (populated on first use).
_tesseract_path_cache: Optional[Path] = None
# PaddleOCR is loaded lazily so importing this module does not require the
# Paddle packages/models unless an image actually needs OCR.
_paddleocr_cache: Dict[str, object] = {}
_paddleocr_vl_cache: Dict[str, object] = {}

# PP-OCRv5 server models are the configuration used by the working
# handwriting/document OCR path supplied for integration.
PADDLEOCR_DET_MODEL = "PP-OCRv5_server_det"
PADDLEOCR_REC_MODEL = "PP-OCRv5_server_rec"
PADDLEOCR_VL_VERSION = "v1.6"


# Below this longest-side dimension, an upscaled variant is generated to
# help small/low-resolution text (small print, tiny stamps, etc.).
_UPSCALE_THRESHOLD_PX = 1000
_UPSCALE_TARGET_PX = 1000

# Alternate Tesseract page-segmentation modes tried, cheaply, on the
# same engine/image before escalating to a different engine entirely.
# 6 = uniform block of text, 4 = single column of variable-size text,
# 11 = sparse text (find as much text as possible, no layout assumed).
# Certificates, forms, stamps, and other non-paragraph layouts often
# confuse the default PSM 3 ("fully automatic") mode.
_TESSERACT_PSM_FALLBACKS = (6, 4, 11)

# A small, generic set of common English/academic-document words, used
# only as a *plausibility* signal in the quality assessment (does OCR
# output look like real language at all). This is NOT derived from any
# specific test document -- it is a fixed, generic vocabulary.
_COMMON_WORDS = frozenset(
    {
        # Generic document-language terms. These are only a weak OCR
        # plausibility signal; they never imply a document type or value.
        "name", "date", "number", "address", "reference", "identifier",
        "issued", "issue", "expiry", "signature", "authorized",
        "organization", "company", "department", "status",
        "amount", "total", "balance", "account", "invoice",
        "description", "email", "phone", "document", "form",
        "the", "and", "of", "in", "to", "is", "for", "with",
        "from", "at", "or", "as", "on", "by", "this", "that",
    }
)

# Secondary domain vocabulary retained only as an optional signal so that
# established academic documents continue to score naturally. It is never
# required for a good OCR assessment and never determines document type.
_ACADEMIC_DOMAIN_WORDS = frozenset(
    {
        "university", "college", "certificate", "certify", "certifies",
        "institute", "institution", "student", "students", "course",
        "training", "completed", "awarded", "school", "academy",
        "examination", "result", "grade", "marks", "subject", "semester",
        "program", "programme", "diploma", "degree", "bachelor", "master",
        "engineering", "technology", "science", "education", "board",
        "presented", "successfully", "participation",
    }
)


# --------------------------------------------------------------------------- #
# OCR engine identifiers
# --------------------------------------------------------------------------- #

class OCREngine(str, Enum):
    """Identifies which strategy produced a page's final text."""

    NATIVE_TEXT = "native_text"
    TESSERACT = "tesseract"
    PADDLEOCR = "paddleocr"
    PADDLEOCR_VL = "paddleocr_vl"
    # Kept for backward compatibility with older callers/results.
    EASYOCR = "easyocr"
    TROCR = "trocr"
    NONE = "none"


# --------------------------------------------------------------------------- #
# Result structures
# --------------------------------------------------------------------------- #

@dataclass
class PageOCRResult:
    """Extraction result for a single page/logical unit of a document."""

    page_number: int
    text: str
    confidence: Optional[float]
    source_image_path: Optional[Path]
    ocr_applied: bool
    text_extracted: bool

    # --- Added fields (all optional / defaulted -> backward compatible) ---
    ocr_engine: Optional[str] = None
    quality_score: Optional[float] = None
    quality_label: Optional[str] = None
    # True when `confidence` comes from an engine that does not produce a
    # properly calibrated probability (e.g. EasyOCR's detector score, or
    # is simply unavailable, e.g. TrOCR). False for Tesseract, whose
    # word-level confidence is at least self-consistent.
    confidence_approximate: bool = False
    # Diagnostic trail: which "engine:variant" combinations were tried,
    # in order, for this page.
    engines_attempted: List[str] = field(default_factory=list)


@dataclass
class OCRResult:
    """Structured result returned by `run_ocr`."""

    original_filename: str
    document_type: DocumentType
    num_pages: int
    pages: List[PageOCRResult]
    combined_text: str
    average_confidence: Optional[float]
    output_text_path: Optional[Path]
    ocr_required: bool
    processing_status: str
    warnings: List[str] = field(default_factory=list)

    # --- Added field (optional / defaulted -> backward compatible) ---
    engine_usage_summary: Dict[str, int] = field(default_factory=dict)


@dataclass
class QualityAssessment:
    """
    A genuine, engine-agnostic assessment of whether a piece of OCR
    output actually looks like usable text -- deliberately independent
    of whatever confidence number the OCR engine itself reported.
    """

    score: float          # 0-100, higher = more trustworthy
    label: str            # "empty" | "poor" | "fair" | "good"
    word_count: int
    alpha_ratio: float
    details: List[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Tesseract detection & configuration
# --------------------------------------------------------------------------- #

def _candidate_tesseract_paths() -> List[Path]:
    """Build an ordered list of plausible Tesseract executable locations."""
    candidates: List[Path] = []

    env_path = os.environ.get("TESSERACT_CMD")
    if env_path:
        candidates.append(Path(env_path))

    which_path = shutil.which("tesseract")
    if which_path:
        candidates.append(Path(which_path))

    for raw_path in _WINDOWS_TESSERACT_CANDIDATES + _UNIX_TESSERACT_CANDIDATES:
        candidates.append(Path(raw_path))

    return candidates


def get_tesseract_path() -> Path:
    """
    Automatically detect the Tesseract OCR executable.

    Detection order:
        1. `TESSERACT_CMD` environment variable.
        2. `tesseract` on the system PATH.
        3. Common Windows install locations
           (e.g. C:\\Program Files\\Tesseract-OCR\\tesseract.exe).
        4. Common Linux/macOS install locations.

    Returns:
        Path to a usable Tesseract executable.

    Raises:
        TesseractNotFoundError: If no working Tesseract installation can
            be found.
    """
    global _tesseract_path_cache
    if _tesseract_path_cache is not None:
        return _tesseract_path_cache

    for candidate in _candidate_tesseract_paths():
        try:
            if candidate.is_file():
                _tesseract_path_cache = candidate
                logger.info("Detected Tesseract OCR at: %s", candidate)
                return candidate
        except OSError:
            continue

    raise TesseractNotFoundError(
        "Tesseract OCR engine could not be found on this system. "
        "Install Tesseract OCR and ensure it is on the system PATH, or "
        "set the TESSERACT_CMD environment variable to its executable "
        "path (e.g. 'C:\\Program Files\\Tesseract-OCR\\tesseract.exe' on "
        "Windows, or '/usr/bin/tesseract' on Linux)."
    )


def _configure_pytesseract():
    """
    Import pytesseract and point it at the detected Tesseract executable.

    Returns:
        The configured `pytesseract` module.

    Raises:
        OCRDependencyError: If the `pytesseract` package is not installed.
        TesseractNotFoundError: If the Tesseract binary cannot be located.
    """
    try:
        import pytesseract
    except ImportError as exc:
        raise OCRDependencyError(
            "The 'pytesseract' package is required for OCR. "
            "Install it via 'pip install pytesseract'."
        ) from exc

    tesseract_path = get_tesseract_path()
    pytesseract.pytesseract.tesseract_cmd = str(tesseract_path)
    return pytesseract


# --------------------------------------------------------------------------- #
# Timeout helper (shared by all engines, not just Tesseract)
# --------------------------------------------------------------------------- #

def _run_with_timeout(func, timeout: int, *args, **kwargs):
    """
    Run `func(*args, **kwargs)` in a worker thread and enforce a wall-clock
    timeout, so a slow/hanging OCR engine cannot stall the whole document.

    Raises:
        OCRProcessingError: If the call does not complete within `timeout`
            seconds. The underlying thread is abandoned (Python has no
            safe way to force-kill a thread), but the caller regains
            control immediately.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise OCRProcessingError(
                f"OCR engine timed out after {timeout}s."
            ) from exc


# --------------------------------------------------------------------------- #
# Image validation
# --------------------------------------------------------------------------- #

def validate_image_path(image_path: Path) -> None:
    """
    Verify that an image path exists and points to a valid, decodable
    image before it is handed to any OCR engine.

    Raises:
        OCRImageError: If the file is missing, not a file, or not a
            valid/readable image.
    """
    if not image_path.exists():
        raise OCRImageError(f"Image file does not exist: {image_path}")
    if not image_path.is_file():
        raise OCRImageError(f"Image path is not a file: {image_path}")

    try:
        with Image.open(image_path) as img:
            img.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise OCRImageError(
            f"Invalid or corrupted image, cannot OCR: {image_path.name}"
        ) from exc


# --------------------------------------------------------------------------- #
# Quality assessment (engine-agnostic)
# --------------------------------------------------------------------------- #

def assess_ocr_quality(text: str) -> QualityAssessment:
    """
    Assess whether OCR output looks like usable document text.

    The assessment is document-generic: it uses language, character balance,
    token quality, common generic document vocabulary, and lightweight
    document-structure signals. Academic vocabulary is only a secondary
    signal so existing academic documents retain their good scores.

    This function never changes OCR text and never assumes a document type.
    """
    details: List[str] = []
    stripped = text.strip() if text else ""

    if not stripped:
        return QualityAssessment(
            score=0.0,
            label="empty",
            word_count=0,
            alpha_ratio=0.0,
            details=["No text was recognized."],
        )

    total_chars = len(stripped)
    alpha_chars = sum(1 for c in stripped if c.isalpha())
    alpha_ratio = alpha_chars / total_chars if total_chars else 0.0

    # Keep tokenization deliberately language/document agnostic. OCR output
    # can contain numbers, identifiers, dates, currency, and short labels.
    words = re.findall(r"[A-Za-z']{2,}", stripped)
    word_count = len(words)

    allowed_punct = set(".,'-/:()@#%&+$=;!?")
    symbol_chars = sum(
        1 for c in stripped
        if not (c.isalnum() or c.isspace() or c in allowed_punct)
    )
    symbol_ratio = symbol_chars / total_chars if total_chars else 0.0

    has_repeated_run = bool(re.search(r"(.)\1{4,}", stripped))

    common_hits = sum(1 for w in words if w.lower() in _COMMON_WORDS)
    common_ratio = (common_hits / word_count) if word_count else 0.0

    academic_hits = sum(
        1 for w in words if w.lower() in _ACADEMIC_DOMAIN_WORDS
    )
    academic_ratio = (academic_hits / word_count) if word_count else 0.0

    # Generic structural evidence found across many document families:
    # dates, contact data, identifiers, key/value labels, monetary values,
    # organization/issuer language, and common document headings.
    structure_patterns = (
        r"\b\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,4})?\b",  # numeric date/id shapes
        r"\b(?:19|20)\d{2}\b",                         # year
        r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b",       # email
        r"\b(?:https?://|www\.)\S+\b",                # URL
        r"\b(?:ref(?:erence)?|id(?:entifier)?|account|invoice|document|"
        r"number|no\.?|code)\s*[:#-]?\s*[A-Z0-9][A-Z0-9/_-]{1,}\b",
        r"\b(?:amount|total|balance)\s*[:#-]?\s*(?:[$€£₹]\s*)?\d",
        r"\b(?:issued?|expiry|expires?|valid\s+until|due\s+date)\b",
        r"\b(?:name|address|email|phone|department|status|description)\s*[:#-]",
        r"\b(?:signature|signed|authorized|organisation|organization|company)\b",
        r"\b(?:form|statement|invoice|report|application|agreement|letter)\b",
        r"\b(?:passport|license|licence|identity|identification|id\s+card)\b",
    )
    structure_hits = sum(
        bool(re.search(pattern, stripped, re.IGNORECASE))
        for pattern in structure_patterns
    )
    structure_ratio = structure_hits / len(structure_patterns)

    score = 0.0
    score += min(alpha_ratio, 1.0) * 35
    score += min(word_count / 20.0, 1.0) * 25
    score += min(common_ratio * 3.0, 1.0) * 15
    score += min(total_chars / 100.0, 1.0) * 15

    # Generic structure is a modest bonus, not a requirement. Academic
    # vocabulary gets only a smaller secondary bonus for regression stability.
    score += min(structure_hits / 5.0, 1.0) * 7
    score += min(academic_ratio * 2.0, 1.0) * 3

    if symbol_ratio > 0.3:
        score -= 25
        details.append(
            f"High proportion of non-alphanumeric symbols ({symbol_ratio:.0%})."
        )
    if has_repeated_run:
        score -= 20
        details.append("Suspicious repeated-character run detected.")
    if word_count < 3 and total_chars < 15:
        score -= 15
        details.append("Unusually short OCR output.")
    if structure_hits:
        details.append(
            f"Detected {structure_hits} generic document-structure signal(s)."
        )

    score = max(0.0, min(100.0, score))

    if score >= 65:
        label = "good"
    elif score >= 35:
        label = "fair"
    elif score > 0:
        label = "poor"
    else:
        label = "empty"

    return QualityAssessment(
        score=round(score, 2),
        label=label,
        word_count=word_count,
        alpha_ratio=round(alpha_ratio, 3),
        details=details,
    )


def _compute_confidence(ocr_data: dict) -> Optional[float]:
    """
    Compute an average confidence score from Tesseract's word-level
    `image_to_data` output.

    Args:
        ocr_data: The dict returned by `pytesseract.image_to_data(...,
            output_type=Output.DICT)`.

    Returns:
        Average confidence (0-100) across recognized words, or None if
        no valid confidence values were reported (e.g. blank page).
    """
    valid_scores: List[float] = []
    for raw_conf in ocr_data.get("conf", []):
        try:
            score = float(raw_conf)
        except (TypeError, ValueError):
            continue
        if score >= 0:
            valid_scores.append(score)

    if not valid_scores:
        return None
    return round(sum(valid_scores) / len(valid_scores), 2)


# --------------------------------------------------------------------------- #
# Engine: Tesseract (primary, fast, printed text)
# --------------------------------------------------------------------------- #

def ocr_image(
    image_path: Path,
    lang: str = DEFAULT_OCR_LANGUAGE,
    timeout: int = OCR_TIMEOUT_SECONDS,
) -> Tuple[str, Optional[float]]:
    """
    Run Tesseract OCR on a single image file and return its text and
    confidence score.

    This is the module's original public single-file entry point and
    remains fully backward compatible. Internally, the multi-engine
    pipeline (`run_ocr`) uses `_ocr_array_with_tesseract` on in-memory
    image variants instead, so it does not need to write each variant
    back to disk first.

    Args:
        image_path: Path to the (already preprocessed) image to OCR.
        lang: Tesseract language code(s), e.g. "eng" or "eng+hin".
        timeout: Maximum seconds to allow Tesseract to run before
            treating it as failed.

    Returns:
        A tuple of (extracted_text, average_confidence). Confidence is
        None if it could not be determined (e.g. no recognizable text).

    Raises:
        OCRImageError: If the image is missing, invalid, or corrupted.
        TesseractNotFoundError: If the Tesseract binary is unavailable.
        OCRDependencyError: If pytesseract is not installed.
        OCRProcessingError: If Tesseract fails, errors out, or times out.
    """
    validate_image_path(image_path)
    pytesseract = _configure_pytesseract()

    try:
        with Image.open(image_path) as img:
            img.load()
            text = pytesseract.image_to_string(img, lang=lang, timeout=timeout)
            data = pytesseract.image_to_data(
                img, lang=lang, timeout=timeout, output_type=pytesseract.Output.DICT
            )
    except pytesseract.pytesseract.TesseractNotFoundError as exc:
        raise TesseractNotFoundError(
            "The configured Tesseract executable could not be run."
        ) from exc
    except RuntimeError as exc:
        # pytesseract raises RuntimeError when the underlying process
        # exceeds the configured timeout.
        raise OCRProcessingError(
            f"OCR timed out after {timeout}s while processing: {image_path.name}"
        ) from exc
    except pytesseract.TesseractError as exc:
        raise OCRProcessingError(
            f"Tesseract failed to process image '{image_path.name}': {exc}"
        ) from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise OCRImageError(
            f"Failed to open image for OCR: {image_path.name}"
        ) from exc

    confidence = _compute_confidence(data)
    return text.strip(), confidence


def _ocr_array_with_tesseract(
    image_array: np.ndarray,
    lang: str,
    timeout: int,
    config: str = "",
) -> Tuple[str, Optional[float]]:
    """
    Run Tesseract on an in-memory image array (a preprocessing variant
    that was never written to disk).

    Args:
        config: Extra Tesseract config flags, e.g. "--psm 6" to override
            the default automatic page-segmentation mode. Useful for
            certificates, forms, stamps, or other sparse/irregular
            layouts that the default PSM 3 (fully automatic) mode
            sometimes misreads or drops entirely.

    Raises:
        TesseractNotFoundError: If the Tesseract binary is unavailable.
        OCRDependencyError: If pytesseract is not installed.
        OCRProcessingError: If Tesseract fails, errors out, or times out.
    """
    pytesseract = _configure_pytesseract()

    try:
        pil_image = Image.fromarray(image_array)
        text = pytesseract.image_to_string(
            pil_image, lang=lang, timeout=timeout, config=config
        )
        data = pytesseract.image_to_data(
            pil_image,
            lang=lang,
            timeout=timeout,
            config=config,
            output_type=pytesseract.Output.DICT,
        )
    except pytesseract.pytesseract.TesseractNotFoundError as exc:
        raise TesseractNotFoundError(
            "The configured Tesseract executable could not be run."
        ) from exc
    except RuntimeError as exc:
        raise OCRProcessingError(
            f"OCR timed out after {timeout}s while processing an image variant."
        ) from exc
    except pytesseract.TesseractError as exc:
        raise OCRProcessingError(
            f"Tesseract failed to process an image variant: {exc}"
        ) from exc

    confidence = _compute_confidence(data)
    return text.strip(), confidence


# --------------------------------------------------------------------------- #
# Engine: EasyOCR (secondary, printed documents / certificates / logos)
# --------------------------------------------------------------------------- #
#
# Why EasyOCR: it is open-source, actively maintained, installs with a
# single `pip install`, requires no paid API or internet access after
# the first model download, runs on CPU-only Windows machines, and uses
# GPU automatically when one is available. Its deep-learning text
# detector generally copes much better than Tesseract with certificates,
# logos, stamps, unusual fonts, small text, and uneven layouts.

_easyocr_reader_cache: Dict[Tuple[str, ...], object] = {}


def _get_easyocr_reader(lang_list: Tuple[str, ...]):
    """
    Lazily import EasyOCR and construct (or return a cached) Reader for
    the given languages. Models are downloaded once and cached locally
    by EasyOCR itself (~/.EasyOCR/model) on first use.

    Raises:
        OCRDependencyError: If the 'easyocr' package is not installed.
        OCRModelError: If the model fails to load/download.
    """
    if lang_list in _easyocr_reader_cache:
        return _easyocr_reader_cache[lang_list]

    try:
        import easyocr
    except ImportError as exc:
        raise OCRDependencyError(
            "The 'easyocr' package is required for the secondary printed-"
            "document OCR strategy (certificates, logos, unusual fonts, "
            "low-quality scans). Install it via 'pip install easyocr'."
        ) from exc

    gpu_available = False
    try:
        import torch
        gpu_available = torch.cuda.is_available()
    except ImportError:
        gpu_available = False

    try:
        reader = easyocr.Reader(list(lang_list), gpu=gpu_available, verbose=False)
    except Exception as exc:  # pragma: no cover - depends on network/model state
        raise OCRModelError(
            f"Failed to load/download the EasyOCR model for languages "
            f"{lang_list}: {exc}"
        ) from exc

    _easyocr_reader_cache[lang_list] = reader
    logger.info(
        "Loaded EasyOCR reader for languages=%s (gpu=%s).", lang_list, gpu_available
    )
    return reader


def _ocr_with_easyocr(
    image_array: np.ndarray,
    lang_list: Tuple[str, ...] = ("en",),
) -> Tuple[str, Optional[float]]:
    """
    Run EasyOCR on an in-memory image array.

    Returns:
        (text, approximate_confidence). Confidence is EasyOCR's own
        per-detection recognizer score averaged and scaled to 0-100; it
        is NOT calibrated the same way as Tesseract's confidence and
        must be treated as approximate only.

    Raises:
        OCRDependencyError: If 'easyocr' is not installed.
        OCRModelError: If the model fails to load or inference crashes.
        OCRProcessingError: If the call times out.
    """
    reader = _get_easyocr_reader(lang_list)

    def _run():
        return reader.readtext(image_array, detail=1, paragraph=False)

    try:
        detections = _run_with_timeout(_run, EASYOCR_TIMEOUT_SECONDS)
    except OCRProcessingError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise OCRModelError(f"EasyOCR inference failed: {exc}") from exc

    if not detections:
        return "", None

    # EasyOCR does not guarantee reading order; approximate it by
    # sorting top-to-bottom (bucketed, to tolerate slight skew) then
    # left-to-right.
    def _sort_key(item):
        bbox = item[0]
        top_left = bbox[0]
        return (round(top_left[1] / 15.0), top_left[0])

    detections = sorted(detections, key=_sort_key)

    lines = [det[1] for det in detections if det[1] and det[1].strip()]
    scores = [float(det[2]) for det in detections if det[1] and det[1].strip()]

    text = "\n".join(lines).strip()
    confidence = round(sum(scores) / len(scores) * 100, 2) if scores else None
    return text, confidence


# --------------------------------------------------------------------------- #
# Engine: TrOCR (handwriting OCR, last-resort fallback)
# --------------------------------------------------------------------------- #
#
# Why TrOCR: `microsoft/trocr-base-handwritten` is a well-established,
# open-source, locally runnable transformer OCR model specifically fine-
# tuned on handwritten text. It requires only `transformers` + `torch`
# (+ `sentencepiece`), runs on CPU (slowly) or GPU (fast) with no paid
# API, and the weights are downloaded once and cached by Hugging Face
# Hub thereafter.

_trocr_cache: Dict[str, object] = {}


def _get_trocr_model():
    """
    Lazily import transformers/torch and load (or return cached)
    TrOCR processor + model + device.

    Raises:
        OCRDependencyError: If 'transformers'/'torch' are not installed.
        OCRModelError: If the model fails to download/load.
    """
    if _trocr_cache:
        return _trocr_cache["processor"], _trocr_cache["model"], _trocr_cache["device"]

    try:
        import torch
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    except ImportError as exc:
        raise OCRDependencyError(
            "The 'torch' and 'transformers' packages (plus 'sentencepiece') "
            "are required for handwriting OCR. Install them via "
            "'pip install torch transformers sentencepiece'."
        ) from exc

    try:
        processor = TrOCRProcessor.from_pretrained(TROCR_MODEL_NAME)
        model = VisionEncoderDecoderModel.from_pretrained(TROCR_MODEL_NAME)
    except Exception as exc:  # pragma: no cover - depends on network/model state
        raise OCRModelError(
            f"Failed to download/load the TrOCR handwriting model "
            f"('{TROCR_MODEL_NAME}'): {exc}"
        ) from exc

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()

    _trocr_cache["processor"] = processor
    _trocr_cache["model"] = model
    _trocr_cache["device"] = device
    logger.info("Loaded TrOCR handwriting model on device=%s.", device)
    return processor, model, device


def _trocr_generate(
    processor,
    model,
    device: str,
    pil_images: List["Image.Image"],
    batch_size: int = 8,
) -> Tuple[List[str], List[Optional[float]]]:
    """
    Run TrOCR generation over a list of already-cropped line images and
    return, for each one, the decoded text plus an *approximate*
    confidence derived from the model's own token probabilities (the
    mean of each generated token's top softmax probability, scaled to
    0-100). TrOCR has no calibrated confidence output, so this is a
    rough signal only -- primarily useful for picking the best
    candidate among several OCR attempts, not as an absolute quality
    guarantee. Must be called from inside a worker thread (via
    `_run_with_timeout`) since it imports/uses `torch` directly.
    """
    import torch

    texts: List[str] = []
    confidences: List[Optional[float]] = []

    for start in range(0, len(pil_images), batch_size):
        batch = pil_images[start : start + batch_size]
        pixel_values = processor(images=batch, return_tensors="pt").pixel_values
        pixel_values = pixel_values.to(device)
        with torch.no_grad():
            outputs = model.generate(
                pixel_values,
                max_length=256,
                output_scores=True,
                return_dict_in_generate=True,
            )
        decoded = processor.batch_decode(outputs.sequences, skip_special_tokens=True)
        texts.extend(decoded)

        try:
            if outputs.scores:
                # outputs.scores: tuple(len=generated_len) of (batch, vocab) logits.
                step_probs = [
                    torch.softmax(step, dim=-1).max(dim=-1).values for step in outputs.scores
                ]
                token_probs = torch.stack(step_probs, dim=1)  # (batch, generated_len)
                seq_conf = (token_probs.mean(dim=1) * 100).tolist()
                confidences.extend(round(float(c), 2) for c in seq_conf)
            else:
                confidences.extend([None] * len(batch))
        except Exception:  # pragma: no cover - confidence is best-effort only
            confidences.extend([None] * len(batch))

    return texts, confidences


def _ocr_with_trocr(image_array: np.ndarray) -> Tuple[str, Optional[float]]:
    """
    Run the TrOCR handwriting model on an entire in-memory image array
    in one shot (no line segmentation).

    This is a fallback only: TrOCR (`microsoft/trocr-base-handwritten`)
    is trained to transcribe a single line of text, so handing it a
    whole page tends to produce truncated or garbled output on
    anything but a single short line. Prefer `_ocr_with_trocr_lines`,
    which detects individual lines first; this whole-image path is
    used only when line detection itself is unavailable or finds
    nothing.

    Returns:
        (text, confidence). Confidence is an approximate, uncalibrated
        signal derived from the model's token probabilities (see
        `_trocr_generate`); it should be treated as a rough ranking
        signal, not an absolute score.

    Raises:
        OCRDependencyError: If 'torch'/'transformers' are not installed.
        OCRModelError: If the model fails to load or inference crashes.
        OCRImageError: If the image cannot be prepared.
        OCRProcessingError: If the call times out.
    """
    processor, model, device = _get_trocr_model()

    try:
        pil_image = Image.fromarray(image_array).convert("RGB")
    except Exception as exc:
        raise OCRImageError(f"Failed to prepare image for TrOCR: {exc}") from exc

    def _run():
        return _trocr_generate(processor, model, device, [pil_image])

    try:
        texts, confidences = _run_with_timeout(_run, TROCR_TIMEOUT_SECONDS)
    except OCRProcessingError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise OCRModelError(f"TrOCR inference failed: {exc}") from exc

    text = texts[0].strip() if texts else ""
    confidence = confidences[0] if confidences else None
    return text, confidence


# Extra padding (pixels) added around each detected line box before
# cropping for TrOCR, so ascenders/descenders and slightly-loose
# detection boxes aren't clipped.
_TROCR_LINE_PADDING_PX = 6

# Safety cap on how many line crops a single page will run through
# TrOCR for, so a mis-detected page (hundreds of tiny boxes) cannot
# stall processing.
_TROCR_MAX_LINES = 150

# Mixed printed/handwritten documents need a second handwriting pass even when
# the printed page itself scores "good". Only suspicious regions are sent to
# TrOCR so ordinary documents do not become unnecessarily slow.
_TROCR_MIXED_MAX_LINES = 24
_TROCR_SUSPECT_CONFIDENCE = 68.0
_TROCR_LINE_MIN_HEIGHT_PX = 8


def _detect_text_lines(
    image_array: np.ndarray, lang_list: Tuple[str, ...]
) -> List[Tuple[int, int, int, int]]:
    """
    Use EasyOCR's text *detector* (not its recognizer) to find line/word
    bounding boxes in an image.

    TrOCR needs this: it is a single-line recognizer with no built-in
    layout analysis, so feeding it a whole page is the main reason
    handwriting extraction comes back empty or scrambled. Reusing
    EasyOCR's detector here (rather than its recognizer, which is
    weaker on handwriting) gives TrOCR the line segmentation it needs
    while still letting TrOCR do the actual handwriting recognition.

    Returns:
        (x_min, y_min, x_max, y_max) boxes, sorted top-to-bottom then
        left-to-right (bucketed to tolerate slight skew/rotation).
    """
    reader = _get_easyocr_reader(lang_list)

    def _run():
        return reader.detect(image_array)

    horizontal_list, free_list = _run_with_timeout(_run, EASYOCR_TIMEOUT_SECONDS)

    boxes: List[Tuple[int, int, int, int]] = []

    # detect() returns one list per input image; we always pass a
    # single image, so index 0 if present.
    h_boxes = horizontal_list[0] if horizontal_list else []
    for box in h_boxes:
        x_min, x_max, y_min, y_max = box
        boxes.append((int(x_min), int(y_min), int(x_max), int(y_max)))

    # "free" boxes are rotated/skewed quads; use their axis-aligned
    # bounding box, which is good enough for a crop.
    f_boxes = free_list[0] if free_list else []
    for quad in f_boxes:
        xs = [pt[0] for pt in quad]
        ys = [pt[1] for pt in quad]
        boxes.append((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))))

    def _sort_key(box: Tuple[int, int, int, int]) -> Tuple[float, int]:
        x_min, y_min, _, _ = box
        return (round(y_min / 15.0), x_min)

    boxes.sort(key=_sort_key)
    return boxes[:_TROCR_MAX_LINES]


def _detect_text_lines_cv2(image_array: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """Lightweight line detector that does not require an OCR package.

    Useful for fully handwritten pages where Tesseract may return no boxes and
    EasyOCR may not be installed. Horizontal morphology groups nearby ink
    strokes into line-sized regions for TrOCR.
    """
    gray = image_array if len(image_array.shape) == 2 else cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
    if gray.size == 0:
        return []
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 11
    )
    width = max(15, gray.shape[1] // 35)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (width, 3))
    joined = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    joined = cv2.dilate(joined, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3)), iterations=1)
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    page_area = gray.shape[0] * gray.shape[1]
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if w < 30 or h < 8 or area < page_area * 0.00005:
            continue
        if w > gray.shape[1] * 0.98 and h > gray.shape[0] * 0.25:
            continue
        boxes.append((x, y, x + w, y + h))
    boxes.sort(key=lambda b: (b[1], b[0]))
    return boxes[:_TROCR_MAX_LINES]


def _detect_text_lines_tesseract(
    image_array: np.ndarray,
    lang: str = "eng",
) -> List[Tuple[int, int, int, int]]:
    """Detect likely text-line regions with Tesseract when EasyOCR is unavailable."""
    pytesseract = _configure_pytesseract()
    try:
        data = pytesseract.image_to_data(
            Image.fromarray(image_array), lang=lang, config="--psm 11",
            timeout=OCR_TIMEOUT_SECONDS, output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:
        raise OCRProcessingError(f"Tesseract line detection failed: {exc}") from exc

    words = []
    for i, raw in enumerate(data.get("text", [])):
        txt = str(raw or "").strip()
        if not txt:
            continue
        try:
            x = int(data["left"][i]); y = int(data["top"][i])
            w = int(data["width"][i]); h = int(data["height"][i])
            conf = float(data["conf"][i])
        except (TypeError, ValueError, KeyError):
            continue
        if w > 0 and h >= _TROCR_LINE_MIN_HEIGHT_PX:
            words.append((x, y, x + w, y + h, conf))

    if not words:
        return _detect_text_lines_cv2(image_array)
    words.sort(key=lambda b: (b[1], b[0]))
    groups = []
    for box in words:
        x0, y0, x1, y1, conf = box
        cy = (y0 + y1) / 2.0
        placed = False
        for group in reversed(groups[-4:]):
            gy0 = min(b[1] for b in group); gy1 = max(b[3] for b in group)
            gcy = (gy0 + gy1) / 2.0
            if abs(cy - gcy) <= max(12.0, 0.65 * max(y1-y0, gy1-gy0)):
                group.append(box); placed = True; break
        if not placed:
            groups.append([box])

    boxes = []
    for group in groups:
        boxes.append((min(b[0] for b in group), min(b[1] for b in group),
                      max(b[2] for b in group), max(b[3] for b in group)))
    boxes.sort(key=lambda b: (round(b[1] / 15.0), b[0]))
    return boxes[:_TROCR_MAX_LINES]


def _ocr_with_trocr_mixed_page(
    image_array: np.ndarray,
    easyocr_lang_list: Tuple[str, ...] = ("en",),
    tesseract_lang: str = "eng",
) -> Tuple[str, Optional[float]]:
    """Recover suspicious handwritten regions without replacing good printed OCR."""
    try:
        boxes = _detect_text_lines(image_array, easyocr_lang_list)
    except Exception:
        boxes = _detect_text_lines_tesseract(image_array, tesseract_lang)
    if not boxes:
        boxes = _detect_text_lines_cv2(image_array)
    if not boxes:
        return "", None

    pytesseract = _configure_pytesseract()
    height, width = image_array.shape[:2]
    suspects = []
    for bx in boxes:
        x0, y0, x1, y1 = bx
        x0 = max(0, x0 - 8); y0 = max(0, y0 - 8)
        x1 = min(width, x1 + 8); y1 = min(height, y1 + 8)
        crop = image_array[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        try:
            pil = Image.fromarray(crop)
            txt = pytesseract.image_to_string(
                pil, lang=tesseract_lang, config="--psm 7", timeout=10
            ).strip()
            data = pytesseract.image_to_data(
                pil, lang=tesseract_lang, config="--psm 7", timeout=10,
                output_type=pytesseract.Output.DICT,
            )
            conf = _compute_confidence(data)
        except Exception:
            txt, conf = "", None
        suspicious = (
            not txt or conf is None or conf < _TROCR_SUSPECT_CONFIDENCE or
            bool(re.search(r"[^A-Za-z0-9 .,;:'\"!?()\-/]", txt))
        )
        if suspicious:
            suspects.append((y0, x0, crop, conf))

    suspects.sort(key=lambda item: (item[3] if item[3] is not None else -1.0, item[0], item[1]))
    suspects = suspects[:_TROCR_MIXED_MAX_LINES]
    suspects.sort(key=lambda item: (round(item[0] / 15.0), item[1]))
    if not suspects:
        return "", None

    processor, model, device = _get_trocr_model()
    line_images = [Image.fromarray(item[2]).convert("RGB") for item in suspects]
    def _run():
        return _trocr_generate(processor, model, device, line_images)
    try:
        texts, confidences = _run_with_timeout(_run, TROCR_TIMEOUT_SECONDS)
    except OCRProcessingError:
        raise
    except Exception as exc:
        raise OCRModelError(f"Mixed handwriting TrOCR inference failed: {exc}") from exc

    recovered = []
    valid_conf = []
    for txt, conf in zip(texts, confidences):
        txt = (txt or "").strip()
        if not txt or not re.search(r"[A-Za-z]{2,}", txt):
            continue
        if conf is not None and conf < 25:
            continue
        recovered.append(txt)
        if conf is not None:
            valid_conf.append(conf)
    return "\n".join(recovered).strip(), (round(sum(valid_conf)/len(valid_conf), 2) if valid_conf else None)


def _ocr_with_trocr_lines(
    image_array: np.ndarray,
    easyocr_lang_list: Tuple[str, ...] = ("en",),
) -> Tuple[str, Optional[float]]:
    """
    Run TrOCR handwriting recognition line-by-line rather than on the
    whole page at once -- this is the main lever for getting usable
    text out of genuinely handwritten pages.

    Detects individual text-line boxes first (`_detect_text_lines`),
    crops each one, runs TrOCR on every crop, and reassembles the
    results in reading order. Falls back to whole-page TrOCR
    (`_ocr_with_trocr`) if line detection is unavailable, fails, or
    finds nothing to crop.

    Returns:
        (text, confidence) -- confidence is the mean of each line's
        approximate, uncalibrated TrOCR confidence (see
        `_trocr_generate`), or None if no line produced one.

    Raises:
        OCRDependencyError: If a required package is not installed.
        OCRModelError: If a model fails to load or inference crashes.
        OCRProcessingError: If a call times out.
    """
    try:
        boxes = _detect_text_lines(image_array, easyocr_lang_list)
    except (OCRDependencyError, OCRModelError, OCRProcessingError) as exc:
        logger.debug(
            "Line detection for TrOCR unavailable, falling back to whole-page: %s",
            exc,
        )
        return _ocr_with_trocr(image_array)

    if not boxes:
        boxes = _detect_text_lines_cv2(image_array)
    if not boxes:
        return _ocr_with_trocr(image_array)

    height, width = image_array.shape[:2]
    line_images: List["Image.Image"] = []
    for x_min, y_min, x_max, y_max in boxes:
        x0 = max(0, x_min - _TROCR_LINE_PADDING_PX)
        y0 = max(0, y_min - _TROCR_LINE_PADDING_PX)
        x1 = min(width, x_max + _TROCR_LINE_PADDING_PX)
        y1 = min(height, y_max + _TROCR_LINE_PADDING_PX)
        if x1 <= x0 or y1 <= y0:
            continue
        crop = image_array[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        line_images.append(Image.fromarray(crop).convert("RGB"))

    if not line_images:
        return _ocr_with_trocr(image_array)

    processor, model, device = _get_trocr_model()

    def _run():
        return _trocr_generate(processor, model, device, line_images)

    try:
        texts, confidences = _run_with_timeout(_run, TROCR_TIMEOUT_SECONDS)
    except OCRProcessingError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise OCRModelError(f"TrOCR line-wise inference failed: {exc}") from exc

    lines = [t.strip() for t in texts if t and t.strip()]
    text = "\n".join(lines)

    valid_confidences = [c for c in confidences if c is not None]
    confidence = (
        round(sum(valid_confidences) / len(valid_confidences), 2)
        if valid_confidences
        else None
    )
    return text, confidence


# --------------------------------------------------------------------------- #
# Image preprocessing variants (OCR-stage-local, non-destructive)
# --------------------------------------------------------------------------- #

def _sharpen_for_ocr(gray: np.ndarray) -> np.ndarray:
    """
    Produce a mildly sharpened, contrast-boosted variant of a grayscale
    page image, aimed at blurry photo-scans and faint/low-contrast
    handwriting. Uses CLAHE (localized contrast boosting, which copes
    better than a single global contrast stretch with unevenly-lit
    photos) followed by a light unsharp mask. Deliberately gentler than
    binarization so it never destroys thin pencil strokes or soft
    stamp/signature detail.
    """
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    contrast_boosted = clahe.apply(gray)
    blurred = cv2.GaussianBlur(contrast_boosted, (0, 0), sigmaX=3)
    sharpened = cv2.addWeighted(contrast_boosted, 1.5, blurred, -0.5, 0)
    return sharpened


def _build_page_variants(base_gray: np.ndarray) -> "OrderedDict[str, np.ndarray]":
    """
    Build a small set of OCR-friendly variants of an already-preprocessed
    page image, without touching the original file on disk or modifying
    `preprocessing.py`.

    Variants:
        - "contrast_enhanced": the image exactly as produced by
          `preprocessing.py` (grayscale, denoised, contrast-enhanced,
          deskewed). Used as-is for Tesseract's first pass, EasyOCR, and
          TrOCR (binarizing would destroy handwriting strokes and soft
          detail like stamps/signatures, so this variant is intentionally
          never thresholded).
        - "adaptive_threshold": a binarized version, reusing
          `preprocessing.binarize_image`. Helpful for dense, clean printed
          text and some low-contrast scans, but never used for handwriting.
        - "upscaled": only generated when the image is small on its
          longest side, to help with small print / tiny stamp text.
        - "sharpened": contrast-boosted (CLAHE) + mildly unsharp-masked
          version of the grayscale image. Helps blurry phone-photo
          scans and faint/low-contrast handwriting (pencil, worn ink,
          poor lighting) without the harsh, stroke-destroying effect of
          binarization -- so, like "contrast_enhanced", it is safe to
          use for handwriting as well as print.

    Args:
        base_gray: The single-channel image already produced by
            `preprocessing.py` for this page.

    Returns:
        An ordered mapping of variant name -> image array.
    """
    variants: "OrderedDict[str, np.ndarray]" = OrderedDict()
    variants["contrast_enhanced"] = base_gray

    try:
        variants["adaptive_threshold"] = binarize_image(base_gray)
    except DocumentPreprocessingError as exc:
        logger.debug("Skipping binarized variant: %s", exc)

    try:
        variants["sharpened"] = _sharpen_for_ocr(base_gray)
    except cv2.error as exc:  # pragma: no cover - defensive
        logger.debug("Skipping sharpened variant: %s", exc)

    height, width = base_gray.shape[:2]
    longest_side = max(height, width)
    if longest_side and longest_side < _UPSCALE_THRESHOLD_PX:
        scale = _UPSCALE_TARGET_PX / float(longest_side)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        try:
            variants["upscaled"] = cv2.resize(
                base_gray, new_size, interpolation=cv2.INTER_CUBIC
            )
        except cv2.error as exc:  # pragma: no cover - defensive
            logger.debug("Skipping upscaled variant: %s", exc)

    return variants


def _normalize_lang_lists(lang: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """
    Turn a Tesseract-style language string (e.g. "eng+hin") into both a
    Tesseract language list and a best-effort EasyOCR equivalent.

    EasyOCR uses different language codes than Tesseract (e.g. "en"
    instead of "eng"); only the common case of English is mapped
    explicitly, everything else is passed through as-is so additional
    languages still "just work" if the codes happen to coincide, and
    otherwise EasyOCR will raise a clear error of its own.
    """
    tesseract_codes = tuple(
        part.strip() for part in lang.split("+") if part.strip()
    ) or ("eng",)

    _tess_to_easyocr = {"eng": "en"}
    easyocr_codes = tuple(_tess_to_easyocr.get(code, code) for code in tesseract_codes)
    return tesseract_codes, easyocr_codes


# --------------------------------------------------------------------------- #
# Text-source helpers (non-OCR paths)
# --------------------------------------------------------------------------- #

def _read_extracted_text_file(path: Path) -> str:
    """
    Read a UTF-8 text file produced by the preprocessing stage.

    Raises:
        OCRProcessingError: If the file cannot be read or decoded.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise OCRProcessingError(
            f"Failed to read preprocessed text file: {path}"
        ) from exc


def _get_pdf_native_page_text(original_pdf_path: Path, page_number: int) -> str:
    """
    Re-read the exact text of a single PDF page directly from the source
    PDF using PyMuPDF.

    This is used instead of the preprocessing stage's combined text file
    because that file concatenates all text-based pages together without
    per-page boundaries, whereas OCR output must preserve page order and
    per-page text explicitly.

    Args:
        original_pdf_path: Path to the original, unmodified uploaded PDF.
        page_number: 1-indexed page number to read.

    Returns:
        The extracted text for that page (may be an empty string).

    Raises:
        OCRProcessingError: If PyMuPDF is unavailable, the PDF cannot be
            opened, or the page index is out of range.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise OCRProcessingError(
            "PyMuPDF ('pymupdf') is required to re-read native PDF page "
            "text. Install it via 'pip install pymupdf'."
        ) from exc

    try:
        document = fitz.open(str(original_pdf_path))
    except Exception as exc:
        raise OCRProcessingError(
            f"Failed to open PDF for text retrieval: {original_pdf_path.name}"
        ) from exc

    try:
        if page_number < 1 or page_number > document.page_count:
            raise OCRProcessingError(
                f"Page {page_number} is out of range for PDF: "
                f"{original_pdf_path.name}"
            )
        page = document.load_page(page_number - 1)
        text = page.get_text("text") or ""
    except OCRProcessingError:
        raise
    except Exception as exc:
        raise OCRProcessingError(
            f"Failed to extract text from PDF page {page_number}: {exc}"
        ) from exc
    finally:
        document.close()

    return text


# --------------------------------------------------------------------------- #
# Per-page processing
# --------------------------------------------------------------------------- #

def _process_text_page(
    page: PageMetadata,
    document_type: DocumentType,
    original_document_path: Optional[Path],
    extracted_text_path: Optional[Path],
    warnings: List[str],
) -> PageOCRResult:
    """
    Build a `PageOCRResult` for a page that preprocessing already marked
    as containing usable extracted text (no OCR necessary).
    """
    text = ""

    if document_type == DocumentType.PDF:
        if original_document_path is not None:
            try:
                text = _get_pdf_native_page_text(original_document_path, page.page_number)
            except OCRProcessingError as exc:
                logger.warning("%s", exc)
                warnings.append(
                    f"Falling back to truncated preview text for page "
                    f"{page.page_number}: {exc}"
                )
                text = page.extracted_text_preview or ""
        else:
            warnings.append(
                f"Original PDF path not provided; using truncated preview "
                f"text for page {page.page_number}."
            )
            text = page.extracted_text_preview or ""
    else:
        # DOCX, or DOC already converted to DOCX by preprocessing: a
        # single logical page whose full text preprocessing already
        # wrote out in full.
        if extracted_text_path is not None:
            text = _read_extracted_text_file(extracted_text_path)
        else:
            text = page.extracted_text_preview or ""

    text = text.strip()
    quality = assess_ocr_quality(text) if text else None

    return PageOCRResult(
        page_number=page.page_number,
        text=text,
        confidence=None,
        source_image_path=None,
        ocr_applied=False,
        text_extracted=bool(text),
        ocr_engine=(OCREngine.NATIVE_TEXT.value if text else OCREngine.NONE.value),
        quality_score=(quality.score if quality else None),
        quality_label=(quality.label if quality else "empty"),
        confidence_approximate=False,
        engines_attempted=["native_text"] if text else [],
    )


def _document_signal_score(text: str) -> float:
    """Add a small document-generic structure bonus to OCR candidate ranking.

    The bonus is intentionally domain agnostic. It rewards useful evidence
    such as labels, dates, identifiers, contact details, organizations,
    signatures, addresses, references, and amounts without requiring any
    particular document family.
    """
    lowered = (text or "").lower()
    signals = (
        r"\bdate\b|\bissued?\b|\bexpiry\b|\bexpires?\b",
        r"\bname\b|\bapplicant\b|\bholder\b|\brecipient\b",
        r"\baddress\b|\broad\b|\bstreet\b|\bavenue\b|\bsector\b|\bzip\b|\bpostal\b",
        r"\b(?:organization|organisation|company|department|authority|employer)\b",
        r"\b(?:signature|signed|authorized|authorised)\b",
        r"\b(?:reference|ref|identifier|id|account|invoice|document)\b",
        r"\b(?:amount|total|balance|due|price|fee|salary)\b",
        r"\b(?:email|phone|telephone|mobile|www\.|https?://)\b",
        r"\b(?:passport|license|licence|identity|form|statement|report|agreement)\b",
        r"\b\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,4})?\b|\b(?:19|20)\d{2}\b",
        r"\b[a-z]{2,}\d[a-z0-9_-]{2,}\b",
    )
    hits = sum(
        bool(re.search(pattern, lowered, re.IGNORECASE))
        for pattern in signals
    )
    return min(15.0, hits * 1.35)


def _candidate_rank(candidate: dict) -> float:
    q = candidate["quality"]
    return q.score + _document_signal_score(candidate["text"])



def _get_paddleocr(lang: str = DEFAULT_OCR_LANGUAGE):
    """Lazy-load a PP-OCRv5 PaddleOCR pipeline."""
    cache_key = lang or DEFAULT_OCR_LANGUAGE
    if cache_key in _paddleocr_cache:
        return _paddleocr_cache[cache_key]

    try:
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise OCRDependencyError(
            "PaddleOCR is required for the secondary scanned/handwriting OCR "
            "path. Install the PaddleOCR/PaddlePaddle packages first."
        ) from exc

    # Disable MKLDNN to avoid the CPU backend issue seen on some Windows
    # installations. This mirrors the known-good configuration.
    os.environ.setdefault("FLAGS_use_mkldnn", "0")

    try:
        try:
            pipeline = PaddleOCR(
                text_detection_model_name=PADDLEOCR_DET_MODEL,
                text_recognition_model_name=PADDLEOCR_REC_MODEL,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
                enable_mkldnn=False,
            )
        except TypeError:
            # Compatibility fallback for PaddleOCR releases that expose
            # fewer constructor arguments.
            pipeline = PaddleOCR(
                lang="en",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
            )
    except Exception as exc:
        raise OCRModelError(f"Failed to initialize PaddleOCR: {exc}") from exc

    _paddleocr_cache[cache_key] = pipeline
    return pipeline


def _normalise_paddle_result(result) -> Optional[dict]:
    """Convert one PaddleOCR result object into a plain dictionary."""
    try:
        data = result.json if hasattr(result, "json") else result
        if callable(data):
            data = data()
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    if isinstance(data.get("res"), dict):
        data = data["res"]

    return data


def _ocr_with_paddleocr(image_path: Path, lang: str) -> Tuple[str, Optional[float]]:
    """
    Run PP-OCRv5 on the supplied image path.

    The original image is deliberately accepted here. This is important for
    handwriting and photographed documents where preprocessing may remove
    thin strokes or subtle layout information.
    """
    pipeline = _get_paddleocr(lang)

    try:
        results = pipeline.predict(str(image_path))
    except Exception as exc:
        raise OCRModelError(f"PaddleOCR inference failed: {exc}") from exc

    texts: List[str] = []
    scores: List[float] = []

    try:
        iterable = list(results)
    except Exception as exc:
        raise OCRProcessingError(f"Could not read PaddleOCR results: {exc}") from exc

    for result in iterable:
        data = _normalise_paddle_result(result)
        if not data:
            continue

        rec_texts = data.get("rec_texts", []) or []
        rec_scores = data.get("rec_scores", []) or []

        for i, value in enumerate(rec_texts):
            value = str(value).strip()
            if not value:
                continue
            texts.append(value)
            if i < len(rec_scores):
                try:
                    scores.append(float(rec_scores[i]))
                except (TypeError, ValueError):
                    pass

    text = "\n".join(texts).strip()
    confidence = (sum(scores) / len(scores) * 100.0) if scores else None
    return text, round(confidence, 2) if confidence is not None else None


def _get_paddleocr_vl():
    """Lazy-load PaddleOCR-VL for difficult/handwritten document pages."""
    cache_key = PADDLEOCR_VL_VERSION
    if cache_key in _paddleocr_vl_cache:
        return _paddleocr_vl_cache[cache_key]

    try:
        from paddleocr import PaddleOCRVL
    except ImportError as exc:
        raise OCRDependencyError(
            "PaddleOCR-VL is unavailable. Install the PaddleOCR document-parser "
            "extras and PaddlePaddle to enable the handwriting/document fallback."
        ) from exc

    os.environ.setdefault("FLAGS_use_mkldnn", "0")

    try:
        pipeline = PaddleOCRVL(pipeline_version=cache_key)
    except Exception as exc:
        raise OCRModelError(
            f"Failed to initialize PaddleOCR-VL ({cache_key}): {exc}"
        ) from exc

    _paddleocr_vl_cache[cache_key] = pipeline
    return pipeline


def _extract_paddleocr_vl_text(result) -> str:
    """Extract readable text/markdown from one PaddleOCR-VL result."""
    data = result
    try:
        data = result.json if hasattr(result, "json") else result
        if callable(data):
            data = data()
    except Exception:
        data = result

    if isinstance(data, dict):
        if isinstance(data.get("res"), dict):
            data = data["res"]
        for key in ("markdown", "text", "rec_texts"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                lines = [str(x).strip() for x in value if str(x).strip()]
                if lines:
                    return "\n".join(lines)

    # Some PaddleOCR-VL versions expose markdown/text as object attributes.
    for attr in ("markdown", "text"):
        try:
            value = getattr(result, attr)
            if callable(value):
                value = value()
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            pass

    return ""


def _ocr_with_paddleocr_vl(image_path: Path) -> Tuple[str, Optional[float]]:
    """
    Run PaddleOCR-VL on the whole page.

    PaddleOCR-VL is used as a difficult-document/handwriting fallback. It is
    not assigned a fabricated confidence score; its text is evaluated using
    the same engine-independent quality scorer as every other candidate.
    """
    pipeline = _get_paddleocr_vl()

    try:
        results = pipeline.predict(input=str(image_path))
        texts = []
        for result in list(results):
            value = _extract_paddleocr_vl_text(result)
            if value:
                texts.append(value)
    except TypeError:
        try:
            results = pipeline.predict(str(image_path))
            texts = []
            for result in list(results):
                value = _extract_paddleocr_vl_text(result)
                if value:
                    texts.append(value)
        except Exception as exc:
            raise OCRModelError(f"PaddleOCR-VL inference failed: {exc}") from exc
    except Exception as exc:
        raise OCRModelError(f"PaddleOCR-VL inference failed: {exc}") from exc

    text = "\n".join(texts).strip()
    return text, None


def _handwriting_likelihood(
    best_candidate: Optional[dict],
    original_candidate: Optional[dict],
    paddle_candidate: Optional[dict],
) -> float:
    """
    Produce a conservative handwriting-likelihood score from OCR evidence.

    This is deliberately a routing signal, not a claim that a page is
    handwritten. A high score means conventional printed OCR is struggling
    or disagreeing across image representations, so the handwriting/document
    model should get a chance to read the page.
    """
    score = 0.0

    if best_candidate is None:
        score += 0.55
    else:
        label = best_candidate["quality"].label
        if label == "empty":
            score += 0.75
        elif label == "poor":
            score += 0.55
        elif label == "fair":
            score += 0.30

    if original_candidate is not None and best_candidate is not None:
        a = re.sub(r"[^a-z0-9]+", " ", original_candidate["text"].lower()).strip()
        b = re.sub(r"[^a-z0-9]+", " ", best_candidate["text"].lower()).strip()
        if a and b and a != b:
            from difflib import SequenceMatcher
            similarity = SequenceMatcher(None, a, b).ratio()
            if similarity < 0.55:
                score += 0.20
            elif similarity < 0.75:
                score += 0.10

    if paddle_candidate is not None and paddle_candidate["text"].strip():
        # If PaddleOCR found substantially more text than the conventional
        # result, the page deserves the document/handwriting fallback.
        best_len = len((best_candidate or {}).get("text", ""))
        paddle_len = len(paddle_candidate["text"])
        if best_len < 20 and paddle_len > max(30, best_len * 2):
            score += 0.20

    return min(1.0, score)


def _process_image_page(
    page: PageMetadata,
    lang: str,
    warnings: List[str],
    original_document_path: Optional[Path] = None,
) -> PageOCRResult:
    """
    OCR a scanned/image page using multiple representations and engines.

    The original image is always preserved by preprocessing.py. Conventional
    OCR uses the processed image and alternate variants; PP-OCRv5 also gets
    the untouched original image; PaddleOCR-VL is used when OCR evidence
    suggests difficult layout, handwriting, or poor recognition.
    """
    assert page.image_path is not None

    validate_image_path(page.image_path)
    base_gray = cv2.imread(str(page.image_path), cv2.IMREAD_GRAYSCALE)

    if base_gray is None:
        raise OCRImageError(
            f"Could not load preprocessed image for page {page.page_number}: "
            f"{page.image_path}"
        )

    variants = _build_page_variants(base_gray)
    tesseract_langs, _ = _normalize_lang_lists(lang)
    tesseract_lang_str = "+".join(tesseract_langs)

    engines_attempted: List[str] = []
    candidates: List[dict] = []

    def _add_candidate(
        engine: OCREngine,
        variant_name: str,
        text: str,
        confidence: Optional[float],
        approximate: bool,
    ) -> Optional[dict]:
        text = (text or "").strip()
        quality = assess_ocr_quality(text)
        candidate = {
            "engine": engine,
            "variant": variant_name,
            "text": text,
            "confidence": confidence if text else None,
            "confidence_approximate": approximate,
            "quality": quality,
        }
        engines_attempted.append(f"{engine.value}:{variant_name}")
        candidates.append(candidate)
        return candidate

    def _best_so_far() -> Optional[dict]:
        return max(candidates, key=_candidate_rank) if candidates else None

    # ---------------------------------------------------------
    # 1. Tesseract on the processed image
    # ---------------------------------------------------------
    try:
        text_a, conf_a = _ocr_array_with_tesseract(
            variants["contrast_enhanced"],
            tesseract_lang_str,
            OCR_TIMEOUT_SECONDS,
        )
        _add_candidate(
            OCREngine.TESSERACT,
            "contrast_enhanced",
            text_a,
            conf_a,
            False,
        )
    except OCRProcessingError as exc:
        warnings.append(f"Page {page.page_number}: Tesseract primary OCR failed: {exc}")

    # ---------------------------------------------------------
    # 2. Tesseract alternate variants
    # ---------------------------------------------------------
    best = _best_so_far()

    if (best is None or best["quality"].label != "good") and "adaptive_threshold" in variants:
        try:
            text_b, conf_b = _ocr_array_with_tesseract(
                variants["adaptive_threshold"],
                tesseract_lang_str,
                OCR_TIMEOUT_SECONDS,
            )
            _add_candidate(
                OCREngine.TESSERACT,
                "adaptive_threshold",
                text_b,
                conf_b,
                False,
            )
        except OCRProcessingError as exc:
            warnings.append(f"Page {page.page_number}: Tesseract threshold OCR failed: {exc}")

    best = _best_so_far()

    if best is None or best["quality"].label in ("empty", "poor", "fair"):
        for psm in _TESSERACT_PSM_FALLBACKS:
            try:
                text_psm, conf_psm = _ocr_array_with_tesseract(
                    variants["contrast_enhanced"],
                    tesseract_lang_str,
                    OCR_TIMEOUT_SECONDS,
                    config=f"--psm {psm}",
                )
                _add_candidate(
                    OCREngine.TESSERACT,
                    f"contrast_enhanced_psm{psm}",
                    text_psm,
                    conf_psm,
                    False,
                )
            except OCRProcessingError as exc:
                warnings.append(
                    f"Page {page.page_number}: Tesseract PSM {psm} failed: {exc}"
                )

            best = _best_so_far()
            if best is not None and best["quality"].label == "good":
                break

    # ---------------------------------------------------------
    # 3. PP-OCRv5 on the ORIGINAL image
    # ---------------------------------------------------------
    # This is the key integration from the friend's implementation:
    # PaddleOCR gets the untouched page instead of only the processed copy.
    original_path = getattr(page, "original_image_path", None)

    # Backward-compatible fallback for older preprocessing metadata.
    if original_path is None and original_document_path is not None:
        if original_document_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            original_path = original_document_path

    original_candidate = None
    paddle_candidate = None

    if original_path is not None and Path(original_path).exists():
        original_path = Path(original_path)
        try:
            text_p, conf_p = _ocr_with_paddleocr(original_path, lang)
            paddle_candidate = _add_candidate(
                OCREngine.PADDLEOCR,
                "original",
                text_p,
                conf_p,
                True,
            )
        except (OCRDependencyError, OCRModelError, OCRProcessingError) as exc:
            warnings.append(
                f"Page {page.page_number}: PaddleOCR original-image OCR unavailable/failed: {exc}"
            )
    else:
        warnings.append(
            f"Page {page.page_number}: original image unavailable; "
            f"PaddleOCR will use the processed image."
        )
        try:
            text_p, conf_p = _ocr_with_paddleocr(page.image_path, lang)
            paddle_candidate = _add_candidate(
                OCREngine.PADDLEOCR,
                "processed",
                text_p,
                conf_p,
                True,
            )
        except (OCRDependencyError, OCRModelError, OCRProcessingError) as exc:
            warnings.append(
                f"Page {page.page_number}: PaddleOCR processed-image OCR failed: {exc}"
            )

    # ---------------------------------------------------------
    # 4. PaddleOCR on a sharpened/upscaled processed variant if needed
    # ---------------------------------------------------------
    best = _best_so_far()
    if best is None or best["quality"].label in ("empty", "poor", "fair"):
        for variant_name in ("sharpened", "upscaled"):
            if variant_name not in variants:
                continue
            try:
                # Write only this temporary variant; PaddleOCR's public API
                # is path-based.
                temp_path = page.image_path.parent / (
                    f".__paddle_{page.page_number}_{variant_name}.png"
                )
                if not cv2.imwrite(str(temp_path), variants[variant_name]):
                    continue
                try:
                    text_p, conf_p = _ocr_with_paddleocr(temp_path, lang)
                    _add_candidate(
                        OCREngine.PADDLEOCR,
                        variant_name,
                        text_p,
                        conf_p,
                        True,
                    )
                finally:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            except (OCRDependencyError, OCRModelError, OCRProcessingError) as exc:
                warnings.append(
                    f"Page {page.page_number}: PaddleOCR '{variant_name}' failed: {exc}"
                )

            best = _best_so_far()
            if best is not None and best["quality"].label == "good":
                break

    # ---------------------------------------------------------
    # 5. Decide whether difficult-document/handwriting fallback is needed
    # ---------------------------------------------------------
    best = _best_so_far()

    if original_path is not None:
        # Find the original-image Paddle candidate, if one exists.
        original_candidates = [
            c for c in candidates
            if c["engine"] == OCREngine.PADDLEOCR and c["variant"] == "original"
        ]
        if original_candidates:
            original_candidate = original_candidates[-1]

    likelihood = _handwriting_likelihood(
        best,
        original_candidate,
        paddle_candidate,
    )

    # Run VL for:
    #   - poor/empty conventional OCR,
    #   - fair OCR with evidence of disagreement,
    #   - or a high handwriting/difficult-document likelihood.
    should_run_vl = (
        best is None
        or best["quality"].label in ("empty", "poor")
        or likelihood >= 0.50
    )

    if should_run_vl and original_path is not None and Path(original_path).exists():
        try:
            text_vl, conf_vl = _ocr_with_paddleocr_vl(Path(original_path))
            _add_candidate(
                OCREngine.PADDLEOCR_VL,
                "original",
                text_vl,
                conf_vl,
                False,
            )
        except (OCRDependencyError, OCRModelError, OCRProcessingError) as exc:
            warnings.append(
                f"Page {page.page_number}: PaddleOCR-VL fallback unavailable/failed: {exc}"
            )
    elif should_run_vl:
        try:
            text_vl, conf_vl = _ocr_with_paddleocr_vl(page.image_path)
            _add_candidate(
                OCREngine.PADDLEOCR_VL,
                "processed",
                text_vl,
                conf_vl,
                False,
            )
        except (OCRDependencyError, OCRModelError, OCRProcessingError) as exc:
            warnings.append(
                f"Page {page.page_number}: PaddleOCR-VL fallback unavailable/failed: {exc}"
            )

    # ---------------------------------------------------------
    # 6. Select the strongest candidate
    # ---------------------------------------------------------
    best = _best_so_far()

    if best is None:
        warnings.append(
            f"Page {page.page_number}: all OCR engines failed or were unavailable."
        )
        return PageOCRResult(
            page_number=page.page_number,
            text="",
            confidence=None,
            source_image_path=page.image_path,
            ocr_applied=True,
            text_extracted=False,
            ocr_engine=OCREngine.NONE.value,
            quality_score=None,
            quality_label="empty",
            confidence_approximate=False,
            engines_attempted=engines_attempted,
        )

    if likelihood >= 0.50:
        warnings.append(
            f"Page {page.page_number}: difficult-document/handwriting likelihood "
            f"{likelihood:.2f}; handwriting-capable OCR path was evaluated."
        )

    if best["quality"].label in ("empty", "poor"):
        warnings.append(
            f"Page {page.page_number}: best available OCR result is "
            f"{best['quality'].label} quality "
            f"(engine={best['engine'].value}, score={best['quality'].score})."
        )

    final_text = best["text"].strip()

    return PageOCRResult(
        page_number=page.page_number,
        text=final_text,
        confidence=best["confidence"],
        # Keep the processed path as the primary source for compatibility;
        # the engine_attempted trail records when the untouched original was used.
        source_image_path=page.image_path,
        ocr_applied=True,
        text_extracted=bool(final_text),
        ocr_engine=best["engine"].value,
        quality_score=best["quality"].score,
        quality_label=best["quality"].label,
        confidence_approximate=best["confidence_approximate"],
        engines_attempted=engines_attempted,
    )


def _process_single_page(
    page: PageMetadata,
    document_type: DocumentType,
    original_document_path: Optional[Path],
    extracted_text_path: Optional[Path],
    lang: str,
    warnings: List[str],
) -> PageOCRResult:
    """
    Route a single page to the correct extraction strategy: reuse
    preprocessing's text, run the OCR pipeline on its image, or record
    it as unusable if neither is available.
    """
    if page.text_extracted and not page.ocr_required:
        return _process_text_page(
            page, document_type, original_document_path, extracted_text_path, warnings
        )

    if page.image_path is not None:
        return _process_image_page(page, lang, warnings, original_document_path)

    warnings.append(
        f"Page {page.page_number} has neither extractable text nor an "
        f"image to OCR; skipping."
    )
    return PageOCRResult(
        page_number=page.page_number,
        text="",
        confidence=None,
        source_image_path=None,
        ocr_applied=False,
        text_extracted=False,
        ocr_engine=OCREngine.NONE.value,
        quality_score=None,
        quality_label="empty",
        confidence_approximate=False,
        engines_attempted=[],
    )


# --------------------------------------------------------------------------- #
# Combination & output
# --------------------------------------------------------------------------- #

def combine_pages(pages: List[PageOCRResult]) -> str:
    """
    Combine per-page text into a single document string, preserving page
    order and marking clear page boundaries.

    Args:
        pages: Per-page OCR/extraction results.

    Returns:
        The combined text, with each page prefixed by a boundary marker.
    """
    sections: List[str] = []
    for page in sorted(pages, key=lambda p: p.page_number):
        header = f"----- Page {page.page_number} -----"
        body = page.text if page.text else "[No text extracted]"
        sections.append(f"{header}\n{body}")
    return "\n\n".join(sections)


def compute_average_confidence(pages: List[PageOCRResult]) -> Optional[float]:
    """
    Compute the overall average OCR confidence across all pages that
    actually had a confidence score (i.e. pages that were OCR'd by an
    engine that reports one).

    Note: this averages confidence values across potentially different
    engines (Tesseract, EasyOCR), which are not perfectly equivalent
    scales. It is intended as a rough, approximate summary only -- see
    each page's `confidence_approximate` flag for whether that page's
    individual value is calibrated the same way as Tesseract's.

    Returns:
        The average confidence (0-100), or None if no page produced a
        confidence score (e.g. an all-text document with no OCR at all,
        or every OCR'd page came back empty).
    """
    scores = [p.confidence for p in pages if p.confidence is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 2)


def _compute_engine_usage_summary(pages: List[PageOCRResult]) -> Dict[str, int]:
    """Count how many pages ended up using each OCR engine (diagnostic)."""
    summary: Dict[str, int] = {}
    for page in pages:
        key = page.ocr_engine or OCREngine.NONE.value
        summary[key] = summary.get(key, 0) + 1
    return summary


def save_combined_text(
    text: str, output_dir: Path, filename: str = OCR_OUTPUT_FILENAME
) -> Path:
    """
    Save the combined extracted text as a UTF-8 file, creating the output
    directory if necessary. The original uploaded document is never
    touched by this module.

    Args:
        text: Combined text to save.
        output_dir: Directory in which to save the file (typically the
            same per-document output directory used by preprocessing).
        filename: Name of the output text file.

    Returns:
        Path to the saved text file.

    Raises:
        OCRProcessingError: If the file cannot be written.
    """
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename
        output_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise OCRProcessingError(
            f"Failed to save OCR output text to: {output_dir / filename}"
        ) from exc
    return output_path


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #

def run_ocr(
    document_metadata: DocumentMetadata,
    original_document_path: Optional[Union[str, Path]] = None,
    lang: str = DEFAULT_OCR_LANGUAGE,
    save_output: bool = True,
) -> OCRResult:
    """
    Run the OCR / text-extraction stage on a preprocessed document.

    For each page, this reuses preprocessing's extracted text where it is
    already available (text-based PDF pages, DOCX, DOC-derived-DOCX) and
    only invokes the OCR pipeline where a page genuinely requires it
    (scanned PDF pages, standalone JPG/JPEG/PNG images). For image pages,
    an intelligent, multi-engine pipeline (Tesseract -> EasyOCR -> TrOCR)
    is used, escalating only as far as necessary based on a genuine OCR
    quality assessment (see `_process_image_page`). Page order and
    per-page boundaries are always preserved in the final output.

    Args:
        document_metadata: The `DocumentMetadata` returned by
            `preprocessing.preprocess_document(...)`.
        original_document_path: Path to the original uploaded document.
            Required to recover exact per-page text for multi-page
            text-based PDFs; if omitted, a truncated preview is used
            instead for those pages (with a warning recorded).
        lang: Tesseract-style language code(s) to use for OCR (default
            "eng"). Multiple languages can be combined, e.g. "eng+hin",
            provided the corresponding Tesseract language data is
            installed; a best-effort equivalent is also derived for
            EasyOCR.
        save_output: Whether to write the combined extracted text to disk
            (inside `document_metadata.output_dir`).

    Returns:
        An `OCRResult` describing the extracted text, per-page detail,
        confidence scores, quality assessment, engines used, and overall
        processing status.

    Raises:
        OCRProcessingError (and subclasses): On validation, dependency,
            or unexpected processing failures. A single failed page never
            raises -- it is recorded as a warning and an empty/failed
            page result instead, so one bad page cannot fail an entire
            multi-page document.
    """
    if not document_metadata.pages:
        raise OCRProcessingError(
            f"No pages available for OCR processing: {document_metadata.original_filename}"
        )

    original_path = Path(original_document_path) if original_document_path else None
    warnings: List[str] = []
    page_results: List[PageOCRResult] = []

    try:
        for page in sorted(document_metadata.pages, key=lambda p: p.page_number):
            result = _process_single_page(
                page,
                document_metadata.document_type,
                original_path,
                document_metadata.extracted_text_path,
                lang,
                warnings,
            )
            page_results.append(result)
    except (OCRProcessingError, TesseractNotFoundError, OCRImageError, OCRDependencyError):
        raise
    except Exception as exc:
        logger.exception(
            "Unexpected error during OCR for '%s'", document_metadata.original_filename
        )
        raise OCRProcessingError(
            f"Unexpected error during OCR for "
            f"'{document_metadata.original_filename}': {exc}"
        ) from exc

    combined_text = combine_pages(page_results)
    average_confidence = compute_average_confidence(page_results)
    engine_usage_summary = _compute_engine_usage_summary(page_results)

    output_text_path: Optional[Path] = None
    if save_output:
        output_text_path = save_combined_text(combined_text, document_metadata.output_dir)

    successful_pages = sum(1 for p in page_results if p.text_extracted)
    if successful_pages == 0:
        status = "failed"
    elif successful_pages < len(page_results):
        status = "partial"
    else:
        status = "success"

    ocr_applied_any = any(p.ocr_applied for p in page_results)

    result = OCRResult(
        original_filename=document_metadata.original_filename,
        document_type=document_metadata.document_type,
        num_pages=len(page_results),
        pages=page_results,
        combined_text=combined_text,
        average_confidence=average_confidence,
        output_text_path=output_text_path,
        ocr_required=ocr_applied_any,
        processing_status=status,
        warnings=warnings,
        engine_usage_summary=engine_usage_summary,
    )

    logger.info(
        "OCR complete for '%s' (%d pages, status=%s, avg_confidence=%s, engines=%s).",
        document_metadata.original_filename,
        result.num_pages,
        status,
        average_confidence,
        engine_usage_summary,
    )
    return result


__all__ = [
    "OCRProcessingError",
    "TesseractNotFoundError",
    "OCRImageError",
    "OCRDependencyError",
    "OCRModelError",
    "OCREngine",
    "PageOCRResult",
    "OCRResult",
    "QualityAssessment",
    "assess_ocr_quality",
    "get_tesseract_path",
    "validate_image_path",
    "ocr_image",
    "combine_pages",
    "compute_average_confidence",
    "save_combined_text",
    "run_ocr",
]
