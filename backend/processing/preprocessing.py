"""Universal document preprocessing for Authenticity Validator for Academia.

Preserves both original and OCR-preprocessed images so downstream OCR can
choose the safest representation for printed, scanned, and handwritten content.
Supported inputs: PDF, DOC, DOCX, JPG, JPEG, PNG.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

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

class DocumentPreprocessingError(Exception):
    """Base exception for all document preprocessing failures."""


class UnsupportedFormatError(DocumentPreprocessingError):
    """Raised when the input file extension/type is not supported."""


class CorruptedFileError(DocumentPreprocessingError):
    """Raised when a file exists but its content cannot be parsed/read."""


class MissingDependencyError(DocumentPreprocessingError):
    """Raised when a required external tool or library is unavailable."""


class ConversionError(DocumentPreprocessingError):
    """Raised when converting between document formats fails."""


# --------------------------------------------------------------------------- #
# Enums & constants
# --------------------------------------------------------------------------- #

class DocumentType(str, Enum):
    """Logical document category, independent of the exact extension."""

    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"
    IMAGE = "image"


class ImagePreprocessingStrategy(str, Enum):
    """
    Selectable image processing strategies.

    GRAYSCALE_ONLY: grayscale + denoise + contrast enhancement + deskew.
        Preserves gray-level detail, which is important for stamps,
        signatures, seals, and faint text. This is the safer default.

    FULL: everything in GRAYSCALE_ONLY plus adaptive binarization.
        Produces a crisp black/white image, good for dense printed text,
        but can destroy soft details like seals or handwritten signatures.
    """

    GRAYSCALE_ONLY = "grayscale_only"
    FULL = "full"


# Extension -> logical document type.
SUPPORTED_EXTENSIONS = {
    ".pdf": DocumentType.PDF,
    ".docx": DocumentType.DOCX,
    ".doc": DocumentType.DOC,
    ".jpg": DocumentType.IMAGE,
    ".jpeg": DocumentType.IMAGE,
    ".png": DocumentType.IMAGE,
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# A PDF page with at least this many characters of extractable text is
# treated as "text-based" and is not rendered/OCR-preprocessed at all.
MIN_TEXT_LENGTH_PER_PAGE = 20

# DPI used when rendering scanned PDF pages to images. High enough for
# good OCR accuracy without producing excessively large files.
PDF_RENDER_DPI = 300

# Images (or rendered pages) larger than this on the longest side are
# downscaled. Smaller images are left untouched to avoid upscaling blur.
MAX_DIMENSION = 2000

# Timeout (seconds) for external LibreOffice conversion calls.
DOC_CONVERSION_TIMEOUT = 120


# --------------------------------------------------------------------------- #
# Metadata structures
# --------------------------------------------------------------------------- #

@dataclass
class PageMetadata:
    """Metadata describing a single page/unit of a processed document."""

    page_number: int
    width: int
    height: int
    text_extracted: bool
    ocr_required: bool
    image_path: Optional[Path] = None
    original_image_path: Optional[Path] = None
    extracted_text_preview: Optional[str] = None


@dataclass
class DocumentMetadata:
    """Structured result returned by `preprocess_document`."""

    original_filename: str
    extension: str
    document_type: DocumentType
    num_pages: int
    pages: List[PageMetadata]
    output_dir: Path
    extracted_text_path: Optional[Path]
    ocr_required: bool
    text_extraction_available: bool
    processing_status: str
    warnings: List[str] = field(default_factory=list)
    embedded_image_paths: List[Path] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# File validation & type detection
# --------------------------------------------------------------------------- #

def detect_document_type(input_path: Path) -> DocumentType:
    """
    Validate an input file and determine its logical document type.

    Args:
        input_path: Path to the uploaded document.

    Returns:
        The detected `DocumentType`.

    Raises:
        DocumentPreprocessingError: If the file is missing, unreadable,
            or empty.
        UnsupportedFormatError: If the file extension is not supported.
    """
    if not isinstance(input_path, Path):
        input_path = Path(input_path)

    try:
        exists = input_path.exists()
    except PermissionError as exc:
        raise DocumentPreprocessingError(
            f"Permission denied while accessing: {input_path}"
        ) from exc

    if not exists:
        raise DocumentPreprocessingError(f"Input file does not exist: {input_path}")

    if not input_path.is_file():
        raise DocumentPreprocessingError(f"Input path is not a file: {input_path}")

    extension = input_path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Unsupported file extension '{extension}'. "
            f"Supported extensions: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    try:
        size = input_path.stat().st_size
    except PermissionError as exc:
        raise DocumentPreprocessingError(
            f"Permission denied while reading file stats: {input_path}"
        ) from exc

    if size == 0:
        raise CorruptedFileError(f"Input file is empty: {input_path.name}")

    return SUPPORTED_EXTENSIONS[extension]


def _create_document_output_dir(input_path: Path, output_dir: Path) -> Path:
    """
    Create a dedicated output subdirectory for a document's processed
    artifacts, so the original upload is never modified or overwritten.

    Args:
        input_path: Path to the original uploaded document.
        output_dir: Base directory under which outputs should be stored.

    Returns:
        The created (or already existing) document-specific output path.
    """
    doc_output_dir = output_dir / f"{input_path.stem}_processed"
    doc_output_dir.mkdir(parents=True, exist_ok=True)
    return doc_output_dir


# --------------------------------------------------------------------------- #
# Image preprocessing primitives (reusable, single-purpose functions)
# --------------------------------------------------------------------------- #

def load_image(input_path: Path) -> np.ndarray:
    """
    Safely load an image file into an OpenCV-compatible BGR array.

    Args:
        input_path: Path to a .jpg/.jpeg/.png file.

    Returns:
        A NumPy array in BGR format.

    Raises:
        CorruptedFileError: If the file cannot be identified or decoded
            as a valid image.
    """
    try:
        with Image.open(input_path) as pil_image:
            pil_image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise CorruptedFileError(
            f"File could not be identified as a valid image: {input_path.name}"
        ) from exc

    try:
        with Image.open(input_path) as pil_image:
            rgb_image = pil_image.convert("RGB")
            image = cv2.cvtColor(np.array(rgb_image), cv2.COLOR_RGB2BGR)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise CorruptedFileError(
            f"Failed to decode image data: {input_path.name}"
        ) from exc

    _validate_non_empty(image, "load_image")
    return image


def resize_image(image: np.ndarray, max_dimension: int = MAX_DIMENSION) -> np.ndarray:
    """
    Resize an image so its longest side does not exceed `max_dimension`,
    preserving aspect ratio. Images already within the limit are left
    unchanged to avoid unnecessary upscaling/quality loss.
    """
    _validate_non_empty(image, "resize_image")

    height, width = image.shape[:2]
    longest_side = max(height, width)
    if longest_side <= max_dimension:
        return image

    scale = max_dimension / float(longest_side)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)


def convert_to_grayscale(image: np.ndarray) -> np.ndarray:
    """Convert a BGR (or already-grayscale) image to single-channel grayscale."""
    _validate_non_empty(image, "convert_to_grayscale")
    if len(image.shape) == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def remove_noise(gray_image: np.ndarray) -> np.ndarray:
    """
    Remove scan/sensor noise using a bilateral filter, which preserves
    edges (and therefore text legibility) better than simple blurring.
    """
    _validate_non_empty(gray_image, "remove_noise")
    return cv2.bilateralFilter(gray_image, d=9, sigmaColor=75, sigmaSpace=75)


def enhance_contrast(gray_image: np.ndarray) -> np.ndarray:
    """Enhance local contrast using CLAHE, recovering faint/uneven text."""
    _validate_non_empty(gray_image, "enhance_contrast")
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray_image)


def binarize_image(gray_image: np.ndarray) -> np.ndarray:
    """
    Convert grayscale to black/white using adaptive Gaussian thresholding.

    NOTE: This step is destructive to soft detail (stamps, seals, faint
    signatures) and should only be applied when a crisp binary image is
    actually needed (see `ImagePreprocessingStrategy.FULL`).
    """
    _validate_non_empty(gray_image, "binarize_image")
    return cv2.adaptiveThreshold(
        gray_image,
        maxValue=255,
        adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        thresholdType=cv2.THRESH_BINARY,
        blockSize=25,
        C=15,
    )


def deskew_image(image: np.ndarray) -> np.ndarray:
    """
    Correct slight rotation (skew) typical of scanned/photographed
    documents. Works on grayscale or binary single-channel images.
    """
    _validate_non_empty(image, "deskew_image")

    if len(image.shape) != 2:
        raise DocumentPreprocessingError("deskew_image expects a single-channel image.")

    # Threshold internally (without mutating the caller's image) purely
    # to locate foreground pixels for angle estimation.
    _, thresh = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coordinates = cv2.findNonZero(thresh)
    if coordinates is None:
        logger.warning("No foreground content found for deskewing; skipping.")
        return image

    angle = cv2.minAreaRect(coordinates)[-1]
    if angle < -45:
        angle = 90 + angle
    angle = -angle

    if abs(angle) < 0.1 or abs(angle) > 45:
        return image

    height, width = image.shape[:2]
    center = (width // 2, height // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle, scale=1.0)
    return cv2.warpAffine(
        image,
        rotation_matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def remove_borders(image: np.ndarray) -> np.ndarray:
    """
    Optional cleanup that crops away dark scanner borders/background
    surrounding the actual document content.

    This is intentionally conservative: if no clearly dominant content
    contour is found, the original image is returned unmodified rather
    than risking a bad crop.
    """
    _validate_non_empty(image, "remove_borders")

    _, thresh = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image

    largest = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(largest)

    image_area = image.shape[0] * image.shape[1]
    # Only crop if the detected content region is a meaningfully large,
    # but not the entire, portion of the frame -- avoids trivial/no-op
    # crops and avoids destructive crops caused by noisy thresholds.
    if 0.5 * image_area <= (w * h) < 0.99 * image_area:
        return image[y : y + h, x : x + w]
    return image


def save_image_png(image: np.ndarray, output_path: Path) -> Path:
    """
    Save a processed image losslessly as PNG, creating parent directories
    as needed.

    Args:
        image: Image array to save.
        output_path: Destination path (extension will be forced to .png).

    Returns:
        The resolved output path.

    Raises:
        DocumentPreprocessingError: If the image is invalid or cannot be
            written.
    """
    _validate_non_empty(image, "save_image_png")

    if output_path.suffix.lower() != ".png":
        output_path = output_path.with_suffix(".png")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    success = cv2.imwrite(str(output_path), image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not success:
        raise DocumentPreprocessingError(f"Failed to write processed image: {output_path}")
    return output_path


def preprocess_page_image(
    image: np.ndarray,
    strategy: ImagePreprocessingStrategy = ImagePreprocessingStrategy.GRAYSCALE_ONLY,
) -> np.ndarray:
    """
    Run the configurable image preprocessing chain on a single page/photo.

    Order: resize -> grayscale -> denoise -> contrast enhance
           -> [binarize if FULL] -> deskew

    Args:
        image: Source image (BGR or grayscale) as a NumPy array.
        strategy: Which preprocessing strategy to apply (see
            `ImagePreprocessingStrategy`).

    Returns:
        The processed, single-channel image ready for OCR.
    """
    _validate_non_empty(image, "preprocess_page_image")

    resized = resize_image(image)
    gray = convert_to_grayscale(resized)
    denoised = remove_noise(gray)
    enhanced = enhance_contrast(denoised)

    if strategy == ImagePreprocessingStrategy.FULL:
        result = binarize_image(enhanced)
    else:
        result = enhanced

    return deskew_image(result)


def _validate_non_empty(image: np.ndarray, stage_name: str) -> None:
    """Raise if an intermediate image array is missing or empty."""
    if image is None or not isinstance(image, np.ndarray) or image.size == 0:
        raise DocumentPreprocessingError(f"Invalid or empty image passed to '{stage_name}'.")


# --------------------------------------------------------------------------- #
# PDF processing
# --------------------------------------------------------------------------- #

def _extract_pdf_pages(
    input_path: Path,
    output_dir: Path,
    strategy: ImagePreprocessingStrategy,
) -> Tuple[List[PageMetadata], Optional[Path], bool, bool]:
    """
    Process every page of a PDF, preserving page order.

    Text-based pages have their text extracted directly (no image
    rendering needed). Scanned/image-based pages are rendered at high
    DPI and passed through the image preprocessing pipeline.

    Returns:
        (pages_metadata, extracted_text_path, ocr_required, text_available)

    Raises:
        MissingDependencyError: If PyMuPDF is not installed.
        CorruptedFileError: If the PDF cannot be opened/parsed/decrypted.
        ConversionError: If a scanned page fails to render.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise MissingDependencyError(
            "PyMuPDF ('pymupdf') is required to process PDF files. "
            "Install it via 'pip install pymupdf'."
        ) from exc

    try:
        document = fitz.open(str(input_path))
    except Exception as exc:  # PyMuPDF raises its own generic exceptions
        raise CorruptedFileError(f"Failed to open PDF file: {input_path.name}") from exc

    try:
        if document.is_encrypted:
            # Attempt to open with an empty password (common for PDFs that
            # are only "restricted", not truly password protected). If
            # that fails, we cannot proceed without user-supplied
            # credentials, which are out of scope for this module.
            if not document.authenticate(""):
                raise CorruptedFileError(
                    f"PDF is password-protected and could not be opened: {input_path.name}"
                )

        if document.page_count == 0:
            raise CorruptedFileError(f"PDF contains no pages: {input_path.name}")

        pages_metadata: List[PageMetadata] = []
        text_fragments: List[str] = []
        overall_ocr_required = False
        overall_text_available = False

        for index in range(document.page_count):
            page_number = index + 1
            try:
                page = document.load_page(index)
                text = page.get_text("text") or ""
                rect = page.rect
                width, height = int(rect.width), int(rect.height)
            except Exception as exc:
                # Never silently drop a page -- record it as failed/needing
                # OCR so downstream stages are aware of it.
                logger.warning("Failed to read PDF page %d: %s", page_number, exc)
                pages_metadata.append(
                    PageMetadata(
                        page_number=page_number,
                        width=0,
                        height=0,
                        text_extracted=False,
                        ocr_required=True,
                    )
                )
                overall_ocr_required = True
                continue

            if len(text.strip()) >= MIN_TEXT_LENGTH_PER_PAGE:
                # Usable embedded text -- avoid unnecessary rendering/OCR.
                pages_metadata.append(
                    PageMetadata(
                        page_number=page_number,
                        width=width,
                        height=height,
                        text_extracted=True,
                        ocr_required=False,
                        extracted_text_preview=text.strip()[:200],
                    )
                )
                text_fragments.append(text)
                overall_text_available = True
            else:
                # Likely a scanned page -- render to a high-quality image.
                zoom = PDF_RENDER_DPI / 72.0
                matrix = fitz.Matrix(zoom, zoom)
                try:
                    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                except Exception as exc:
                    raise ConversionError(
                        f"Failed to render PDF page {page_number} of '{input_path.name}': {exc}"
                    ) from exc

                image_array = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height, pixmap.width, pixmap.n
                )
                if pixmap.n == 4:
                    bgr_image = cv2.cvtColor(image_array, cv2.COLOR_RGBA2BGR)
                else:
                    bgr_image = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)

                # Preserve the original rendered page for OCR engines that
                # perform better on untouched pixels (especially handwriting,
                # faint strokes, signatures, and mixed documents).
                original_page_path = output_dir / f"page_{page_number:03d}_original.png"
                save_image_png(bgr_image, original_page_path)

                # Also create the safer processed version for conventional OCR.
                processed = preprocess_page_image(bgr_image, strategy=strategy)
                page_path = output_dir / f"page_{page_number:03d}_processed.png"
                save_image_png(processed, page_path)

                pages_metadata.append(
                    PageMetadata(
                        page_number=page_number,
                        width=processed.shape[1],
                        height=processed.shape[0],
                        text_extracted=False,
                        ocr_required=True,
                        image_path=page_path,
                        original_image_path=original_page_path,
                    )
                )
                overall_ocr_required = True
    finally:
        document.close()

    extracted_text_path: Optional[Path] = None
    if text_fragments:
        extracted_text_path = output_dir / "extracted_text.txt"
        extracted_text_path.write_text("\n\n".join(text_fragments), encoding="utf-8")

    return pages_metadata, extracted_text_path, overall_ocr_required, overall_text_available


# --------------------------------------------------------------------------- #
# DOCX processing
# --------------------------------------------------------------------------- #

def _extract_docx_images(input_path: Path, output_dir: Path) -> List[Path]:
    """
    Best-effort extraction of embedded images from a DOCX package (a DOCX
    file is itself a ZIP archive containing a 'word/media/' folder).

    Returns:
        List of paths to extracted embedded images (may be empty).
    """
    saved_paths: List[Path] = []
    try:
        with zipfile.ZipFile(input_path) as archive:
            media_entries = [n for n in archive.namelist() if n.startswith("word/media/")]
            if not media_entries:
                return saved_paths

            images_dir = output_dir / "embedded_images"
            images_dir.mkdir(parents=True, exist_ok=True)
            for entry_name in media_entries:
                data = archive.read(entry_name)
                out_path = images_dir / Path(entry_name).name
                out_path.write_bytes(data)
                saved_paths.append(out_path)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        logger.warning("Could not extract embedded images from DOCX: %s", exc)
    return saved_paths


def _extract_docx_content(
    input_path: Path, output_dir: Path
) -> Tuple[List[PageMetadata], Optional[Path], bool, bool, List[Path]]:
    """
    Extract paragraph text (in original order) and embedded images from
    a DOCX file.

    Returns:
        (pages_metadata, extracted_text_path, ocr_required,
         text_available, embedded_image_paths)

    Raises:
        MissingDependencyError: If python-docx is not installed.
        CorruptedFileError: If the DOCX cannot be opened/parsed.
    """
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise MissingDependencyError(
            "python-docx is required to process DOCX files. "
            "Install it via 'pip install python-docx'."
        ) from exc

    try:
        document = docx.Document(str(input_path))
    except Exception as exc:
        raise CorruptedFileError(f"Failed to open DOCX file: {input_path.name}") from exc

    # Preserve paragraph order exactly as it appears in the document.
    paragraphs = [p.text for p in document.paragraphs if p.text and p.text.strip()]
    full_text = "\n".join(paragraphs)

    if not full_text.strip():
        logger.warning("DOCX contains no extractable paragraph text: %s", input_path.name)

    extracted_text_path: Optional[Path] = None
    if full_text.strip():
        extracted_text_path = output_dir / "extracted_text.txt"
        extracted_text_path.write_text(full_text, encoding="utf-8")

    embedded_images = _extract_docx_images(input_path, output_dir)

    # DOCX has no fixed "page" concept without a rendering engine, so the
    # whole document is represented as a single logical text unit.
    page_metadata = PageMetadata(
        page_number=1,
        width=0,
        height=0,
        text_extracted=bool(full_text.strip()),
        ocr_required=False,
        extracted_text_preview=full_text.strip()[:200] if full_text.strip() else None,
    )

    return [page_metadata], extracted_text_path, False, bool(full_text.strip()), embedded_images


# --------------------------------------------------------------------------- #
# Legacy DOC processing
# --------------------------------------------------------------------------- #

def _convert_doc_to_docx(input_path: Path, temp_dir: Path) -> Path:
    """
    Convert a legacy .doc file to .docx using LibreOffice's headless CLI,
    since Python has no reliable native .doc parser.

    Args:
        input_path: Path to the source .doc file.
        temp_dir: Scratch directory for the converted output.

    Returns:
        Path to the converted .docx file.

    Raises:
        MissingDependencyError: If LibreOffice is not installed/available.
        ConversionError: If the conversion process fails or times out.
    """
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        raise MissingDependencyError(
            "LibreOffice ('soffice') is required to convert legacy .doc files "
            "but was not found on this system. Install LibreOffice to enable "
            ".doc support."
        )

    try:
        result = subprocess.run(
            [
                converter,
                "--headless",
                "--norestore",
                "--convert-to",
                "docx",
                "--outdir",
                str(temp_dir),
                str(input_path),
            ],
            capture_output=True,
            timeout=DOC_CONVERSION_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(
            f"Timed out converting DOC file to DOCX: {input_path.name}"
        ) from exc
    except OSError as exc:
        raise ConversionError(
            f"Failed to invoke LibreOffice for DOC conversion: {exc}"
        ) from exc

    if result.returncode != 0:
        stderr_text = result.stderr.decode(errors="ignore") if result.stderr else ""
        raise ConversionError(
            f"LibreOffice failed to convert '{input_path.name}' to DOCX: {stderr_text}"
        )

    converted_path = temp_dir / f"{input_path.stem}.docx"
    if not converted_path.exists():
        raise ConversionError(
            f"Expected converted file was not produced: {converted_path.name}"
        )
    return converted_path


# --------------------------------------------------------------------------- #
# Image document processing
# --------------------------------------------------------------------------- #

def _process_image_document(
    input_path: Path,
    output_dir: Path,
    strategy: ImagePreprocessingStrategy,
) -> Tuple[List[PageMetadata], bool, bool]:
    """
    Run the full image preprocessing pipeline on a standalone
    JPG/JPEG/PNG document.

    Returns:
        (pages_metadata, ocr_required, text_available)
    """
    image = load_image(input_path)

    # Preserve the untouched original image. The OCR stage can use this
    # representation when preprocessing would remove thin handwriting,
    # faint strokes, signatures, stamps, or other subtle visual details.
    original_path = output_dir / f"{input_path.stem}_original.png"
    save_image_png(image, original_path)

    # Create the conventional OCR-friendly processed representation.
    processed = preprocess_page_image(image, strategy=strategy)
    output_path = output_dir / f"{input_path.stem}_processed.png"
    save_image_png(processed, output_path)

    page_metadata = PageMetadata(
        page_number=1,
        width=processed.shape[1],
        height=processed.shape[0],
        text_extracted=False,
        ocr_required=True,
        image_path=output_path,
        original_image_path=original_path,
    )
    return [page_metadata], True, False


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #

def preprocess_document(
    input_path: Union[str, Path],
    output_dir: Union[str, Path],
    image_strategy: ImagePreprocessingStrategy = ImagePreprocessingStrategy.GRAYSCALE_ONLY,
) -> DocumentMetadata:
    """
    Universal preprocessing entry point. Detects the document's type and
    dispatches to the appropriate extraction/conversion pipeline.

    Pipeline:
        detect file type
        -> extract/convert content (PDF / DOC / DOCX / IMAGE)
        -> preprocess pages/images where applicable
        -> write standardized outputs
        -> return structured metadata for the OCR stage

    Args:
        input_path: Path to the uploaded document
            (.pdf, .doc, .docx, .jpg, .jpeg, .png).
        output_dir: Base directory where processed artifacts should be
            written. A dedicated subdirectory is created per document so
            the original upload is never modified or overwritten.
        image_strategy: Preprocessing strategy applied to any images
            (standalone image uploads, or rendered scanned PDF pages).
            Defaults to GRAYSCALE_ONLY to preserve stamps/signatures;
            pass FULL for a crisper binarized result when appropriate.

    Returns:
        A `DocumentMetadata` instance describing everything produced,
        ready to be consumed by the OCR/text-extraction stage.

    Raises:
        DocumentPreprocessingError (and subclasses): On any validation,
            parsing, conversion, or unexpected processing failure.
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    document_type = detect_document_type(input_path)
    doc_output_dir = _create_document_output_dir(input_path, output_dir)

    warnings: List[str] = []
    embedded_image_paths: List[Path] = []
    extracted_text_path: Optional[Path] = None

    try:
        if document_type == DocumentType.PDF:
            pages, extracted_text_path, ocr_required, text_available = _extract_pdf_pages(
                input_path, doc_output_dir, image_strategy
            )

        elif document_type == DocumentType.DOCX:
            (
                pages,
                extracted_text_path,
                ocr_required,
                text_available,
                embedded_image_paths,
            ) = _extract_docx_content(input_path, doc_output_dir)

        elif document_type == DocumentType.DOC:
            with tempfile.TemporaryDirectory(prefix="doc_convert_") as tmp:
                converted_path = _convert_doc_to_docx(input_path, Path(tmp))
                (
                    pages,
                    extracted_text_path,
                    ocr_required,
                    text_available,
                    embedded_image_paths,
                ) = _extract_docx_content(converted_path, doc_output_dir)

        elif document_type == DocumentType.IMAGE:
            pages, ocr_required, text_available = _process_image_document(
                input_path, doc_output_dir, image_strategy
            )

        else:  # pragma: no cover - defensive; SUPPORTED_EXTENSIONS keeps this unreachable
            raise UnsupportedFormatError(
                f"No processing strategy implemented for document type: {document_type}"
            )

    except DocumentPreprocessingError:
        # Already a well-formed, descriptive error -- propagate as-is.
        raise
    except Exception as exc:
        logger.exception("Unexpected error while preprocessing '%s'", input_path.name)
        raise DocumentPreprocessingError(
            f"Unexpected error while processing '{input_path.name}': {exc}"
        ) from exc

    if not pages:
        warnings.append("No pages could be extracted or processed from the document.")
        status = "failed"
    elif any(p.ocr_required for p in pages) and any(p.text_extracted for p in pages):
        status = "partial"
    else:
        status = "success"

    metadata = DocumentMetadata(
        original_filename=input_path.name,
        extension=input_path.suffix.lower(),
        document_type=document_type,
        num_pages=len(pages),
        pages=pages,
        output_dir=doc_output_dir,
        extracted_text_path=extracted_text_path,
        ocr_required=ocr_required,
        text_extraction_available=text_available,
        processing_status=status,
        warnings=warnings,
        embedded_image_paths=embedded_image_paths,
    )

    logger.info(
        "Preprocessing complete for '%s' (%s pages, status=%s).",
        input_path.name,
        metadata.num_pages,
        metadata.processing_status,
    )
    return metadata


__all__ = [
    "DocumentPreprocessingError",
    "UnsupportedFormatError",
    "CorruptedFileError",
    "MissingDependencyError",
    "ConversionError",
    "DocumentType",
    "ImagePreprocessingStrategy",
    "PageMetadata",
    "DocumentMetadata",
    "detect_document_type",
    "load_image",
    "resize_image",
    "convert_to_grayscale",
    "remove_noise",
    "enhance_contrast",
    "binarize_image",
    "deskew_image",
    "remove_borders",
    "save_image_png",
    "preprocess_page_image",
    "preprocess_document",
]