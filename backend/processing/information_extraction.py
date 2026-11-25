# """
# information_extraction.py
# =========================

# Deterministic (rule-based) extraction of structured fields from the cleaned
# text of academic / training documents: certificates, degrees, diplomas,
# mark sheets, transcripts, awards, credentials.

# Design principles
# -----------------
# * NOTHING is tied to one specific document. There are no institution names,
#   person names, course names, or fixed strings from any sample document.
#   The module only knows about *document structure*: labels ("Roll No:"),
#   certificate phrasing ("This is to certify that ..."), layout (a name on the
#   line after a cue, a designation under a signature), and value shapes
#   (dates, e-mails, URLs, IDs).
# * Several independent strategies are tried per field, strongest first
#   (explicit label -> sentence pattern -> layout heuristic), and the strategy
#   used is recorded in `ExtractedField.method`, together with a confidence
#   level and the source snippet.
# * Values are copied verbatim from the text (only boundaries are tidied);
#   OCR text is never "corrected" and nothing is invented.
# * A field that cannot be found stays `None`. Unrecognised "Label: value"
#   lines are kept in `additional_info` instead of being thrown away.
# * Every extractor is isolated: one failure never breaks the whole run.

# Public API (unchanged): `extract_information`, `extract_information_from_file`,
# `find_all_dates`, `find_all_emails`, `find_all_urls` and the result dataclasses.
# """

# from __future__ import annotations

# import logging
# import re
# from dataclasses import dataclass, field
# from enum import Enum
# from pathlib import Path
# from typing import Callable, Dict, List, Optional, Pattern, Tuple

# # --------------------------------------------------------------------------- #
# # Logging
# # --------------------------------------------------------------------------- #

# logger = logging.getLogger(__name__)
# if not logger.handlers:
#     _handler = logging.StreamHandler()
#     _handler.setFormatter(
#         logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
#     )
#     logger.addHandler(_handler)
#     logger.setLevel(logging.INFO)


# # --------------------------------------------------------------------------- #
# # Custom exceptions
# # --------------------------------------------------------------------------- #

# class InformationExtractionError(Exception):
#     """Base exception for all information-extraction failures."""


# class InvalidInputError(InformationExtractionError):
#     """Raised when the input to `extract_information` is invalid."""


# # --------------------------------------------------------------------------- #
# # Enums
# # --------------------------------------------------------------------------- #

# class ConfidenceLevel(str, Enum):
#     """
#     Heuristic confidence in an extracted field (NOT a calibrated probability):

#         HIGH   -> explicit label ("Student ID: ...") or an unambiguous
#                   pattern (e-mail, labelled date / ID).
#         MEDIUM -> a sentence pattern or document-structure heuristic
#                   ("presented to <name>", a heading line, a signature block).
#         LOW    -> weak best-effort guess (e.g. first line used as a title,
#                   the only date in the document assumed to be the issue date).
#     """

#     HIGH = "high"
#     MEDIUM = "medium"
#     LOW = "low"


# class DocumentType(str, Enum):
#     """Coarse academic-document categories this module can classify into."""

#     CERTIFICATE = "certificate"
#     TRAINING_CERTIFICATE = "training_certificate"
#     DEGREE = "degree"
#     DIPLOMA = "diploma"
#     MARKSHEET = "marksheet"
#     TRANSCRIPT = "transcript"
#     AWARD = "award"
#     CREDENTIAL = "credential"
#     OTHER = "other"
#     UNKNOWN = "unknown"


# _CONFIDENCE_RANK: Dict[ConfidenceLevel, int] = {
#     ConfidenceLevel.HIGH: 3,
#     ConfidenceLevel.MEDIUM: 2,
#     ConfidenceLevel.LOW: 1,
# }


# # --------------------------------------------------------------------------- #
# # Result structures
# # --------------------------------------------------------------------------- #

# @dataclass
# class ExtractedField:
#     """A single extracted value, together with its provenance."""

#     value: str
#     confidence: ConfidenceLevel
#     source: Optional[str] = None   # the text snippet the value came from
#     method: Optional[str] = None   # label | context_phrase | pattern | keyword | heading_heuristic | ...
#     page: Optional[int] = None     # 1-indexed page number, if known


# @dataclass
# class ExtractedDocumentInfo:
#     """All structured fields extracted from an academic document."""

#     document_title: Optional[ExtractedField] = None
#     document_type: Optional[ExtractedField] = None
#     recipient_name: Optional[ExtractedField] = None
#     student_id: Optional[ExtractedField] = None
#     certificate_number: Optional[ExtractedField] = None
#     institution_name: Optional[ExtractedField] = None
#     university_name: Optional[ExtractedField] = None
#     issuer_name: Optional[ExtractedField] = None
#     issuer_designation: Optional[ExtractedField] = None
#     course_name: Optional[ExtractedField] = None
#     degree_name: Optional[ExtractedField] = None
#     specialization: Optional[ExtractedField] = None
#     department: Optional[ExtractedField] = None
#     issue_date: Optional[ExtractedField] = None
#     start_date: Optional[ExtractedField] = None
#     completion_date: Optional[ExtractedField] = None
#     expiry_date: Optional[ExtractedField] = None
#     grade: Optional[ExtractedField] = None
#     marks: Optional[ExtractedField] = None
#     percentage: Optional[ExtractedField] = None
#     cgpa: Optional[ExtractedField] = None
#     email: Optional[ExtractedField] = None
#     website: Optional[ExtractedField] = None
#     location: Optional[ExtractedField] = None
#     # Labelled "Label: value" lines that do not belong to any schema field
#     # (e.g. "Duration: 40 hours"). Never fabricated.
#     additional_info: Dict[str, ExtractedField] = field(default_factory=dict)


# @dataclass
# class ExtractionStatistics:
#     """Aggregate counts describing what was found in the document."""

#     pages_processed: int = 0
#     fields_detected: int = 0
#     fields_not_detected: int = 0
#     dates_detected: int = 0
#     ids_detected: int = 0
#     emails_detected: int = 0
#     urls_detected: int = 0


# @dataclass
# class ExtractionResult:
#     """Structured result returned by `extract_information`."""

#     document_info: ExtractedDocumentInfo
#     status: str  # "success" | "partial" | "failed" | "empty"
#     warnings: List[str]
#     errors: List[str]
#     statistics: ExtractionStatistics
#     overall_confidence: Optional[ConfidenceLevel]
#     cleaned_text: str  # verbatim reference to the input this was derived from


# _SCHEMA_FIELD_NAMES: Tuple[str, ...] = (
#     "document_title", "document_type", "recipient_name", "student_id",
#     "certificate_number", "institution_name", "university_name",
#     "issuer_name", "issuer_designation", "course_name", "degree_name",
#     "specialization", "department", "issue_date", "start_date",
#     "completion_date", "expiry_date", "grade", "marks", "percentage",
#     "cgpa", "email", "website", "location",
# )


# # --------------------------------------------------------------------------- #
# # Page splitting ("----- Page N -----" markers from the cleaning stage)
# # --------------------------------------------------------------------------- #

# _PAGE_MARKER_PATTERN = re.compile(r"^-{2,}\s*Page\s+(\d+)\s*-{2,}$")


# def _split_pages(text: str) -> List[Tuple[Optional[int], str]]:
#     """
#     Split text into (page_number, page_body) segments using the
#     "----- Page N -----" markers. Without markers the whole text is one
#     page with number `None`.
#     """
#     lines = text.split("\n")
#     segments: List[Tuple[Optional[int], List[str]]] = []
#     leading_lines: List[str] = []
#     current_page: Optional[int] = None
#     current_lines: List[str] = []
#     seen_marker = False

#     for line in lines:
#         match = _PAGE_MARKER_PATTERN.match(line.strip())
#         if match:
#             if not seen_marker:
#                 if any(candidate.strip() for candidate in leading_lines):
#                     segments.append((None, leading_lines))
#             else:
#                 segments.append((current_page, current_lines))
#             current_page = int(match.group(1))
#             current_lines = []
#             seen_marker = True
#         else:
#             (current_lines if seen_marker else leading_lines).append(line)

#     if seen_marker:
#         segments.append((current_page, current_lines))
#     else:
#         segments.append((None, leading_lines))

#     return [(page, "\n".join(body_lines)) for page, body_lines in segments]


# # --------------------------------------------------------------------------- #
# # Low-level text helpers
# # --------------------------------------------------------------------------- #

# _WHITESPACE = re.compile(r"\s+")

# # A line that itself looks like "Some Label: value" (used to stop a value from
# # swallowing the next labelled line).
# _LABEL_LIKE_LINE = re.compile(r"^[A-Za-z][A-Za-z .()/&']{1,35}\s*:")

# # A second "Label:" further along the same line, e.g. after a column gap.
# _NEXT_LABEL_IN_VALUE = re.compile(r"(?:\t+|\s{2,}|\s\|\s)[A-Za-z][A-Za-z .()/&']{1,35}\s*:")

# # "Label: value" or "Label - value" (a dash needs spaces around it so that
# # hyphenated words such as "course-based" are not treated as labels).
# _LABEL_SEP = r"(?:\s*[:\uFF1A]\s*|\s+[-\u2013\u2014]+\s+)"


# def _non_empty_lines(text: str) -> List[str]:
#     return [line.strip() for line in text.split("\n") if line.strip()]


# def _next_non_empty(lines: List[str], idx: int, lookahead: int = 3) -> Optional[str]:
#     for j in range(idx + 1, min(len(lines), idx + 1 + lookahead)):
#         if lines[j].strip():
#             return lines[j].strip()
#     return None


# def _clean_value(value: str, strip_quotes: bool = False) -> str:
#     """
#     Trim a captured value's boundaries WITHOUT altering its letters, digits
#     or casing (the module must never "correct" OCR text).
#     """
#     value = _WHITESPACE.sub(" ", value).strip()
#     if strip_quotes:
#         value = value.strip(" \"'\u201c\u201d\u2018\u2019")
#     return value.strip(" .,;:|_")


# def _truncate_at_next_label(raw_value: str) -> str:
#     match = _NEXT_LABEL_IN_VALUE.search(raw_value)
#     return raw_value[: match.start()] if match else raw_value


# def _label_group(labels: List[str]) -> str:
#     return "(?:" + "|".join("(?:" + label + ")" for label in labels) + ")"


# def _extract_labeled_value(
#     text: str,
#     label_alternatives: List[str],
#     *,
#     allow_next_line: bool = True,
#     allow_table_gap: bool = True,
# ) -> Optional[Tuple[str, str]]:
#     """
#     Find the value belonging to one of the given label regexes. Supported
#     layouts (checked line by line, first hit wins):

#         Label: value                     (also "Label - value")
#         Label:                           value on the following line
#         Label                            label alone on its line, value next
#         Label      value                 table-style, separated by a wide gap

#     A second "Label:" further along the same line truncates the value so two
#     fields are never glued together. Returns (value, source_snippet).
#     """
#     group = _label_group(label_alternatives)
#     inline = re.compile(r"(?<![A-Za-z])" + group + _LABEL_SEP + r"(.*)$", re.IGNORECASE)
#     standalone = re.compile(r"^\W*" + group + r"\W*$", re.IGNORECASE)
#     gap = re.compile(r"^\W*" + group + r"(?:\t+|[ ]{2,})(\S.*)$", re.IGNORECASE)

#     lines = text.split("\n")
#     for idx, raw_line in enumerate(lines):
#         line = raw_line.strip()
#         if not line:
#             continue

#         match = inline.search(line)
#         if match:
#             trimmed = _truncate_at_next_label(match.group(1))
#             value = _clean_value(trimmed)
#             if value:
#                 return value, line[match.start(): match.start(1) + len(trimmed)].strip()
#             if allow_next_line:
#                 nxt = _next_non_empty(lines, idx)
#                 if nxt and not _LABEL_LIKE_LINE.match(nxt):
#                     value = _clean_value(_truncate_at_next_label(nxt))
#                     if value:
#                         return value, f"{line} {nxt}"
#             continue

#         if allow_next_line and standalone.match(line):
#             nxt = _next_non_empty(lines, idx)
#             if nxt and not _LABEL_LIKE_LINE.match(nxt):
#                 value = _clean_value(_truncate_at_next_label(nxt))
#                 if value:
#                     return value, f"{line} {nxt}"
#             continue

#         if allow_table_gap:
#             match = gap.match(line)
#             if match:
#                 trimmed = _truncate_at_next_label(match.group(1))
#                 # A value with another wide gap inside is most likely a table
#                 # header row ("Course   Duration   Grade"), not a value.
#                 if not re.search(r"\t|\s{2,}", trimmed):
#                     value = _clean_value(trimmed)
#                     if value:
#                         return value, line

#     return None


# # A stop pattern that ends a free-text phrase (course name, issuer, ...) at
# # the words/punctuation that normally follow it in certificate sentences.
# _MONTH = (
#     r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
#     r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
# )

# _PHRASE_STOP = re.compile(
#     r"\s+(?:(?:from|held|conducted|organi[sz]ed|offered|provided|delivered|hosted|arranged|at|during|"
#     r"between|dated|under|by|scoring|securing|having|who|which|that|as\s+part|in\s+the\s+month|"
#     r"and\s+(?:is|has|was)|is\s+hereby)\b"
#     r"|on\s+(?:the\s+)?\d|on\s+" + _MONTH + r"\b|in\s+" + _MONTH + r"\b|in\s+\d{4}\b"
#     r"|for\s+(?:a\s+)?(?:duration\b|period\b|\d)|of\s+\d+\s+(?:hours?|hrs?|days?|weeks?|months?)\b"
#     r"|with\s+(?:(?:grade|distinction|honou?rs?|merit|a\s+(?:grade|score)|first|second|third|marks|cgpa|gpa)\b|\d))"
#     r"|\s*[,;]|\.(?:\s|$)|\s+[-\u2013\u2014]\s+|\s{2,}|\t",
#     re.IGNORECASE,
# )

# _PHRASE_LEADING_STOP = re.compile(
#     r"^(?:with|from|at|on|by|held|conducted|organi[sz]ed|scoring|securing|during|under|and|having|"
#     r"in\s+the|of|for|to|the\s+certificate)\b",
#     re.IGNORECASE,
# )

# # A phrase that ends in a connector is assumed to continue on the next line.
# _CONTINUATION_END = re.compile(r"(?:\b(?:of|in|on|and|for|to|the|with|at|a|an)|[&,/\-\u2013\u2014])\s*$", re.IGNORECASE)


# def _phrase_after(text: str, pos: int, stop: Pattern[str] = _PHRASE_STOP) -> str:
#     """
#     Return the phrase that starts at `pos`: the rest of that line, or (when the
#     cue ended its line) the next non-empty line. A line ending in a connector
#     ("... program on") continues onto one further line. The phrase is cut at
#     the first `stop` match.
#     """
#     lines = text[pos:].split("\n")
#     idx = 0
#     first = lines[0].strip()
#     if not first:
#         found = next((i for i in range(1, min(len(lines), 3)) if lines[i].strip()), None)
#         if found is None:
#             return ""
#         idx = found
#         first = lines[idx].strip()
#         if _LABEL_LIKE_LINE.match(first):
#             return ""

#     phrase = first
#     if not stop.search(phrase) and _CONTINUATION_END.search(phrase) and idx + 1 < len(lines):
#         nxt = lines[idx + 1].strip()
#         if nxt and not _LABEL_LIKE_LINE.match(nxt):
#             phrase = f"{phrase} {nxt}"

#     match = stop.search(phrase)
#     if match:
#         phrase = phrase[: match.start()]
#     return _clean_value(phrase, strip_quotes=True)


# # --------------------------------------------------------------------------- #
# # Date detection
# # --------------------------------------------------------------------------- #

# _ORD = r"(?:st|nd|rd|th)?"

# # Ordered longest-first: at any position the first alternative that matches
# # wins, so "12 March 2024" is never reduced to "March 2024". No capturing groups.
# _DATE_SOURCES: List[Tuple[str, str]] = [
#     ("day_of_month_year", r"\b\d{1,2}" + _ORD + r"[ \t]+day[ \t]+of[ \t]+" + _MONTH + r"\.?,?[ \t]+\d{4}\b"),
#     ("day_month_year", r"\b\d{1,2}" + _ORD + r"[ \t\-]+(?:of[ \t]+)?" + _MONTH + r"\.?,?[ \t\-]+\d{4}\b"),
#     ("month_day_year", r"\b" + _MONTH + r"\.?[ \t]+\d{1,2}" + _ORD + r",?[ \t]+\d{4}\b"),
#     ("iso", r"(?<![\w/.\-])\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?![\w/\-])"),
#     ("numeric_slash_dash", r"(?<![\w/.\-])\d{1,2}[/\-]\d{1,2}[/\-](?:\d{4}|\d{2})(?![\w/\-])"),
#     ("numeric_dot", r"(?<![\w/.\-])\d{1,2}\.\d{1,2}\.\d{4}(?![\w/\-])"),
#     ("month_year", r"\b" + _MONTH + r"\.?,?[ \t]+\d{4}\b"),
# ]
# _ANY_DATE = "(?:" + "|".join(source for _name, source in _DATE_SOURCES) + ")"
# _ANY_DATE_RE = re.compile(_ANY_DATE, re.IGNORECASE)

# _DATE_RANGE_RE = re.compile(
#     r"(?:\bfrom\s+|\bbetween\s+)?(" + _ANY_DATE + r")\s*(?:to|till|until|through|and|[-\u2013\u2014])\s*(" + _ANY_DATE + r")",
#     re.IGNORECASE,
# )


# def _find_first_date(text: str) -> Optional[str]:
#     """Return the first recognizable date substring in `text`, if any."""
#     match = _ANY_DATE_RE.search(text)
#     return match.group(0) if match else None


# def find_all_dates(text: str) -> List[str]:
#     """Find every recognizable date substring in `text` (non-overlapping)."""
#     return [match.group(0) for match in _ANY_DATE_RE.finditer(text)]


# _DATE_LABELS: Dict[str, List[str]] = {
#     "issue_date": [
#         r"issued(?:\s*on)?", r"date\s*of\s*issu(?:e|ance)", r"issu(?:e|ance)\s*date",
#         r"date\s*of\s*award", r"awarded\s*on", r"date\s*of\s*certification",
#     ],
#     "start_date": [
#         r"start(?:ing)?\s*date", r"date\s*of\s*(?:commencement|start|joining)",
#         r"commenced\s*on", r"started\s*on", r"from\s*date", r"begin(?:ning)?\s*date",
#         r"joining\s*date", r"joined\s*on",
#     ],
#     "completion_date": [
#         r"completion\s*date", r"date\s*of\s*completion", r"completed\s*on",
#         r"end(?:ing)?\s*date", r"to\s*date", r"date\s*of\s*(?:passing|examination)",
#         r"exam(?:ination)?\s*date", r"concluded\s*on",
#     ],
#     "expiry_date": [
#         r"expiry(?:\s*date)?", r"expiration(?:\s*date)?", r"date\s*of\s*expiry",
#         r"valid\s*(?:till|until|upto|up\s*to|through|thru)", r"expires?\s*on", r"validity",
#     ],
# }

# # Used only as a weaker fallback for the issue date ("Date: 12/03/2024").
# _PLAIN_DATE_LABELS = [r"dated", r"date"]
# _PLAIN_DATE_EXCLUDE = re.compile(
#     r"start|begin|commenc|complet|\bend|expir|valid|birth|dob|join|\bfrom\b|\buntil\b|\btill\b|\bto\b",
#     re.IGNORECASE,
# )


# def _extract_labeled_date(
#     text: str,
#     labels: List[str],
#     *,
#     confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
#     allow_gap: bool = False,
#     exclude_line: Optional[Pattern[str]] = None,
# ) -> Optional[ExtractedField]:
#     """Extract a date that follows one of the given labels ("Issued on: ...")."""
#     group = _label_group(labels)
#     filler = r"[^\n\d]{0,40}?" if allow_gap else ""
#     inline = re.compile(
#         r"(?<![A-Za-z])" + group + r"\b\s*[:\-\u2013\u2014]?\s*" + filler + r"(?:on\s+|the\s+)?(" + _ANY_DATE + r")",
#         re.IGNORECASE,
#     )
#     standalone = re.compile(r"^\W*" + group + r"\W*$", re.IGNORECASE)

#     lines = text.split("\n")
#     for idx, raw_line in enumerate(lines):
#         line = raw_line.strip()
#         if not line or (exclude_line and exclude_line.search(line)):
#             continue
#         match = inline.search(line)
#         if match:
#             return ExtractedField(
#                 value=match.group(1), confidence=confidence,
#                 source=line[match.start(): match.end()], method="label",
#             )
#         if standalone.match(line):
#             nxt = _next_non_empty(lines, idx)
#             date_str = _find_first_date(nxt) if nxt else None
#             if date_str:
#                 return ExtractedField(value=date_str, confidence=confidence, source=f"{line} {nxt}", method="label")
#     return None


# def _date_from_range(text: str, which: int) -> Optional[ExtractedField]:
#     """Start (0) or end (1) of a 'from X to Y' style date range."""
#     match = _DATE_RANGE_RE.search(text)
#     if not match:
#         return None
#     return ExtractedField(
#         value=match.group(which + 1), confidence=ConfidenceLevel.MEDIUM,
#         source=match.group(0).strip(), method="context_phrase",
#     )


# _COMPLETION_CONTEXT = re.compile(
#     r"\b(?:complet(?:ed|ion)|passed|concluded|finished)\b(?:[^\n]|\n(?!\s*\n)){0,200}?"
#     r"\b(?:on|dated|in|during)\s+(?:the\s+)?(" + _ANY_DATE + r")",
#     re.IGNORECASE,
# )
# _ISSUE_CONTEXT = re.compile(
#     r"\b(?:given|issued|dated|awarded|presented)\b[^\n]{0,80}?\b(?:this|on|dated)\s+(?:the\s+)?(" + _ANY_DATE + r")",
#     re.IGNORECASE,
# )


# def _extract_issue_date(text: str) -> Optional[ExtractedField]:
#     found = _extract_labeled_date(text, _DATE_LABELS["issue_date"])
#     if found:
#         return found
#     found = _extract_labeled_date(
#         text, _PLAIN_DATE_LABELS, confidence=ConfidenceLevel.MEDIUM,
#         allow_gap=True, exclude_line=_PLAIN_DATE_EXCLUDE,
#     )
#     if found:
#         found.method = "label"
#         return found
#     match = _ISSUE_CONTEXT.search(text)
#     if match:
#         return ExtractedField(
#             value=match.group(1), confidence=ConfidenceLevel.MEDIUM,
#             source=match.group(0).strip(), method="context_phrase",
#         )
#     return None


# def _extract_start_date(text: str) -> Optional[ExtractedField]:
#     return _extract_labeled_date(text, _DATE_LABELS["start_date"]) or _date_from_range(text, 0)


# def _extract_completion_date(text: str) -> Optional[ExtractedField]:
#     found = _extract_labeled_date(text, _DATE_LABELS["completion_date"]) or _date_from_range(text, 1)
#     if found:
#         return found
#     match = _COMPLETION_CONTEXT.search(text)
#     if match:
#         return ExtractedField(
#             value=match.group(1), confidence=ConfidenceLevel.MEDIUM,
#             source=_WHITESPACE.sub(" ", match.group(0)).strip(), method="context_phrase",
#         )
#     return None


# def _extract_expiry_date(text: str) -> Optional[ExtractedField]:
#     return _extract_labeled_date(text, _DATE_LABELS["expiry_date"])


# # --------------------------------------------------------------------------- #
# # E-mail / URL detection
# # --------------------------------------------------------------------------- #

# _EMAIL_PATTERN = re.compile(r"(?<![A-Za-z0-9_.+\-])[A-Za-z0-9_.+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
# _URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
# # Bare domains ("example.com/verify") are only accepted for well-known TLDs
# # and with a second-level label of 3+ characters, so degree abbreviations such
# # as "B.Tech", "M.Sc" or "Ph.D" are never mistaken for websites.
# _BARE_DOMAIN_PATTERN = re.compile(
#     r"(?<![@\w./\-])(?:[a-z0-9\-]+\.)*[a-z0-9][a-z0-9\-]{2,}\."
#     r"(?:com|org|net|edu|gov|io|co|in|ac|info|biz|ai|us|uk|ca|au|de|app|dev|online|site|tech|academy|school|xyz)"
#     r"(?:\.[a-z]{2})?(?:/[^\s<>\"']*)?(?![\w@\-])",
#     re.IGNORECASE,
# )


# def find_all_emails(text: str) -> List[str]:
#     """Return every email-like substring found in `text`."""
#     return [match.group(0) for match in _EMAIL_PATTERN.finditer(text)]


# def _url_matches(text: str) -> List["re.Match[str]"]:
#     email_spans = [match.span() for match in _EMAIL_PATTERN.finditer(text)]
#     found: List["re.Match[str]"] = []
#     taken: List[Tuple[int, int]] = []
#     for pattern in (_URL_PATTERN, _BARE_DOMAIN_PATTERN):
#         for match in pattern.finditer(text):
#             span = match.span()
#             if any(span[0] < e[1] and span[1] > e[0] for e in email_spans):
#                 continue
#             if any(span[0] < t[1] and span[1] > t[0] for t in taken):
#                 continue
#             taken.append(span)
#             found.append(match)
#     return sorted(found, key=lambda m: m.start())


# def find_all_urls(text: str) -> List[str]:
#     """Return every URL-like substring found in `text` (e-mail domains excluded)."""
#     return [match.group(0).rstrip(".,;:)") for match in _url_matches(text)]


# def _extract_email(text: str) -> Optional[ExtractedField]:
#     match = _EMAIL_PATTERN.search(text)
#     if not match:
#         return None
#     return ExtractedField(
#         value=match.group(0).rstrip(".,;:"), confidence=ConfidenceLevel.HIGH,
#         source=match.group(0), method="pattern",
#     )


# def _extract_website(text: str) -> Optional[ExtractedField]:
#     matches = _url_matches(text)
#     if not matches:
#         return None
#     match = matches[0]
#     return ExtractedField(
#         value=match.group(0).rstrip(".,;:)"), confidence=ConfidenceLevel.HIGH,
#         source=match.group(0), method="pattern",
#     )


# # --------------------------------------------------------------------------- #
# # ID / credential numbers (only ever taken next to an ID-like label)
# # --------------------------------------------------------------------------- #

# _ID_LABELS: Dict[str, List[str]] = {
#     "student_id": [
#         r"(?:student|candidate|trainee|learner|participant|member|employee|applicant|delegate|intern)"
#         r"\s*(?:id|no\.?|number|code|#)",
#         r"roll\s*(?:no\.?|number|#)",
#         r"(?:registration|reg\.?|enrol+ment|admission|seat|hall\s*ticket|exam(?:ination)?)\s*(?:no\.?|number|id|#)",
#         r"(?:prn|usn|uid|uin)",
#     ],
#     "certificate_number": [
#         r"cert(?:ificate|\.)?\s*(?:no\.?|number|id|code|#)",
#         r"credential\s*(?:id|no\.?|number|code|#)",
#         r"serial\s*(?:no\.?|number|#)",
#         r"(?:reference|ref\.?)\s*(?:no\.?|number|id|#)?",
#         r"(?:document|doc\.?|diploma|licen[cs]e|verification|validation|unique|authenticity)"
#         r"\s*(?:no\.?|number|id|code|#)",
#     ],
# }

# _ID_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_.\-#]*")


# def _is_plausible_id(token: str) -> bool:
#     if len(token) < 3:
#         return False
#     if any(ch.isdigit() for ch in token):
#         return not _ANY_DATE_RE.fullmatch(token)
#     return token.isupper() and len(token) >= 6  # e.g. an all-letter code


# def _extract_id_field(text: str, labels: List[str]) -> Optional[ExtractedField]:
#     labeled = _extract_labeled_value(text, labels)
#     if labeled:
#         raw_value, source = labeled
#         token_match = _ID_TOKEN.match(raw_value)
#         if token_match:
#             token = token_match.group(0).strip(".,;:-/#")
#             if _is_plausible_id(token):
#                 return ExtractedField(value=token, confidence=ConfidenceLevel.HIGH, source=source, method="label")

#     # Loose form without a separator ("Roll No 20BCS045"): the token must
#     # contain a digit, which keeps ordinary words from being read as IDs.
#     loose = re.compile(
#         r"(?<![A-Za-z])" + _label_group(labels) + r"\s*[:#\-\u2013\u2014.]*\s*"
#         r"([A-Za-z0-9][A-Za-z0-9/_.\-]*\d[A-Za-z0-9/_.\-]*)",
#         re.IGNORECASE,
#     )
#     for line in text.split("\n"):
#         match = loose.search(line)
#         if match:
#             token = match.group(1).strip(".,;:-/")
#             if _is_plausible_id(token):
#                 return ExtractedField(
#                     value=token, confidence=ConfidenceLevel.MEDIUM,
#                     source=match.group(0).strip(), method="pattern",
#                 )
#     return None


# # --------------------------------------------------------------------------- #
# # Person names
# # --------------------------------------------------------------------------- #

# _PERSON_QUALIFIER = (
#     r"(?:student|candidate|recipient|participant|trainee|learner|awardee|holder|delegate|attendee|"
#     r"intern|employee|applicant|beneficiary|graduate|member|full)"
# )
# _QUALIFIED_NAME_LABELS = [
#     _PERSON_QUALIFIER + r"['\u2019]?s?\s*name",
#     r"name\s+of\s+(?:the\s+)?" + _PERSON_QUALIFIER,
#     r"awarded\s+to", r"presented\s+to", r"issued\s+to", r"granted\s+to",
# ]

# # Words that cannot be part of a person's name; used to reject sentence
# # fragments, organisation names and document titles.
# _NON_NAME_WORDS = frozenset(
#     """
#     certificate certification certified course training program programme workshop internship
#     university college institute institution school academy department faculty board
#     completion achievement participation excellence appreciation award awarded presented
#     this that the has have had is was are successfully hereby certify certifies
#     ltd limited pvt private inc llc solutions technologies technology systems services
#     foundation association society council trust centre center authority
#     degree diploma transcript marksheet grade marks
#     """.split()
# )

# _NAME_CUE_PATTERNS: List[Pattern[str]] = [
#     re.compile(r"\b(?:hereby\s+)?certif(?:y|ies)\s+that\b[\s:,\-]*", re.IGNORECASE),
#     re.compile(
#         r"\b(?:(?:conferred|bestowed)\s+(?:upon|on)|(?:presented|awarded|granted|issued|given)\s+to)\b[\s:,\-]*",
#         re.IGNORECASE,
#     ),
# ]

# _NAME_STOP = re.compile(
#     r"\s+(?:has|have|had|is|are|was|who|s/o|d/o|w/o|c/o|son|daughter|wife|bearing|holding|successfully|"
#     r"having|for|of|in|on|from|with|under|at|as|to|by|roll|reg(?:istration)?|enrol\w*)\b"
#     r"|\s*[,;:(]|\.(?=\s*$)|\.(?=\s+(?-i:[a-z]))|\s{2,}|\t",
#     re.IGNORECASE,
# )

# _COMPLETION_VERB_LINE = re.compile(
#     r"^(?:has|have|had|is|was|hereby)\b.{0,20}?\b"
#     r"(?:complet|attend|participat|pass|award|qualif|undergone|secur|achiev|been|success|earn)",
#     re.IGNORECASE,
# )


# def _looks_like_person_name(candidate: str, min_words: int = 1, require_case: bool = True) -> bool:
#     """
#     Heuristic filter against obviously wrong matches: a plausible name has
#     1-6 alphabetic words, no digits, no organisation / document vocabulary,
#     and is not entirely lowercase (which would be a sentence fragment).
#     """
#     candidate = candidate.strip()
#     if not candidate or len(candidate) > 60 or (require_case and candidate == candidate.lower()):
#         return False
#     if re.search(r"[:@/\\]", candidate):
#         return False
#     words = candidate.split()
#     if not (min_words <= len(words) <= 6):
#         return False
#     for word in words:
#         core = word.strip(".,'\u2019-")
#         if not core or not core[0].isalpha() or any(ch.isdigit() for ch in core):
#             return False
#         if core.lower() in _NON_NAME_WORDS:
#             return False
#     return True


# def _extract_generic_name_label(text: str, require_case: bool = True) -> Optional[ExtractedField]:
#     """A bare "Name: ..." label, accepted only at the start of a line so that
#     "Institution Name:" / "Father's Name:" are never read as the recipient."""
#     lines = text.split("\n")
#     pattern = re.compile(r"^[\d\W]*name\s*(?:[:\uFF1A]|\s[-\u2013\u2014]\s)\s*(.*)$", re.IGNORECASE)
#     gap = re.compile(r"^name(?:\t+|[ ]{2,})(\S.*)$", re.IGNORECASE)
#     for idx, raw in enumerate(lines):
#         line = raw.strip()
#         match = pattern.match(line) or gap.match(line)
#         if not match:
#             continue
#         value = _clean_value(_truncate_at_next_label(match.group(1)))
#         if not value:
#             nxt = _next_non_empty(lines, idx)
#             if nxt and not _LABEL_LIKE_LINE.match(nxt):
#                 value = _clean_value(nxt)
#         if value and _looks_like_person_name(value, require_case=require_case):
#             return ExtractedField(value=value, confidence=ConfidenceLevel.MEDIUM, source=line, method="label")
#     return None


# def _extract_recipient_name(text: str) -> Optional[ExtractedField]:
#     """
#     Strategies, strongest first:
#       1. a qualified label ("Student Name:", "Name of the Candidate")
#       2. a bare "Name:" line
#       3. certificate phrasing: "certify that <name> ...", "presented to <name>"
#          (the name may sit on the line after the cue)
#       4. layout: a name-like line directly above "has successfully completed ..."
#     """
#     # If OCR produced no capital letters at all, "not entirely lowercase" can no
#     # longer be used to filter sentence fragments.
#     require_case = text != text.lower()

#     labeled = _extract_labeled_value(text, _QUALIFIED_NAME_LABELS)
#     if labeled:
#         value, source = labeled
#         if _looks_like_person_name(value, require_case=require_case):
#             return ExtractedField(value=value, confidence=ConfidenceLevel.HIGH, source=source, method="label")

#     generic = _extract_generic_name_label(text, require_case=require_case)
#     if generic:
#         return generic

#     for cue in _NAME_CUE_PATTERNS:
#         for match in cue.finditer(text):
#             candidate = _phrase_after(text, match.end(), _NAME_STOP)
#             if _looks_like_person_name(candidate, require_case=require_case):
#                 return ExtractedField(
#                     value=candidate, confidence=ConfidenceLevel.MEDIUM,
#                     source=f"{match.group(0).strip()} {candidate}".strip(), method="context_phrase",
#                 )

#     lines = _non_empty_lines(text)
#     for idx in range(1, len(lines)):
#         if _COMPLETION_VERB_LINE.match(lines[idx]):
#             candidate = _clean_value(lines[idx - 1])
#             if _looks_like_person_name(candidate, min_words=2):
#                 return ExtractedField(
#                     value=candidate, confidence=ConfidenceLevel.MEDIUM,
#                     source=f"{lines[idx - 1]} / {lines[idx]}", method="context_phrase",
#                 )
#     return None


# # --------------------------------------------------------------------------- #
# # Titles and organisations
# # --------------------------------------------------------------------------- #

# _TITLE_KEYWORDS = re.compile(
#     r"\b(?:certificate|certification|diploma|degree|transcript|mark\s*sheet|marksheet|"
#     r"statement\s+of\s+marks|grade\s+(?:card|sheet)|report\s+card|award|credential|licen[cs]e|"
#     r"of\s+(?:completion|achievement|participation|appreciation|excellence|merit|training|"
#     r"internship|recognition|registration|qualification|accreditation))\b",
#     re.IGNORECASE,
# )
# _SENTENCE_WORDS = re.compile(
#     r"\b(?:is|are|was|has|have|had|hereby|awarded|presented|certify|certifies|successfully|"
#     r"completed|attended|will|shall)\b",
#     re.IGNORECASE,
# )


# def _extract_document_title(first_page_text: str) -> Optional[ExtractedField]:
#     """
#     Prefer a heading line that names a document kind ("CERTIFICATE OF
#     COMPLETION", "Statement of Marks"); a title split over two lines
#     ("CERTIFICATE" / "OF COMPLETION") is joined. Falls back to the first
#     line (LOW confidence) because letterhead often comes first.
#     """
#     lines = _non_empty_lines(first_page_text)
#     if not lines:
#         return None

#     for idx, line in enumerate(lines[:15]):
#         if len(line) > 100 or _LABEL_LIKE_LINE.match(line) or any(ch.isdigit() for ch in line):
#             continue
#         if _TITLE_KEYWORDS.search(line) and not _SENTENCE_WORDS.search(line):
#             title = line
#             if idx + 1 < len(lines) and re.match(r"^of\s+\w+", lines[idx + 1], re.IGNORECASE) \
#                     and len(lines[idx + 1].split()) <= 4 and not re.search(r"\bof\b", line, re.IGNORECASE):
#                 title = f"{line} {lines[idx + 1]}"
#             return ExtractedField(
#                 value=_clean_value(title), confidence=ConfidenceLevel.MEDIUM,
#                 source=title, method="heading_heuristic",
#             )

#     first_line = lines[0]
#     if 3 <= len(first_line) <= 100 and not _LABEL_LIKE_LINE.match(first_line) \
#             and sum(ch.isalpha() for ch in first_line) >= 3:
#         return ExtractedField(value=first_line, confidence=ConfidenceLevel.LOW, source=first_line, method="heading_heuristic")
#     return None


# _UNIVERSITY_WORDS = r"\buniversit(?:y|ies)\b|\bvishwavidyalaya\b|\bvidyapeeth\b"
# _INSTITUTION_WORDS = (
#     r"\b(?:institute|institution|college|school|academy|polytechnic|solutions?|technolog(?:y|ies)|"
#     r"systems|services|labs?|laboratories|ltd|limited|pvt|private|inc|llc|llp|corporation|corp|"
#     r"foundation|centre|center|association|society|council|trust|training|education(?:al)?|"
#     r"learning|consult\w*|enterprises|group|company|board)\b"
# )


# def _looks_like_org_heading(line: str) -> bool:
#     if not (2 <= len(line.split()) <= 12) or len(line) > 100:
#         return False
#     if _LABEL_LIKE_LINE.match(line) or _SENTENCE_WORDS.search(line) or _TITLE_KEYWORDS.search(line) \
#             or _ISSUER_CUE.match(line):
#         return False
#     if re.search(r"@|www\.|https?:", line, re.IGNORECASE):
#         return False
#     digits = sum(ch.isdigit() for ch in line)
#     return digits <= len(line) * 0.3


# def _extract_organization(text: str, heading_keyword_pattern: str, labels: List[str]) -> Optional[ExtractedField]:
#     """
#     An organisation name from (1) an explicit label, else (2) a heading-like
#     line among the first lines of the page that contains an organisation
#     keyword (letterheads rarely carry an "Institution:" label), else (3) the
#     same kind of line in the footer (LOW confidence).
#     """
#     labeled = _extract_labeled_field(text, labels, ConfidenceLevel.HIGH)
#     if labeled:
#         return labeled

#     keyword = re.compile(heading_keyword_pattern, re.IGNORECASE)
#     lines = _non_empty_lines(text)
#     for line in lines[:10]:
#         if keyword.search(line) and _looks_like_org_heading(line):
#             return ExtractedField(value=_clean_value(line), confidence=ConfidenceLevel.MEDIUM, source=line, method="heading_heuristic")
#     for line in lines[-6:] if len(lines) > 10 else []:
#         if keyword.search(line) and _looks_like_org_heading(line):
#             return ExtractedField(value=_clean_value(line), confidence=ConfidenceLevel.LOW, source=line, method="heading_heuristic")
#     return None


# def _extract_labeled_field(
#     text: str, labels: List[str], confidence: ConfidenceLevel, strip_quotes: bool = True
# ) -> Optional[ExtractedField]:
#     """Generic 'Label: value' extractor for simple free-text fields."""
#     labeled = _extract_labeled_value(text, labels)
#     if not labeled:
#         return None
#     value, source = labeled
#     cleaned = _clean_value(value, strip_quotes=strip_quotes)
#     if not cleaned:
#         return None
#     return ExtractedField(value=cleaned, confidence=confidence, source=source, method="label")


# _INSTITUTION_LABELS = [
#     r"institution(?:\s*name)?", r"institute(?:\s*name)?", r"college(?:\s*name)?", r"school(?:\s*name)?",
#     r"academy(?:\s*name)?", r"organi[sz]ation(?:\s*name)?", r"company(?:\s*name)?",
#     r"training\s*(?:provider|partner|cent(?:re|er)|institute)",
#     r"issuing\s*(?:authority|institution|organi[sz]ation)",
# ]
# _UNIVERSITY_LABELS = [r"university(?:\s*name)?", r"affiliated\s*(?:to|with)", r"awarding\s*(?:body|university)"]
# _COURSE_LABELS = [
#     r"course(?:\s*(?:name|title))?", r"program(?:me)?(?:\s*(?:name|title))?",
#     r"training(?:\s*(?:program(?:me)?|name|title|on))?", r"workshop(?:\s*(?:name|title))?", r"module",
# ]
# _DEGREE_LABELS = [r"degree", r"qualification"]
# _SPECIALIZATION_LABELS = [r"specialization", r"specialisation", r"major", r"stream", r"discipline"]
# _DEPARTMENT_LABELS = [r"department", r"dept\.?", r"branch", r"faculty"]
# _ISSUER_LABELS = [
#     r"issued\s*by", r"issuer", r"awarded\s*by", r"authori[sz]ed\s*signatory", r"signed\s*by",
#     r"approved\s*by", r"certified\s*by", r"signatory",
# ]
# _ISSUER_DESIGNATION_LABELS = [r"designation", r"position", r"role"]
# _LOCATION_LABELS = [
#     r"address", r"location", r"place\s*(?:&|and)\s*date", r"place(?:\s*of\s*(?:issue|training|examination))?",
#     r"city", r"venue", r"held\s*at",
# ]


# # --------------------------------------------------------------------------- #
# # Issuer: sentence cues and signature block
# # --------------------------------------------------------------------------- #

# _ISSUER_CUE = re.compile(
#     r"\b(?:(?:issued|awarded|presented|conducted|organi[sz]ed|offered|provided|delivered|certified|"
#     r"authori[sz]ed|accredited|approved)\s+by|in\s+(?:association|collaboration)\s+with|powered\s+by)\b[\s:\-]*",
#     re.IGNORECASE,
# )

# _DESIGNATION_WORDS = (
#     r"(?:director|principal|registrar|dean|controller|chairman|chairperson|chairwoman|chancellor|"
#     r"vice[- ]chancellor|president|vice[- ]president|ceo|cto|coo|cfo|founder|co[- ]?founder|manager|"
#     r"head|hod|professor|lecturer|instructor|trainer|mentor|coordinator|co-ordinator|secretary|"
#     r"signatory|examiner|officer|administrator|superintendent|convener|proprietor|partner|"
#     r"supervisor|in[- ]charge)"
# )
# _DESIGNATION_RE = re.compile(r"\b" + _DESIGNATION_WORDS + r"\b", re.IGNORECASE)


# def _segments(line: str) -> List[str]:
#     """Split a line at wide gaps (OCR of side-by-side signature columns)."""
#     return [seg.strip() for seg in re.split(r"\t+|\s{2,}", line) if seg.strip()]


# def _find_signature_block(text: str) -> Optional[Tuple[Optional[str], str, str]]:
#     """
#     Locate a signature block: a short designation line ("Director",
#     "Head of Department") with a person-like name directly above (or below)
#     it. Scans from the bottom of the page up. Returns
#     (name_or_None, designation, source_snippet).
#     """
#     lines = _non_empty_lines(text)
#     count = len(lines)
#     for idx in range(count - 1, -1, -1):
#         segments = _segments(lines[idx])
#         if not segments:
#             continue
#         candidate = segments[0]
#         if ":" in candidate or any(ch.isdigit() for ch in candidate):
#             continue
#         if len(candidate.split()) > 8 or _SENTENCE_WORDS.search(candidate) or not _DESIGNATION_RE.search(candidate):
#             continue

#         name: Optional[str] = None
#         for j in (idx - 1, idx + 1):
#             if 0 <= j < count:
#                 neighbour = _segments(lines[j])
#                 if neighbour and not _DESIGNATION_RE.search(neighbour[0]) \
#                         and _looks_like_person_name(neighbour[0], min_words=2):
#                     name = _clean_value(neighbour[0])
#                     break
#         if name or idx >= count // 2:
#             source = f"{name} / {candidate}" if name else candidate
#             return name, _clean_value(candidate), source
#     return None


# def _extract_issuer_name(text: str) -> Optional[ExtractedField]:
#     labeled = _extract_labeled_field(text, _ISSUER_LABELS, ConfidenceLevel.HIGH)
#     if labeled:
#         return labeled
#     block = _find_signature_block(text)
#     if block and block[0]:
#         return ExtractedField(value=block[0], confidence=ConfidenceLevel.MEDIUM, source=block[2], method="signature_block")
#     for match in _ISSUER_CUE.finditer(text):
#         phrase = re.sub(r"^(?:the|our)\s+", "", _phrase_after(text, match.end()), flags=re.IGNORECASE)
#         if 3 <= len(phrase) <= 80 and phrase[0].isalpha() and not _PHRASE_LEADING_STOP.match(phrase):
#             return ExtractedField(
#                 value=phrase, confidence=ConfidenceLevel.MEDIUM,
#                 source=f"{match.group(0).strip()} {phrase}", method="context_phrase",
#             )
#     return None


# def _extract_issuer_designation(text: str) -> Optional[ExtractedField]:
#     labeled = _extract_labeled_field(text, _ISSUER_DESIGNATION_LABELS, ConfidenceLevel.HIGH)
#     if labeled:
#         return labeled
#     block = _find_signature_block(text)
#     if block:
#         return ExtractedField(value=block[1], confidence=ConfidenceLevel.MEDIUM, source=block[2], method="signature_block")
#     return None


# # --------------------------------------------------------------------------- #
# # Course, degree, specialization
# # --------------------------------------------------------------------------- #

# _COURSE_KIND = (
#     r"(?:course|training|program(?:me)?|workshop|internship|module|bootcamp|seminar|"
#     r"certification|webinar|class(?:es)?)"
# )
# _COURSE_CUE = re.compile(
#     r"(?:successfully\s+)?(?:complet(?:ed|ing|ion\s+of)|attend(?:ed|ing)|undergone|undergoing|"
#     r"participat(?:ed|ing)\s+in|passed|cleared|qualified\s+in|enrolled\s+in|pursu(?:ed|ing))\s+"
#     r"(?:the\s+|a\s+|an\s+|our\s+|her\s+|his\s+|their\s+|this\s+)?"
#     r"(?:(?:(?:online|offline|professional|certification|certificate|training|short[- ]term|internship)\s+)*"
#     + _COURSE_KIND + r"\s*(?:on|in|of|titled|entitled|named|called|for)?\s*[:\-]?\s*)?"
#     r"[\"\u201c'\u2018]?",
#     re.IGNORECASE,
# )


# def _plausible_title_phrase(phrase: str) -> bool:
#     if not (3 <= len(phrase) <= 120) or not phrase[0].isalpha():
#         return False
#     if _PHRASE_LEADING_STOP.match(phrase) or _ANY_DATE_RE.fullmatch(phrase):
#         return False
#     return sum(ch.isalpha() for ch in phrase) >= 3


# def _extract_course_name(text: str) -> Optional[ExtractedField]:
#     labeled = _extract_labeled_field(text, _COURSE_LABELS, ConfidenceLevel.HIGH)
#     if labeled and _plausible_title_phrase(labeled.value):
#         return labeled
#     for match in _COURSE_CUE.finditer(text):
#         phrase = _phrase_after(text, match.end())
#         if _plausible_title_phrase(phrase):
#             return ExtractedField(
#                 value=phrase, confidence=ConfidenceLevel.MEDIUM,
#                 source=_WHITESPACE.sub(" ", f"{match.group(0).strip()} {phrase}"), method="context_phrase",
#             )
#     return None


# _DEGREE_FULL = re.compile(
#     r"\b((?:(?:Post[- ]?Graduate|Advanced)[ \t]+)?(?:Bachelor|Master|Doctor|Associate|Diploma)(?:'s|s)?[ \t]+(?:of|in)[ \t]+[A-Za-z&]+"
#     r"(?:[ \t]+(?:and|&|of)[ \t]+[A-Za-z&]+"
#     r"|[ \t]+(?!in\b|with\b|from\b|at\b|on\b|by\b|has\b|having\b|under\b|specializ)[A-Za-z&]+){0,2})"
#     r"(?:[ \t]*\(([^)\n]{2,60})\)"
#     r"|[ \t]+(?:in|with[ \t]+(?:a[ \t]+)?(?:major|specializ\w+)[ \t]+in|specializ\w+[ \t]+in)[ \t]+"
#     r"([A-Za-z&' \-]{2,60}?)(?=[ \t]*(?:[,;.(\n]|\bfrom\b|\bat\b|\bwith\b|\bon\b|\bby\b|\bhas\b|\bhaving\b|\bunder\b|$)))?",
#     re.IGNORECASE,
# )
# _DEGREE_ABBR = re.compile(
#     r"(?<![A-Za-z.])((?:B\.?[ ]?Tech|M\.?[ ]?Tech|B\.?[ ]?Sc|M\.?[ ]?Sc|B\.?[ ]?Com|M\.?[ ]?Com|"
#     r"B\.?[ ]?Ed|M\.?[ ]?Ed|B\.?[ ]?Arch|B\.?[ ]?Pharm|M\.?[ ]?Pharm|B\.?[ ]?Des|"
#     r"B\.E|M\.E|B\.A|M\.A|B\.S|M\.S|Ph\.?[ ]?D|MBA|BBA|BCA|MCA|LL\.?B|LL\.?M|MBBS)\.?)(?![A-Za-z])"
#     r"(?:[ \t]*\(([^)\n]{2,60})\)"
#     r"|[ \t]+in[ \t]+([A-Za-z&' \-]{2,60}?)(?=[ \t]*(?:[,;.(\n]|from\b|at\b|with\b|on\b|$)))?"
# )
# _ABBREVIATION_ONLY = re.compile(r"^[A-Z.]{2,8}$")


# def _scan_degree(text: str) -> Optional[Tuple[str, Optional[str], str]]:
#     """Find a degree in prose; returns (degree, specialization_or_None, source)."""
#     for pattern in (_DEGREE_FULL, _DEGREE_ABBR):
#         match = pattern.search(text)
#         if not match:
#             continue
#         degree = _clean_value(match.group(1))
#         spec_raw = match.group(3) or match.group(2)
#         specialization = None
#         if spec_raw:
#             spec_clean = _clean_value(spec_raw)
#             if spec_clean and not _ABBREVIATION_ONLY.match(spec_clean):
#                 specialization = spec_clean
#         return degree, specialization, _WHITESPACE.sub(" ", match.group(0)).strip()
#     return None


# def _extract_degree_name(text: str) -> Optional[ExtractedField]:
#     labeled = _extract_labeled_field(text, _DEGREE_LABELS, ConfidenceLevel.HIGH)
#     if labeled and _plausible_title_phrase(labeled.value):
#         return labeled
#     found = _scan_degree(text)
#     if found:
#         return ExtractedField(value=found[0], confidence=ConfidenceLevel.MEDIUM, source=found[2], method="context_phrase")
#     return None


# def _extract_specialization(text: str) -> Optional[ExtractedField]:
#     labeled = _extract_labeled_field(text, _SPECIALIZATION_LABELS, ConfidenceLevel.HIGH)
#     if labeled:
#         return labeled
#     found = _scan_degree(text)
#     if found and found[1]:
#         return ExtractedField(value=found[1], confidence=ConfidenceLevel.MEDIUM, source=found[2], method="context_phrase")
#     return None


# # --------------------------------------------------------------------------- #
# # Academic values: CGPA/GPA, percentage, marks, grade
# # --------------------------------------------------------------------------- #

# def _extract_cgpa(text: str) -> Optional[ExtractedField]:
#     match = re.search(
#         r"\b(?:CGPA|SGPA|GPA|CPI|SPI|grade\s+point\s+average)\b\s*[:\-=]?\s*(?:of\s+|is\s+)?"
#         r"(\d+(?:\.\d+)?)(?:\s*(?:/|out\s+of)\s*(\d+(?:\.\d+)?))?",
#         text, re.IGNORECASE,
#     )
#     if not match:
#         return None
#     value = match.group(1) if not match.group(2) else f"{match.group(1)}/{match.group(2)}"
#     return ExtractedField(value=value, confidence=ConfidenceLevel.HIGH, source=match.group(0).strip(), method="pattern")


# def _extract_percentage(text: str) -> Optional[ExtractedField]:
#     labeled_match = re.search(r"\b(?:percentage|aggregate)\b\s*[:\-]?\s*(\d{1,3}(?:\.\d+)?)\s*(?:%|per\s*cent|percent)?", text, re.IGNORECASE)
#     if labeled_match and float(labeled_match.group(1)) <= 100:
#         return ExtractedField(
#             value=f"{labeled_match.group(1)}%", confidence=ConfidenceLevel.HIGH,
#             source=labeled_match.group(0).strip(), method="label",
#         )
#     bare_match = re.search(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*(?:%|per\s*cent\b|percent\b)", text, re.IGNORECASE)
#     if bare_match and float(bare_match.group(1)) <= 100:
#         return ExtractedField(
#             value=f"{bare_match.group(1)}%", confidence=ConfidenceLevel.MEDIUM,
#             source=bare_match.group(0).strip(), method="pattern",
#         )
#     return None


# _FRACTION = r"(\d+(?:\.\d+)?\s*(?:/|out\s+of)\s*\d+(?:\.\d+)?)"


# def _extract_marks(text: str) -> Optional[ExtractedField]:
#     patterns = [
#         # "Total Marks: 452/600" - preferred over per-subject marks
#         r"\btotal(?:\s+marks)?(?:\s+(?:obtained|secured))?\b\s*[:\-]?\s*" + _FRACTION,
#         r"\bmarks(?:\s+(?:obtained|secured))?\b\s*[:\-]?\s*" + _FRACTION,
#         r"\b(?:secured|obtained|scored|awarded)\b\s*[:\-]?\s*" + _FRACTION,
#         # bare number only next to an explicit "marks" label
#         r"\b(?:total\s+)?marks(?:\s+(?:obtained|secured))?\b\s*[:\-]\s*(\d+(?:\.\d+)?)(?!\s*(?:%|st\b|nd\b|rd\b|th\b))",
#     ]
#     for pattern in patterns:
#         match = re.search(pattern, text, re.IGNORECASE)
#         if match:
#             confidence = ConfidenceLevel.HIGH if re.search(r"[:\-]", match.group(0)) else ConfidenceLevel.MEDIUM
#             return ExtractedField(
#                 value=_WHITESPACE.sub("", match.group(1)) if "/" in match.group(1) else _WHITESPACE.sub(" ", match.group(1)).strip(),
#                 confidence=confidence, source=match.group(0).strip(), method="label",
#             )
#     return None


# def _extract_grade(text: str) -> Optional[ExtractedField]:
#     match = re.search(
#         r"\b(?:final\s+|overall\s+|letter\s+)?grade\b\s*[:\-=]?\s*(?:of\s+|is\s+)?((?-i:[A-F][+\-]?|O|S))(?![A-Za-z])",
#         text, re.IGNORECASE,
#     )
#     if match:
#         return ExtractedField(value=match.group(1), confidence=ConfidenceLevel.HIGH, source=match.group(0).strip(), method="label")

#     descriptive = re.search(
#         r"(?<![A-Za-z])(?:grade|result|classification|class|division|performance|remarks?)\s*[:\-\u2013]\s*"
#         r"([A-Za-z][A-Za-z +\-]{1,30})",
#         text, re.IGNORECASE,
#     )
#     if descriptive:
#         value = _clean_value(re.split(r"\s{2,}|\t", descriptive.group(1))[0])
#         if value:
#             return ExtractedField(value=value, confidence=ConfidenceLevel.HIGH, source=descriptive.group(0).strip(), method="label")

#     sentence = re.search(
#         r"\b(?:with|in|achiev\w*|secur\w*|obtain\w*|awarded|passed\s+with)\s+"
#         r"((?:first|second|third|1st|2nd)\s+(?:class|division)(?:\s+with\s+distinction)?|distinction|"
#         r"honou?rs?|high(?:est)?\s+distinction|merit|(?:summa\s+|magna\s+)?cum\s+laude)\b",
#         text, re.IGNORECASE,
#     )
#     if sentence:
#         return ExtractedField(
#             value=sentence.group(1), confidence=ConfidenceLevel.MEDIUM,
#             source=sentence.group(0).strip(), method="context_phrase",
#         )
#     return None


# def _extract_location(text: str) -> Optional[ExtractedField]:
#     found = _extract_labeled_field(text, _LOCATION_LABELS, ConfidenceLevel.HIGH, strip_quotes=False)
#     if not found:
#         return None
#     without_dates = _clean_value(_ANY_DATE_RE.sub("", found.value))
#     if not without_dates:
#         return None
#     found.value = without_dates
#     return found


# # --------------------------------------------------------------------------- #
# # Document type
# # --------------------------------------------------------------------------- #

# # Checked in order; the first rule that matches wins. Specific kinds come
# # before the generic "certificate" catch-all.
# _DOCUMENT_TYPE_RULES: List[Tuple[DocumentType, Pattern[str]]] = [
#     (DocumentType.MARKSHEET, re.compile(
#         r"mark\s*sheet|statement\s+of\s+marks|grade\s+(?:card|sheet)|report\s+card|marks\s+memo", re.I)),
#     (DocumentType.TRANSCRIPT, re.compile(r"transcript", re.I)),
#     (DocumentType.DIPLOMA, re.compile(r"diploma", re.I)),
#     (DocumentType.DEGREE, re.compile(
#         r"degree\s+(?:of|certificate)|bachelor(?:'s)?\s+(?:of|in)|master(?:'s)?\s+(?:of|in)|"
#         r"doctor(?:ate)?\s+of|\bph\.?\s?d\b|\bb\.?\s?tech\b|\bm\.?\s?tech\b|\bb\.?\s?sc\b|\bm\.?\s?sc\b", re.I)),
#     (DocumentType.TRAINING_CERTIFICATE, re.compile(
#         r"training|internship|workshop|bootcamp|seminar|webinar|course\s+completion|"
#         r"certificate\s+of\s+(?:completion|participation)|successfully\s+completed", re.I)),
#     (DocumentType.AWARD, re.compile(
#         r"\baward\b|\bprize\b|\bmedal\b|scholarship|appreciation|recognition|excellence|"
#         r"achievement|\bmerit\b|\bwinner\b|runner[- ]up", re.I)),
#     (DocumentType.CREDENTIAL, re.compile(r"credential|licen[cs]e|accreditation|\bbadge\b", re.I)),
#     (DocumentType.CERTIFICATE, re.compile(r"certificat|certif(?:y|ies|ied|ication)", re.I)),
# ]


# def _classify_document_type(text: str, title: Optional[str] = None) -> ExtractedField:
#     """
#     Classify with keyword rules. A heading that names a document kind is
#     consulted first (it is far more reliable than words that merely occur in
#     the body, and an organisation name such as "... Training Solutions" must
#     not decide the type), then the full text. Falls back to UNKNOWN.
#     """
#     if title:
#         for doc_type, pattern in _DOCUMENT_TYPE_RULES[:-1]:
#             match = pattern.search(title)
#             if match:
#                 return ExtractedField(value=doc_type.value, confidence=ConfidenceLevel.MEDIUM, source=match.group(0), method="keyword")
#     for doc_type, pattern in _DOCUMENT_TYPE_RULES:
#         match = pattern.search(text)
#         if match:
#             return ExtractedField(value=doc_type.value, confidence=ConfidenceLevel.MEDIUM, source=match.group(0), method="keyword")
#     return ExtractedField(value=DocumentType.UNKNOWN.value, confidence=ConfidenceLevel.LOW, source=None, method="default")


# # --------------------------------------------------------------------------- #
# # Field extractor registry (page-scoped; title/type/extras handled separately)
# # --------------------------------------------------------------------------- #

# _FIELD_EXTRACTORS: Dict[str, Callable[[str], Optional[ExtractedField]]] = {
#     "recipient_name": _extract_recipient_name,
#     "student_id": lambda t: _extract_id_field(t, _ID_LABELS["student_id"]),
#     "certificate_number": lambda t: _extract_id_field(t, _ID_LABELS["certificate_number"]),
#     "institution_name": lambda t: _extract_organization(t, _INSTITUTION_WORDS, _INSTITUTION_LABELS),
#     "university_name": lambda t: _extract_organization(t, _UNIVERSITY_WORDS, _UNIVERSITY_LABELS),
#     "issuer_name": _extract_issuer_name,
#     "issuer_designation": _extract_issuer_designation,
#     "course_name": _extract_course_name,
#     "degree_name": _extract_degree_name,
#     "specialization": _extract_specialization,
#     "department": lambda t: _extract_labeled_field(t, _DEPARTMENT_LABELS, ConfidenceLevel.HIGH),
#     "issue_date": _extract_issue_date,
#     "start_date": _extract_start_date,
#     "completion_date": _extract_completion_date,
#     "expiry_date": _extract_expiry_date,
#     "grade": _extract_grade,
#     "marks": _extract_marks,
#     "percentage": _extract_percentage,
#     "cgpa": _extract_cgpa,
#     "email": _extract_email,
#     "website": _extract_website,
#     "location": _extract_location,
# }


# # --------------------------------------------------------------------------- #
# # Additional (unmodelled) labelled fields
# # --------------------------------------------------------------------------- #

# def _all_known_label_regexes() -> List[str]:
#     known: List[str] = []
#     for group in _DATE_LABELS.values():
#         known.extend(group)
#     for group in _ID_LABELS.values():
#         known.extend(group)
#     for group in (
#         _QUALIFIED_NAME_LABELS, _INSTITUTION_LABELS, _UNIVERSITY_LABELS, _COURSE_LABELS, _DEGREE_LABELS,
#         _SPECIALIZATION_LABELS, _DEPARTMENT_LABELS, _ISSUER_LABELS, _ISSUER_DESIGNATION_LABELS,
#         _LOCATION_LABELS, _PLAIN_DATE_LABELS,
#     ):
#         known.extend(group)
#     known.extend([r"name", r"cgpa|sgpa|gpa|cpi|spi", r"percentage|aggregate", r"(?:total\s+)?marks(?:\s+(?:obtained|secured))?",
#                   r"(?:final\s+|overall\s+|letter\s+)?grade|result|classification|class|division|performance|remarks?",
#                   r"e-?mail|website|web|url|http|https"])
#     return known


# _KNOWN_LABEL_RE = re.compile("^(?:" + "|".join("(?:" + p + ")" for p in _all_known_label_regexes()) + ")$", re.IGNORECASE)
# _ANY_LABELED_LINE = re.compile(r"^[\d\W]*([A-Za-z][A-Za-z .()/&']{1,34}?)\s*:\s*(\S.{0,150})$")
# _MAX_ADDITIONAL_FIELDS = 20


# def _extract_additional_info(pages: List[Tuple[Optional[int], str]]) -> Dict[str, ExtractedField]:
#     """Keep 'Label: value' lines whose label the schema does not model."""
#     extras: Dict[str, ExtractedField] = {}
#     for page_number, page_text in pages:
#         for raw_line in page_text.split("\n"):
#             line = raw_line.strip()
#             match = _ANY_LABELED_LINE.match(line)
#             if not match:
#                 continue
#             label = _WHITESPACE.sub(" ", match.group(1)).strip(" .")
#             value = _clean_value(_truncate_at_next_label(match.group(2)))
#             if not value or value.startswith("//") or len(label.split()) > 4:
#                 continue
#             if _KNOWN_LABEL_RE.match(label):
#                 continue
#             key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
#             if not key or key in extras:
#                 continue
#             extras[key] = ExtractedField(value=value, confidence=ConfidenceLevel.HIGH, source=line, method="label", page=page_number)
#             if len(extras) >= _MAX_ADDITIONAL_FIELDS:
#                 return extras
#     return extras


# # --------------------------------------------------------------------------- #
# # Candidate selection, confidence
# # --------------------------------------------------------------------------- #

# def _select_best_candidate(
#     candidates: List[ExtractedField], field_name: str, warnings: List[str]
# ) -> Optional[ExtractedField]:
#     """
#     Choose the best candidate across pages: highest confidence wins, ties go to
#     the earliest page. If pages disagree at the top tier, a warning is recorded
#     instead of silently hiding the discrepancy.
#     """
#     if not candidates:
#         return None

#     top_rank = max(_CONFIDENCE_RANK.get(c.confidence, 0) for c in candidates)
#     top_candidates = [c for c in candidates if _CONFIDENCE_RANK.get(c.confidence, 0) == top_rank]
#     distinct_values = sorted({c.value for c in top_candidates})

#     if len(distinct_values) > 1:
#         warnings.append(
#             f"Multiple differing values found for '{field_name}' across pages "
#             f"({', '.join(distinct_values)}); using the first occurrence."
#         )
#     return top_candidates[0]


# def _is_detected(name: str, extracted: Optional[ExtractedField]) -> bool:
#     """An 'unknown' document type is a placeholder, not a detection."""
#     if extracted is None:
#         return False
#     return not (name == "document_type" and extracted.value == DocumentType.UNKNOWN.value)


# def _compute_overall_confidence(document_info: ExtractedDocumentInfo) -> Optional[ConfidenceLevel]:
#     ranks = [
#         _CONFIDENCE_RANK[extracted.confidence]
#         for name in _SCHEMA_FIELD_NAMES
#         if _is_detected(name, extracted := getattr(document_info, name))
#     ]
#     if not ranks:
#         return None
#     average = sum(ranks) / len(ranks)
#     if average >= 2.5:
#         return ConfidenceLevel.HIGH
#     if average >= 1.5:
#         return ConfidenceLevel.MEDIUM
#     return ConfidenceLevel.LOW


# _DATE_FIELD_NAMES = ("issue_date", "start_date", "completion_date", "expiry_date")


# def _apply_document_level_rules(
#     document_info: ExtractedDocumentInfo, cleaned_text: str, warnings: List[str]
# ) -> None:
#     """Cross-field clean-up that needs the whole document."""
#     # The signing authority is not the recipient.
#     issuer, recipient = document_info.issuer_name, document_info.recipient_name
#     if issuer and recipient and issuer.value.lower() == recipient.value.lower():
#         document_info.issuer_name = None

#     # Weak fallback: exactly one date in the whole document and no date field
#     # found -> most likely the issue date (LOW confidence, clearly flagged).
#     if not any(getattr(document_info, name) for name in _DATE_FIELD_NAMES):
#         distinct_dates = {d.lower() for d in find_all_dates(cleaned_text)}
#         if len(distinct_dates) == 1:
#             date_str = find_all_dates(cleaned_text)[0]
#             document_info.issue_date = ExtractedField(
#                 value=date_str, confidence=ConfidenceLevel.LOW,
#                 source=date_str, method="single_date_fallback",
#             )
#             warnings.append("Only one unlabelled date was found; it was assumed to be the issue date (low confidence).")


# # --------------------------------------------------------------------------- #
# # Public API
# # --------------------------------------------------------------------------- #

# def extract_information(cleaned_text: Optional[str]) -> ExtractionResult:
#     """
#     Extract structured academic-document information from cleaned OCR/typed
#     text using deterministic rules only.

#     Args:
#         cleaned_text: Cleaned text (single page, or several pages separated by
#             "----- Page N -----" markers).

#     Returns:
#         An `ExtractionResult`. Fields that could not be found are `None`.
#         `status` is:
#             "empty"   - no text given
#             "failed"  - text given but no field could be identified
#             "success" - no errors, and the core fields were found (document type,
#                         a recipient, an issuing organisation/person, and a date)
#             "partial" - anything in between

#     Raises:
#         InvalidInputError: If `cleaned_text` is None or not a string.
#         InformationExtractionError: On any other unexpected failure.
#     """
#     try:
#         if cleaned_text is None:
#             raise InvalidInputError("cleaned_text is None; expected a string.")
#         if not isinstance(cleaned_text, str):
#             raise InvalidInputError(f"cleaned_text must be a string, got {type(cleaned_text).__name__}.")

#         if not cleaned_text.strip():
#             logger.warning("Received empty cleaned text; nothing to extract.")
#             return ExtractionResult(
#                 document_info=ExtractedDocumentInfo(),
#                 status="empty",
#                 warnings=["Cleaned text is empty; no extraction was performed."],
#                 errors=[],
#                 statistics=ExtractionStatistics(),
#                 overall_confidence=None,
#                 cleaned_text=cleaned_text,
#             )

#         warnings: List[str] = []
#         errors: List[str] = []
#         stats = ExtractionStatistics()

#         pages = _split_pages(cleaned_text)
#         stats.pages_processed = len(pages)
#         document_info = ExtractedDocumentInfo()

#         # Run every page-scoped extractor on every page, then pick the best
#         # candidate so one page never silently overwrites another.
#         for field_name, extractor in _FIELD_EXTRACTORS.items():
#             candidates: List[ExtractedField] = []
#             for page_number, page_text in pages:
#                 if not page_text.strip():
#                     continue
#                 try:
#                     result = extractor(page_text)
#                 except Exception as exc:  # noqa: BLE001 - one field must never break the whole run
#                     logger.warning("Extractor for '%s' failed on page %s: %s", field_name, page_number, exc)
#                     errors.append(f"Extractor for '{field_name}' failed on page {page_number}: {exc}")
#                     continue
#                 if result is not None:
#                     result.page = page_number
#                     candidates.append(result)
#             setattr(document_info, field_name, _select_best_candidate(candidates, field_name, warnings))

#         first_page_text = pages[0][1] if pages else ""
#         try:
#             document_info.document_title = _extract_document_title(first_page_text)
#         except Exception as exc:  # noqa: BLE001
#             logger.warning("Document title extraction failed: %s", exc)
#             errors.append(f"Document title extraction failed: {exc}")
#         if document_info.document_title is not None:
#             document_info.document_title.page = pages[0][0]

#         try:
#             title = document_info.document_title
#             title_text = title.value if title and title.confidence != ConfidenceLevel.LOW else None
#             document_info.document_type = _classify_document_type(cleaned_text, title_text)
#         except Exception as exc:  # noqa: BLE001
#             logger.warning("Document type classification failed: %s", exc)
#             errors.append(f"Document type classification failed: {exc}")

#         try:
#             document_info.additional_info = _extract_additional_info(pages)
#         except Exception as exc:  # noqa: BLE001
#             logger.warning("Additional-info extraction failed: %s", exc)
#             errors.append(f"Additional-info extraction failed: {exc}")

#         try:
#             _apply_document_level_rules(document_info, cleaned_text, warnings)
#         except Exception as exc:  # noqa: BLE001
#             logger.warning("Document-level rules failed: %s", exc)
#             errors.append(f"Document-level rules failed: {exc}")

#         # Input-quality hints: extraction cannot outperform the OCR text.
#         non_empty = _non_empty_lines(cleaned_text)
#         letters = sum(ch.isalpha() for ch in cleaned_text)
#         if len(non_empty) < 4 or letters < 60:
#             warnings.append(
#                 f"Very little text was provided ({len(non_empty)} non-empty line(s), {letters} letters); "
#                 "if the document has more content, check the OCR / text-cleaning stages."
#             )
#         if document_info.document_type is not None and document_info.document_type.value == DocumentType.UNKNOWN.value:
#             warnings.append("No document-type keywords (certificate, diploma, marksheet, award, ...) were found in the text.")

#         detected = [_is_detected(name, getattr(document_info, name)) for name in _SCHEMA_FIELD_NAMES]
#         stats.fields_detected = sum(detected)
#         stats.fields_not_detected = len(detected) - stats.fields_detected
#         stats.dates_detected = len(find_all_dates(cleaned_text))
#         stats.emails_detected = len(find_all_emails(cleaned_text))
#         stats.urls_detected = len(find_all_urls(cleaned_text))
#         stats.ids_detected = sum(
#             1 for value in (document_info.student_id, document_info.certificate_number) if value is not None
#         )

#         overall_confidence = _compute_overall_confidence(document_info)

#         has_type = _is_detected("document_type", document_info.document_type)
#         has_party = any(
#             getattr(document_info, name) is not None
#             for name in ("institution_name", "university_name", "issuer_name")
#         )
#         has_date = any(getattr(document_info, name) is not None for name in _DATE_FIELD_NAMES)
#         if stats.fields_detected == 0:
#             status = "failed"
#             warnings.append("No recognizable fields could be extracted from the provided text.")
#         elif not errors and has_type and document_info.recipient_name and has_party and has_date:
#             status = "success"
#         else:
#             status = "partial"

#         logger.info(
#             "Information extraction complete: status=%s, fields_detected=%d/%d, overall_confidence=%s.",
#             status, stats.fields_detected, len(detected), overall_confidence,
#         )

#         return ExtractionResult(
#             document_info=document_info,
#             status=status,
#             warnings=warnings,
#             errors=errors,
#             statistics=stats,
#             overall_confidence=overall_confidence,
#             cleaned_text=cleaned_text,
#         )

#     except InvalidInputError:
#         raise
#     except InformationExtractionError:
#         raise
#     except Exception as exc:  # noqa: BLE001
#         logger.exception("Unexpected error during information extraction")
#         raise InformationExtractionError(f"Unexpected error during information extraction: {exc}") from exc


# def extract_information_from_file(path: Path) -> ExtractionResult:
#     """
#     Convenience wrapper: read UTF-8 cleaned text from `path` and run
#     `extract_information` on it.

#     Raises:
#         InvalidInputError: If the file does not exist, is not a file, or
#             cannot be decoded as UTF-8.
#         InformationExtractionError: If the file cannot be read for any
#             other reason.
#     """
#     if not isinstance(path, Path):
#         path = Path(path)

#     if not path.exists() or not path.is_file():
#         raise InvalidInputError(f"Input text file does not exist: {path}")

#     try:
#         text = path.read_text(encoding="utf-8")
#     except UnicodeDecodeError as exc:
#         raise InvalidInputError(f"Failed to decode file as UTF-8: {path}") from exc
#     except OSError as exc:
#         raise InformationExtractionError(f"Failed to read input file: {path}") from exc

#     return extract_information(text)


# __all__ = [
#     "InformationExtractionError",
#     "InvalidInputError",
#     "ConfidenceLevel",
#     "DocumentType",
#     "ExtractedField",
#     "ExtractedDocumentInfo",
#     "ExtractionStatistics",
#     "ExtractionResult",
#     "find_all_dates",
#     "find_all_emails",
#     "find_all_urls",
#     "extract_information",
#     "extract_information_from_file",
# ]




"""
information_extraction.py
=========================

Deterministic (rule-based) extraction of structured fields from the cleaned
text of academic / training documents: certificates, degrees, diplomas,
mark sheets, transcripts, awards, credentials.

Design principles
-----------------
* NOTHING is tied to one specific document. There are no institution names,
  person names, course names, or fixed strings from any sample document.
  The module only knows about *document structure*: labels ("Roll No:"),
  certificate phrasing ("This is to certify that ..."), layout (a name on the
  line after a cue, a designation under a signature), and value shapes
  (dates, e-mails, URLs, IDs).
* Several independent strategies are tried per field, strongest first
  (explicit label -> sentence pattern -> layout heuristic), and the strategy
  used is recorded in `ExtractedField.method`, together with a confidence
  level and the source snippet.
* Values are copied verbatim from the text (only boundaries are tidied);
  OCR text is never "corrected" and nothing is invented.
* A field that cannot be found stays `None`. Unrecognised "Label: value"
  lines are kept in `additional_info` instead of being thrown away.
* Every extractor is isolated: one failure never breaks the whole run.

Public API (unchanged): `extract_information`, `extract_information_from_file`,
`find_all_dates`, `find_all_emails`, `find_all_urls` and the result dataclasses.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Pattern, Tuple

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

class InformationExtractionError(Exception):
    """Base exception for all information-extraction failures."""


class InvalidInputError(InformationExtractionError):
    """Raised when the input to `extract_information` is invalid."""


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class ConfidenceLevel(str, Enum):
    """
    Heuristic confidence in an extracted field (NOT a calibrated probability):

        HIGH   -> explicit label ("Student ID: ...") or an unambiguous
                  pattern (e-mail, labelled date / ID).
        MEDIUM -> a sentence pattern or document-structure heuristic
                  ("presented to <name>", a heading line, a signature block).
        LOW    -> weak best-effort guess (e.g. first line used as a title,
                  the only date in the document assumed to be the issue date).
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DocumentType(str, Enum):
    """Coarse document categories; existing academic values are preserved."""

    CERTIFICATE = "certificate"
    TRAINING_CERTIFICATE = "training_certificate"
    DEGREE = "degree"
    DIPLOMA = "diploma"
    MARKSHEET = "marksheet"
    TRANSCRIPT = "transcript"
    AWARD = "award"
    CREDENTIAL = "credential"
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    ID_CARD = "id_card"
    INVOICE = "invoice"
    BANK_STATEMENT = "bank_statement"
    EMPLOYMENT_LETTER = "employment_letter"
    LEGAL_DOCUMENT = "legal_document"
    MEDICAL_DOCUMENT = "medical_document"
    INSURANCE_DOCUMENT = "insurance_document"
    OTHER = "other"
    UNKNOWN = "unknown"


_CONFIDENCE_RANK: Dict[ConfidenceLevel, int] = {
    ConfidenceLevel.HIGH: 3,
    ConfidenceLevel.MEDIUM: 2,
    ConfidenceLevel.LOW: 1,
}


# --------------------------------------------------------------------------- #
# Result structures
# --------------------------------------------------------------------------- #

@dataclass
class ExtractedField:
    """A single extracted value, together with its provenance."""

    value: str
    confidence: ConfidenceLevel
    source: Optional[str] = None   # the text snippet the value came from
    method: Optional[str] = None   # label | context_phrase | pattern | keyword | heading_heuristic | ...
    page: Optional[int] = None     # 1-indexed page number, if known


@dataclass
class ExtractedDocumentInfo:
    """Structured fields extracted from any document; academic fields remain backward compatible."""

    document_title: Optional[ExtractedField] = None
    document_type: Optional[ExtractedField] = None
    recipient_name: Optional[ExtractedField] = None
    student_id: Optional[ExtractedField] = None
    certificate_number: Optional[ExtractedField] = None
    institution_name: Optional[ExtractedField] = None
    university_name: Optional[ExtractedField] = None
    issuer_name: Optional[ExtractedField] = None
    issuer_designation: Optional[ExtractedField] = None
    course_name: Optional[ExtractedField] = None
    degree_name: Optional[ExtractedField] = None
    specialization: Optional[ExtractedField] = None
    department: Optional[ExtractedField] = None
    issue_date: Optional[ExtractedField] = None
    start_date: Optional[ExtractedField] = None
    completion_date: Optional[ExtractedField] = None
    expiry_date: Optional[ExtractedField] = None
    grade: Optional[ExtractedField] = None
    marks: Optional[ExtractedField] = None
    percentage: Optional[ExtractedField] = None
    cgpa: Optional[ExtractedField] = None
    email: Optional[ExtractedField] = None
    website: Optional[ExtractedField] = None
    location: Optional[ExtractedField] = None
    # Labelled "Label: value" lines that do not belong to any schema field
    # (e.g. "Duration: 40 hours"). Never fabricated.
    additional_info: Dict[str, ExtractedField] = field(default_factory=dict)


@dataclass
class ExtractionStatistics:
    """Aggregate counts describing what was found in the document."""

    pages_processed: int = 0
    fields_detected: int = 0
    fields_not_detected: int = 0
    dates_detected: int = 0
    ids_detected: int = 0
    emails_detected: int = 0
    urls_detected: int = 0


@dataclass
class ExtractionResult:
    """Structured result returned by `extract_information`."""

    document_info: ExtractedDocumentInfo
    status: str  # "success" | "partial" | "failed" | "empty"
    warnings: List[str]
    errors: List[str]
    statistics: ExtractionStatistics
    overall_confidence: Optional[ConfidenceLevel]
    cleaned_text: str  # verbatim reference to the input this was derived from


_SCHEMA_FIELD_NAMES: Tuple[str, ...] = (
    "document_title", "document_type", "recipient_name", "student_id",
    "certificate_number", "institution_name", "university_name",
    "issuer_name", "issuer_designation", "course_name", "degree_name",
    "specialization", "department", "issue_date", "start_date",
    "completion_date", "expiry_date", "grade", "marks", "percentage",
    "cgpa", "email", "website", "location",
)


# --------------------------------------------------------------------------- #
# Page splitting ("----- Page N -----" markers from the cleaning stage)
# --------------------------------------------------------------------------- #

_PAGE_MARKER_PATTERN = re.compile(r"^-{2,}\s*Page\s+(\d+)\s*-{2,}$")


def _split_pages(text: str) -> List[Tuple[Optional[int], str]]:
    """
    Split text into (page_number, page_body) segments using the
    "----- Page N -----" markers. Without markers the whole text is one
    page with number `None`.
    """
    lines = text.split("\n")
    segments: List[Tuple[Optional[int], List[str]]] = []
    leading_lines: List[str] = []
    current_page: Optional[int] = None
    current_lines: List[str] = []
    seen_marker = False

    for line in lines:
        match = _PAGE_MARKER_PATTERN.match(line.strip())
        if match:
            if not seen_marker:
                if any(candidate.strip() for candidate in leading_lines):
                    segments.append((None, leading_lines))
            else:
                segments.append((current_page, current_lines))
            current_page = int(match.group(1))
            current_lines = []
            seen_marker = True
        else:
            (current_lines if seen_marker else leading_lines).append(line)

    if seen_marker:
        segments.append((current_page, current_lines))
    else:
        segments.append((None, leading_lines))

    return [(page, "\n".join(body_lines)) for page, body_lines in segments]


# --------------------------------------------------------------------------- #
# Low-level text helpers
# --------------------------------------------------------------------------- #

_WHITESPACE = re.compile(r"\s+")

# A line that itself looks like "Some Label: value" (used to stop a value from
# swallowing the next labelled line).
_LABEL_LIKE_LINE = re.compile(r"^[A-Za-z][A-Za-z .()/&']{1,35}\s*:")

# A second "Label:" further along the same line, e.g. after a column gap.
_NEXT_LABEL_IN_VALUE = re.compile(r"(?:\t+|\s{2,}|\s\|\s)[A-Za-z][A-Za-z .()/&']{1,35}\s*:")

# "Label: value" or "Label - value" (a dash needs spaces around it so that
# hyphenated words such as "course-based" are not treated as labels).
_LABEL_SEP = r"(?:\s*[:\uFF1A]\s*|\s+[-\u2013\u2014]+\s+)"


def _non_empty_lines(text: str) -> List[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def _next_non_empty(lines: List[str], idx: int, lookahead: int = 3) -> Optional[str]:
    for j in range(idx + 1, min(len(lines), idx + 1 + lookahead)):
        if lines[j].strip():
            return lines[j].strip()
    return None


def _clean_value(value: str, strip_quotes: bool = False) -> str:
    """
    Trim a captured value's boundaries WITHOUT altering its letters, digits
    or casing (the module must never "correct" OCR text).
    """
    value = _WHITESPACE.sub(" ", value).strip()
    if strip_quotes:
        value = value.strip(" \"'\u201c\u201d\u2018\u2019")
    return value.strip(" .,;:|_")


def _truncate_at_next_label(raw_value: str) -> str:
    match = _NEXT_LABEL_IN_VALUE.search(raw_value)
    return raw_value[: match.start()] if match else raw_value


def _label_group(labels: List[str]) -> str:
    return "(?:" + "|".join("(?:" + label + ")" for label in labels) + ")"


def _extract_labeled_value(
    text: str,
    label_alternatives: List[str],
    *,
    allow_next_line: bool = True,
    allow_table_gap: bool = True,
) -> Optional[Tuple[str, str]]:
    """
    Find the value belonging to one of the given label regexes. Supported
    layouts (checked line by line, first hit wins):

        Label: value                     (also "Label - value")
        Label:                           value on the following line
        Label                            label alone on its line, value next
        Label      value                 table-style, separated by a wide gap

    A second "Label:" further along the same line truncates the value so two
    fields are never glued together. Returns (value, source_snippet).
    """
    group = _label_group(label_alternatives)
    inline = re.compile(r"(?<![A-Za-z])" + group + _LABEL_SEP + r"(.*)$", re.IGNORECASE)
    standalone = re.compile(r"^\W*" + group + r"\W*$", re.IGNORECASE)
    gap = re.compile(r"^\W*" + group + r"(?:\t+|[ ]{2,})(\S.*)$", re.IGNORECASE)

    lines = text.split("\n")
    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue

        match = inline.search(line)
        if match:
            trimmed = _truncate_at_next_label(match.group(1))
            value = _clean_value(trimmed)
            if value:
                return value, line[match.start(): match.start(1) + len(trimmed)].strip()
            if allow_next_line:
                nxt = _next_non_empty(lines, idx)
                if nxt and not _LABEL_LIKE_LINE.match(nxt):
                    value = _clean_value(_truncate_at_next_label(nxt))
                    if value:
                        return value, f"{line} {nxt}"
            continue

        if allow_next_line and standalone.match(line):
            nxt = _next_non_empty(lines, idx)
            if nxt and not _LABEL_LIKE_LINE.match(nxt):
                value = _clean_value(_truncate_at_next_label(nxt))
                if value:
                    return value, f"{line} {nxt}"
            continue

        if allow_table_gap:
            match = gap.match(line)
            if match:
                trimmed = _truncate_at_next_label(match.group(1))
                # A value with another wide gap inside is most likely a table
                # header row ("Course   Duration   Grade"), not a value.
                if not re.search(r"\t|\s{2,}", trimmed):
                    value = _clean_value(trimmed)
                    if value:
                        return value, line

    return None


# A stop pattern that ends a free-text phrase (course name, issuer, ...) at
# the words/punctuation that normally follow it in certificate sentences.
_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
    r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)

_PHRASE_STOP = re.compile(
    r"\s+(?:(?:from|held|conducted|organi[sz]ed|offered|provided|delivered|hosted|arranged|at|during|"
    r"between|dated|under|by|scoring|securing|having|who|which|that|as\s+part|in\s+the\s+month|"
    r"and\s+(?:is|has|was)|is\s+hereby)\b"
    r"|on\s+(?:the\s+)?\d|on\s+" + _MONTH + r"\b|in\s+" + _MONTH + r"\b|in\s+\d{4}\b"
    r"|for\s+(?:a\s+)?(?:duration\b|period\b|\d)|of\s+\d+\s+(?:hours?|hrs?|days?|weeks?|months?)\b"
    r"|with\s+(?:(?:grade|distinction|honou?rs?|merit|a\s+(?:grade|score)|first|second|third|marks|cgpa|gpa)\b|\d))"
    r"|\s*[,;]|\.(?:\s|$)|\s+[-\u2013\u2014]\s+|\s{2,}|\t",
    re.IGNORECASE,
)

_PHRASE_LEADING_STOP = re.compile(
    r"^(?:with|from|at|on|by|held|conducted|organi[sz]ed|scoring|securing|during|under|and|having|"
    r"in\s+the|of|for|to|the\s+certificate)\b",
    re.IGNORECASE,
)

# A phrase that ends in a connector is assumed to continue on the next line.
_CONTINUATION_END = re.compile(r"(?:\b(?:of|in|on|and|for|to|the|with|at|a|an)|[&,/\-\u2013\u2014])\s*$", re.IGNORECASE)


def _phrase_after(text: str, pos: int, stop: Pattern[str] = _PHRASE_STOP) -> str:
    """
    Return the phrase that starts at `pos`: the rest of that line, or (when the
    cue ended its line) the next non-empty line. A line ending in a connector
    ("... program on") continues onto one further line. The phrase is cut at
    the first `stop` match.
    """
    lines = text[pos:].split("\n")
    idx = 0
    first = lines[0].strip()
    if not first:
        found = next((i for i in range(1, min(len(lines), 3)) if lines[i].strip()), None)
        if found is None:
            return ""
        idx = found
        first = lines[idx].strip()
        if _LABEL_LIKE_LINE.match(first):
            return ""

    phrase = first
    if not stop.search(phrase) and _CONTINUATION_END.search(phrase) and idx + 1 < len(lines):
        nxt = lines[idx + 1].strip()
        if nxt and not _LABEL_LIKE_LINE.match(nxt):
            phrase = f"{phrase} {nxt}"

    match = stop.search(phrase)
    if match:
        phrase = phrase[: match.start()]
    return _clean_value(phrase, strip_quotes=True)


# --------------------------------------------------------------------------- #
# Date detection
# --------------------------------------------------------------------------- #

_ORD = r"(?:st|nd|rd|th)?"

# Ordered longest-first: at any position the first alternative that matches
# wins, so "12 March 2024" is never reduced to "March 2024". No capturing groups.
_DATE_SOURCES: List[Tuple[str, str]] = [
    ("day_of_month_year", r"\b\d{1,2}" + _ORD + r"[ \t]+day[ \t]+of[ \t]+" + _MONTH + r"\.?,?[ \t]+\d{4}\b"),
    ("day_month_year", r"\b\d{1,2}" + _ORD + r"[ \t\-]+(?:of[ \t]+)?" + _MONTH + r"\.?,?[ \t\-]+\d{2,4}\b"),
    ("month_day_year", r"\b" + _MONTH + r"\.?[ \t]+\d{1,2}" + _ORD + r",?[ \t]+\d{2,4}\b"),
    ("iso", r"(?<![\w/.\-])\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?![\w/\-])"),
    ("numeric_slash_dash", r"(?<![\w/.\-])\d{1,2}[/\-]\d{1,2}[/\-](?:\d{4}|\d{2})(?![\w/\-])"),
    ("numeric_dot", r"(?<![\w/.\-])\d{1,2}\.\d{1,2}\.\d{4}(?![\w/\-])"),
    ("month_year", r"\b" + _MONTH + r"\.?,?[ \t]+\d{4}\b"),
]
_ANY_DATE = "(?:" + "|".join(source for _name, source in _DATE_SOURCES) + ")"
_ANY_DATE_RE = re.compile(_ANY_DATE, re.IGNORECASE)

# Partial dates are common in internship certificates: "from 2nd June to
# 12th July 2025".  They are valid as range endpoints even though a
# standalone date extractor should prefer a complete date with a year.
_PARTIAL_DATE = (
    r"\b\d{1,2}" + _ORD + r"[ \t]+" + _MONTH + r"\b"
    r"|\b" + _MONTH + r"\.?[ \t]+\d{1,2}" + _ORD + r"\b"
)

_DATE_RANGE_RE = re.compile(
    r"(?:\bfrom\s+|\bbetween\s+)?(" + _ANY_DATE + r"|" + _PARTIAL_DATE + r")"
    r"\s*(?:to|till|until|through|and|[-\u2013\u2014])\s*"
    r"(" + _ANY_DATE + r"|" + _PARTIAL_DATE + r")",
    re.IGNORECASE,
)


def _find_first_date(text: str) -> Optional[str]:
    """Return the first recognizable date substring in `text`, if any."""
    match = _ANY_DATE_RE.search(text)
    return match.group(0) if match else None


def find_all_dates(text: str) -> List[str]:
    """Find every recognizable date substring in `text` (non-overlapping)."""
    return [match.group(0) for match in _ANY_DATE_RE.finditer(text)]


_DATE_LABELS: Dict[str, List[str]] = {
    "issue_date": [
        r"issued(?:\s*on)?", r"date\s*of\s*issu(?:e|ance)", r"issu(?:e|ance)\s*date",
        r"date\s*of\s*award", r"awarded\s*on", r"date\s*of\s*certification",
    ],
    "start_date": [
        r"start(?:ing)?\s*date", r"date\s*of\s*(?:commencement|start|joining)",
        r"commenced\s*on", r"started\s*on", r"from\s*date", r"begin(?:ning)?\s*date",
        r"joining\s*date", r"joined\s*on",
    ],
    "completion_date": [
        r"completion\s*date", r"date\s*of\s*completion", r"completed\s*on",
        r"end(?:ing)?\s*date", r"to\s*date", r"date\s*of\s*(?:passing|examination)",
        r"exam(?:ination)?\s*date", r"concluded\s*on",
    ],
    "expiry_date": [
        r"expiry(?:\s*date)?", r"expiration(?:\s*date)?", r"date\s*of\s*expiry",
        r"valid\s*(?:till|until|upto|up\s*to|through|thru)", r"expires?\s*on", r"validity",
    ],
}

# Used only as a weaker fallback for the issue date ("Date: 12/03/2024").
_PLAIN_DATE_LABELS = [r"dated", r"date"]
_PLAIN_DATE_EXCLUDE = re.compile(
    r"start|begin|commenc|complet|\bend|expir|valid|birth|dob|join|\bfrom\b|\buntil\b|\btill\b|\bto\b",
    re.IGNORECASE,
)


def _extract_labeled_date(
    text: str,
    labels: List[str],
    *,
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
    allow_gap: bool = False,
    exclude_line: Optional[Pattern[str]] = None,
) -> Optional[ExtractedField]:
    """Extract a date that follows one of the given labels ("Issued on: ...")."""
    group = _label_group(labels)
    filler = r"[^\n\d]{0,40}?" if allow_gap else ""
    inline = re.compile(
        r"(?<![A-Za-z])" + group + r"\b\s*[:\-\u2013\u2014]?\s*" + filler + r"(?:on\s+|the\s+)?(" + _ANY_DATE + r")",
        re.IGNORECASE,
    )
    standalone = re.compile(r"^\W*" + group + r"\W*$", re.IGNORECASE)

    lines = text.split("\n")
    for idx, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line or (exclude_line and exclude_line.search(line)):
            continue
        match = inline.search(line)
        if match:
            return ExtractedField(
                value=match.group(1), confidence=confidence,
                source=line[match.start(): match.end()], method="label",
            )
        if standalone.match(line):
            nxt = _next_non_empty(lines, idx)
            date_str = _find_first_date(nxt) if nxt else None
            if date_str:
                return ExtractedField(value=date_str, confidence=confidence, source=f"{line} {nxt}", method="label")
    return None


def _date_from_range(text: str, which: int) -> Optional[ExtractedField]:
    """Start (0) or end (1) of a 'from X to Y' style date range."""
    match = _DATE_RANGE_RE.search(text)
    if not match:
        return None
    return ExtractedField(
        value=match.group(which + 1), confidence=ConfidenceLevel.MEDIUM,
        source=match.group(0).strip(), method="context_phrase",
    )


_COMPLETION_CONTEXT = re.compile(
    r"\b(?:complet(?:ed|ion)|passed|concluded|finished)\b(?:[^\n]|\n(?!\s*\n)){0,200}?"
    r"\b(?:on|dated|in|during)\s+(?:the\s+)?(" + _ANY_DATE + r")",
    re.IGNORECASE,
)
_ISSUE_CONTEXT = re.compile(
    r"\b(?:given|issued|dated|awarded|presented)\b[^\n]{0,80}?\b(?:this|on|dated)\s+(?:the\s+)?(" + _ANY_DATE + r")",
    re.IGNORECASE,
)


def _extract_issue_date(text: str) -> Optional[ExtractedField]:
    found = _extract_labeled_date(text, _DATE_LABELS["issue_date"])
    if found:
        return found
    found = _extract_labeled_date(
        text, _PLAIN_DATE_LABELS, confidence=ConfidenceLevel.MEDIUM,
        allow_gap=True, exclude_line=_PLAIN_DATE_EXCLUDE,
    )
    if found:
        found.method = "label"
        return found
    match = _ISSUE_CONTEXT.search(text)
    if match:
        return ExtractedField(
            value=match.group(1), confidence=ConfidenceLevel.MEDIUM,
            source=match.group(0).strip(), method="context_phrase",
        )
    return None


def _extract_start_date(text: str) -> Optional[ExtractedField]:
    return _extract_labeled_date(text, _DATE_LABELS["start_date"]) or _date_from_range(text, 0)


def _extract_completion_date(text: str) -> Optional[ExtractedField]:
    found = _extract_labeled_date(text, _DATE_LABELS["completion_date"]) or _date_from_range(text, 1)
    if found:
        return found
    match = _COMPLETION_CONTEXT.search(text)
    if match:
        return ExtractedField(
            value=match.group(1), confidence=ConfidenceLevel.MEDIUM,
            source=_WHITESPACE.sub(" ", match.group(0)).strip(), method="context_phrase",
        )
    return None


def _extract_expiry_date(text: str) -> Optional[ExtractedField]:
    return _extract_labeled_date(text, _DATE_LABELS["expiry_date"])


# --------------------------------------------------------------------------- #
# E-mail / URL detection
# --------------------------------------------------------------------------- #

_EMAIL_PATTERN = re.compile(r"(?<![A-Za-z0-9_.+\-])[A-Za-z0-9_.+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_URL_PATTERN = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
# Bare domains ("example.com/verify") are only accepted for well-known TLDs
# and with a second-level label of 3+ characters, so degree abbreviations such
# as "B.Tech", "M.Sc" or "Ph.D" are never mistaken for websites.
_BARE_DOMAIN_PATTERN = re.compile(
    r"(?<![@\w./\-])(?:[a-z0-9\-]+\.)*[a-z0-9][a-z0-9\-]{2,}\."
    r"(?:com|org|net|edu|gov|io|co|in|ac|info|biz|ai|us|uk|ca|au|de|app|dev|online|site|tech|academy|school|xyz)"
    r"(?:\.[a-z]{2})?(?:/[^\s<>\"']*)?(?![\w@\-])",
    re.IGNORECASE,
)


def find_all_emails(text: str) -> List[str]:
    """Return every email-like substring found in `text`."""
    return [match.group(0) for match in _EMAIL_PATTERN.finditer(text)]


def _url_matches(text: str) -> List["re.Match[str]"]:
    email_spans = [match.span() for match in _EMAIL_PATTERN.finditer(text)]
    found: List["re.Match[str]"] = []
    taken: List[Tuple[int, int]] = []
    for pattern in (_URL_PATTERN, _BARE_DOMAIN_PATTERN):
        for match in pattern.finditer(text):
            span = match.span()
            if any(span[0] < e[1] and span[1] > e[0] for e in email_spans):
                continue
            if any(span[0] < t[1] and span[1] > t[0] for t in taken):
                continue
            taken.append(span)
            found.append(match)
    return sorted(found, key=lambda m: m.start())


def find_all_urls(text: str) -> List[str]:
    """Return every URL-like substring found in `text` (e-mail domains excluded)."""
    return [match.group(0).rstrip(".,;:)") for match in _url_matches(text)]


def _extract_email(text: str) -> Optional[ExtractedField]:
    match = _EMAIL_PATTERN.search(text)
    if not match:
        return None
    return ExtractedField(
        value=match.group(0).rstrip(".,;:"), confidence=ConfidenceLevel.HIGH,
        source=match.group(0), method="pattern",
    )


def _extract_website(text: str) -> Optional[ExtractedField]:
    matches = _url_matches(text)
    if not matches:
        return None
    match = matches[0]
    return ExtractedField(
        value=match.group(0).rstrip(".,;:)"), confidence=ConfidenceLevel.HIGH,
        source=match.group(0), method="pattern",
    )


# --------------------------------------------------------------------------- #
# ID / credential numbers (only ever taken next to an ID-like label)
# --------------------------------------------------------------------------- #

_ID_LABELS: Dict[str, List[str]] = {
    "student_id": [
        r"(?:student|candidate|trainee|learner|participant|member|employee|applicant|delegate|intern)"
        r"\s*(?:id|no\.?|number|code|#)",
        r"roll\s*(?:no\.?|number|#)",
        r"(?:registration|reg\.?|enrol+ment|admission|seat|hall\s*ticket|exam(?:ination)?)\s*(?:no\.?|number|id|#)",
        r"(?:prn|usn|uid|uin)",
    ],
    "certificate_number": [
        r"cert(?:ificate|\.)?\s*(?:no\.?|number|id|code|#)",
        r"credential\s*(?:id|no\.?|number|code|#)",
        r"serial\s*(?:no\.?|number|#)",
        r"(?:reference|ref\.?)\s*(?:no\.?|number|id|#)?",
        r"(?:document|doc\.?|diploma|licen[cs]e|verification|validation|unique|authenticity)"
        r"\s*(?:no\.?|number|id|code|#)",
    ],
}

_ID_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9/_.\-#]*")


def _is_plausible_id(token: str) -> bool:
    if len(token) < 3:
        return False
    if any(ch.isdigit() for ch in token):
        return not _ANY_DATE_RE.fullmatch(token)
    return token.isupper() and len(token) >= 6  # e.g. an all-letter code


def _extract_id_field(text: str, labels: List[str]) -> Optional[ExtractedField]:
    labeled = _extract_labeled_value(text, labels)
    if labeled:
        raw_value, source = labeled
        token_match = _ID_TOKEN.match(raw_value)
        if token_match:
            token = token_match.group(0).strip(".,;:-/#")
            if _is_plausible_id(token):
                return ExtractedField(value=token, confidence=ConfidenceLevel.HIGH, source=source, method="label")

    # Loose form without a separator ("Roll No 20BCS045"): the token must
    # contain a digit, which keeps ordinary words from being read as IDs.
    loose = re.compile(
        r"(?<![A-Za-z])" + _label_group(labels) + r"\s*[:#\-\u2013\u2014.]*\s*"
        r"([A-Za-z0-9][A-Za-z0-9/_.\-]*\d[A-Za-z0-9/_.\-]*)",
        re.IGNORECASE,
    )
    for line in text.split("\n"):
        match = loose.search(line)
        if match:
            token = match.group(1).strip(".,;:-/")
            if _is_plausible_id(token):
                return ExtractedField(
                    value=token, confidence=ConfidenceLevel.MEDIUM,
                    source=match.group(0).strip(), method="pattern",
                )

    # Certificate prose often embeds the student ID directly after the
    # recipient name,     # is deliberately narrow: the token must contain digits and be followed
    # by an explicit student cue, so ordinary dates/numbers are not captured.
    if labels is _ID_LABELS["student_id"]:
        contextual = re.compile(
            r"\b([A-Z][A-Za-z]+(?:[ \t]+[A-Z][A-Za-z]+){1,3})[ \t]+"
            r"((?=[A-Za-z0-9._/-]*[A-Za-z])(?=[A-Za-z0-9._/-]*\d)[A-Za-z0-9._/-]{3,24})[ \t]+"
            r"(?=(?:an?\s+)?student\b)",
            re.IGNORECASE,
        )
        match = contextual.search(text)
        if match and _is_plausible_id(match.group(2)):
            return ExtractedField(
                value=match.group(2), confidence=ConfidenceLevel.MEDIUM,
                source=match.group(0).strip(), method="context_phrase",
            )
    return None


# --------------------------------------------------------------------------- #
# Person names
# --------------------------------------------------------------------------- #

_PERSON_QUALIFIER = (
    r"(?:student|candidate|recipient|participant|trainee|learner|awardee|holder|delegate|attendee|"
    r"intern|employee|applicant|beneficiary|graduate|member|patient|customer|client|"
    r"account\s*holder|insured|policyholder|tenant|owner|passenger|driver|traveller|traveler|full)"
)

_QUALIFIED_NAME_LABELS = [
    _PERSON_QUALIFIER + r"['\u2019]?s?\s*name",
    r"name\s+of\s+(?:the\s+)?" + _PERSON_QUALIFIER,
    r"awarded\s+to", r"presented\s+to", r"issued\s+to", r"granted\s+to",
]

# Words that cannot be part of a person's name; used to reject sentence
# fragments, organisation names and document titles.
_NON_NAME_WORDS = frozenset(
    """
    certificate certification certified course training program programme workshop internship
    university college institute institution school academy department faculty board
    completion achievement participation excellence appreciation award awarded presented
    this that the has have had is was are successfully hereby certify certifies
    ltd limited pvt private inc llc solutions technologies technology systems services
    foundation association society council trust centre center authority
    degree diploma transcript marks issued provided granted presented
    invoice statement document report letter form date address number total bill
    passport nationality account policy claim patient employee companyheet grade marks
    """.split()
)

_NAME_CUE_PATTERNS: List[Pattern[str]] = [
    re.compile(r"\b(?:hereby\s+)?certif(?:y|ies|ied)\s+that\b[\s:,\-]*", re.IGNORECASE),
    re.compile(
        r"\b(?:(?:conferred|bestowed)\s+(?:upon|on)|(?:presented|awarded|granted|issued|given)\s+to)\b[\s:,\-]*",
        re.IGNORECASE,
    ),
]
_GENERIC_NAME_CUE_PATTERNS: List[Pattern[str]] = [
    re.compile(r"\b(?:granted|issued|presented|addressed|assigned|registered|enrolled|belongs?)\s+to\b[\s:,\-]*", re.IGNORECASE),
    re.compile(r"\b(?:employee|applicant|holder|beneficiary|patient|customer|client|passenger|driver|owner)\b\s*[:\-]?\s*", re.IGNORECASE),
]


_NAME_STOP = re.compile(
    r"\s+(?=[A-Za-z0-9._/-]*\d[A-Za-z0-9._/-]*\s+(?:an?\s+)?student\b)"
    r"|\s+(?:has|have|had|is|are|was|who|s/o|d/o|w/o|c/o|son|daughter|wife|bearing|holding|successfully|"
    r"having|for|of|in|on|from|with|under|at|as|to|by|roll|reg(?:istration)?|enrol\w*)\b"
    r"|\s*[,;:(]|\.(?=\s*$)|\.(?=\s+(?-i:[a-z]))|\s{2,}|\t",
    re.IGNORECASE,
)

_COMPLETION_VERB_LINE = re.compile(
    r"^(?:has|have|had|is|was|hereby)\b.{0,20}?\b"
    r"(?:complet|attend|participat|pass|award|qualif|undergone|secur|achiev|been|success|earn)",
    re.IGNORECASE,
)


def _looks_like_person_name(candidate: str, min_words: int = 1, require_case: bool = True) -> bool:
    """
    Heuristic filter against obviously wrong matches: a plausible name has
    1-6 alphabetic words, no digits, no organisation / document vocabulary,
    and is not entirely lowercase (which would be a sentence fragment).
    """
    candidate = candidate.strip()
    if not candidate or len(candidate) > 60 or (require_case and candidate == candidate.lower()):
        return False
    if re.search(r"[:@/\\]", candidate):
        return False
    words = candidate.split()
    if not (min_words <= len(words) <= 6):
        return False
    for word in words:
        core = word.strip(".,'\u2019-")
        if not core or not core[0].isalpha() or any(ch.isdigit() for ch in core):
            return False
        if core.lower() in _NON_NAME_WORDS:
            return False
    return True


def _extract_generic_name_label(text: str, require_case: bool = True) -> Optional[ExtractedField]:
    """A bare "Name: ..." label, accepted only at the start of a line so that
    "Institution Name:" / "Father's Name:" are never read as the recipient."""
    lines = text.split("\n")
    pattern = re.compile(r"^[\d\W]*name\s*(?:[:\uFF1A]|\s[-\u2013\u2014]\s)\s*(.*)$", re.IGNORECASE)
    gap = re.compile(r"^name(?:\t+|[ ]{2,})(\S.*)$", re.IGNORECASE)
    for idx, raw in enumerate(lines):
        line = raw.strip()
        match = pattern.match(line) or gap.match(line)
        if not match:
            continue
        value = _clean_value(_truncate_at_next_label(match.group(1)))
        if not value:
            nxt = _next_non_empty(lines, idx)
            if nxt and not _LABEL_LIKE_LINE.match(nxt):
                value = _clean_value(nxt)
        if value and _looks_like_person_name(value, require_case=require_case):
            return ExtractedField(value=value, confidence=ConfidenceLevel.MEDIUM, source=line, method="label")
    return None


def _extract_recipient_name(text: str) -> Optional[ExtractedField]:
    """
    Strategies, strongest first:
      1. a qualified label ("Student Name:", "Name of the Candidate")
      2. a bare "Name:" line
      3. certificate phrasing: "certify that <name> ...", "presented to <name>"
         (the name may sit on the line after the cue)
      4. layout: a name-like line directly above "has successfully completed ..."
    """
    # If OCR produced no capital letters at all, "not entirely lowercase" can no
    # longer be used to filter sentence fragments.
    require_case = text != text.lower()

    labeled = _extract_labeled_value(text, _QUALIFIED_NAME_LABELS)
    if labeled:
        value, source = labeled
        if _looks_like_person_name(value, require_case=require_case):
            return ExtractedField(value=value, confidence=ConfidenceLevel.HIGH, source=source, method="label")

    generic = _extract_generic_name_label(text, require_case=require_case)
    if generic:
        return generic

    for cue in _NAME_CUE_PATTERNS:
        for match in cue.finditer(text):
            candidate = _phrase_after(text, match.end(), _NAME_STOP)
            if _looks_like_person_name(candidate, require_case=require_case):
                return ExtractedField(
                    value=candidate, confidence=ConfidenceLevel.MEDIUM,
                    source=f"{match.group(0).strip()} {candidate}".strip(), method="context_phrase",
                )

    for cue in _GENERIC_NAME_CUE_PATTERNS:
        for match in cue.finditer(text):
            candidate = _phrase_after(text, match.end(), _NAME_STOP)
            if _looks_like_person_name(candidate, require_case=require_case):
                return ExtractedField(
                    value=candidate, confidence=ConfidenceLevel.MEDIUM,
                    source=f"{match.group(0).strip()} {candidate}".strip(), method="context_phrase",
                )

    lines = _non_empty_lines(text)
    for idx in range(1, len(lines)):
        if _COMPLETION_VERB_LINE.match(lines[idx]):
            candidate = _clean_value(lines[idx - 1])
            if _looks_like_person_name(candidate, min_words=2):
                return ExtractedField(
                    value=candidate, confidence=ConfidenceLevel.MEDIUM,
                    source=f"{lines[idx - 1]} / {lines[idx]}", method="context_phrase",
                )
    return None


# --------------------------------------------------------------------------- #
# Titles and organisations
# --------------------------------------------------------------------------- #

_TITLE_KEYWORDS = re.compile(
    r"\b(?:certificate|certification|diploma|degree|transcript|mark\s*sheet|marksheet|"
    r"statement\s+of\s+marks|grade\s+(?:card|sheet)|report\s+card|award|credential|licen[cs]e|"
    r"of\s+(?:completion|achievement|participation|appreciation|excellence|merit|training|"
    r"internship|recognition|registration|qualification|accreditation))\b",
    re.IGNORECASE,
)
_SENTENCE_WORDS = re.compile(
    r"\b(?:is|are|was|has|have|had|hereby|awarded|presented|certify|certifies|successfully|"
    r"completed|attended|will|shall)\b",
    re.IGNORECASE,
)


def _extract_document_title(first_page_text: str) -> Optional[ExtractedField]:
    """
    Prefer a heading line that names a document kind ("CERTIFICATE OF
    COMPLETION", "Statement of Marks"); a title split over two lines
    ("CERTIFICATE" / "OF COMPLETION") is joined. Falls back to the first
    line (LOW confidence) because letterhead often comes first.
    """
    lines = _non_empty_lines(first_page_text)
    if not lines:
        return None

    for idx, line in enumerate(lines[:15]):
        if len(line) > 100 or _LABEL_LIKE_LINE.match(line) or any(ch.isdigit() for ch in line):
            continue
        if _TITLE_KEYWORDS.search(line) and not _SENTENCE_WORDS.search(line):
            title = line
            if idx + 1 < len(lines) and re.match(r"^of\s+\w+", lines[idx + 1], re.IGNORECASE) \
                    and len(lines[idx + 1].split()) <= 4 and not re.search(r"\bof\b", line, re.IGNORECASE):
                title = f"{line} {lines[idx + 1]}"
            return ExtractedField(
                value=_clean_value(title), confidence=ConfidenceLevel.MEDIUM,
                source=title, method="heading_heuristic",
            )

    first_line = lines[0]
    if 3 <= len(first_line) <= 100 and not _LABEL_LIKE_LINE.match(first_line) \
            and sum(ch.isalpha() for ch in first_line) >= 3:
        return ExtractedField(value=first_line, confidence=ConfidenceLevel.LOW, source=first_line, method="heading_heuristic")
    return None


_UNIVERSITY_WORDS = r"\buniversit(?:y|ies)\b|\bvishwavidyalaya\b|\bvidyapeeth\b"
_INSTITUTION_WORDS = (
    r"\b(?:universit(?:y|ies)|vishwavidyalaya|vidyapeeth|institute|institution|college|school|"
    r"academy|polytechnic|company|corporation|corp\.?|organization|organisation|board|authority|"
    r"hospital|government|govt\.?|department|ministry|agency|foundation|association|society|"
    r"council|trust|centre|center|laborator(?:y|ies)|lab|enterprise(?:s)?|group|ltd\.?|limited|"
    r"pvt\.?|private|inc\.?|llc|llp|solutions?|technolog(?:y|ies)|systems|services|training|"
    r"education(?:al)?|learning|consult\w*)\b"
)


def _looks_like_org_heading(line: str) -> bool:
    if not (2 <= len(line.split()) <= 12) or len(line) > 100:
        return False
    if _LABEL_LIKE_LINE.match(line) or _SENTENCE_WORDS.search(line) or _TITLE_KEYWORDS.search(line) \
            or _ISSUER_CUE.match(line):
        return False
    if re.search(r"@|www\.|https?:", line, re.IGNORECASE):
        return False
    digits = sum(ch.isdigit() for ch in line)
    return digits <= len(line) * 0.3


def _extract_organization(text: str, heading_keyword_pattern: str, labels: List[str]) -> Optional[ExtractedField]:
    """Extract an organisation/entity using labels, context, then layout."""
    labeled = _extract_labeled_field(text, labels, ConfidenceLevel.HIGH)
    if labeled:
        return labeled

    context_patterns = [
        r"\b(?:student|candidate|trainee|participant|applicant|employee|member|patient|customer|client|account\s+holder|registered\s+user)\s+(?:of|at|from|with)\s+",
        r"\b(?:issued|awarded|provided|certified|approved|authorized|authorised|registered|employed|insured|admitted|treated|verified|validated|supported|sponsored|funded|maintained)\s+by\s+",
        r"\b(?:issued|provided|registered|employed|insured|admitted|treated)\s+(?:through|with|at)\s+",
    ]
    stop = re.compile(r"(?=\s+(?:who|which|that|has|have|had|is|was|were|are|successfully|for|during|on|dated|issued|provided|registered|employed|insured|from|with|at|by)\b|[.,;:()])", re.IGNORECASE)
    for pattern in context_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidate_line = text[match.end():].split("\n", 1)[0].strip()
            m = stop.search(candidate_line)
            candidate = candidate_line[:m.start()] if m else candidate_line
            candidate = _clean_value(candidate, strip_quotes=True).strip(" -–—")
            if not (3 <= len(candidate) <= 120):
                continue
            if _LABEL_LIKE_LINE.match(candidate) or _looks_like_person_name(candidate, min_words=1) or _SENTENCE_WORDS.search(candidate):
                continue
            if re.search(_INSTITUTION_WORDS, candidate, re.IGNORECASE) or len(candidate.split()) >= 2:
                return ExtractedField(value=candidate, confidence=ConfidenceLevel.MEDIUM,
                                      source=f"{match.group(0).strip()} {candidate}".strip(), method="context_phrase")

    keyword = re.compile(heading_keyword_pattern, re.IGNORECASE)
    lines = _non_empty_lines(text)
    for line in lines[:12]:
        if keyword.search(line) and _looks_like_org_heading(line):
            return ExtractedField(value=_clean_value(line), confidence=ConfidenceLevel.MEDIUM,
                                  source=line, method="heading_heuristic")
    for line in lines[-8:] if len(lines) > 12 else []:
        if keyword.search(line) and _looks_like_org_heading(line):
            return ExtractedField(value=_clean_value(line), confidence=ConfidenceLevel.LOW,
                                  source=line, method="heading_heuristic")

    # Preserve the university-specific prose fallback for existing academic documents.
    if heading_keyword_pattern and re.search(r"universit", heading_keyword_pattern, re.IGNORECASE):
        contextual = re.compile(
            r"\b(?:student|candidate|trainee|participant|graduate|alumnus|alumna)\s+of\s+"
            r"((?:[A-Z][A-Za-z0-9&.'-]*\s+){1,8}(?:University|College|Institute|Academy|School))\b",
            re.IGNORECASE,
        )
        match = contextual.search(text)
        if match:
            return ExtractedField(value=_clean_value(match.group(1)), confidence=ConfidenceLevel.MEDIUM,
                                  source=match.group(0).strip(), method="context_phrase")
    return None


def _extract_labeled_field(
    text: str, labels: List[str], confidence: ConfidenceLevel, strip_quotes: bool = True
) -> Optional[ExtractedField]:
    """Generic 'Label: value' extractor for simple free-text fields."""
    labeled = _extract_labeled_value(text, labels)
    if not labeled:
        return None
    value, source = labeled
    cleaned = _clean_value(value, strip_quotes=strip_quotes)
    if not cleaned:
        return None
    return ExtractedField(value=cleaned, confidence=confidence, source=source, method="label")


_INSTITUTION_LABELS = [
    r"institution(?:\s*name)?", r"institute(?:\s*name)?", r"college(?:\s*name)?", r"school(?:\s*name)?",
    r"academy(?:\s*name)?", r"organi[sz]ation(?:\s*name)?", r"company(?:\s*name)?",
    r"training\s*(?:provider|partner|cent(?:re|er)|institute)",
    r"issuing\s*(?:authority|institution|organi[sz]ation)",
]
_UNIVERSITY_LABELS = [r"university(?:\s*name)?", r"affiliated\s*(?:to|with)", r"awarding\s*(?:body|university)"]
_COURSE_LABELS = [
    r"course(?:\s*(?:name|title))?", r"program(?:me)?(?:\s*(?:name|title))?",
    r"training(?:\s*(?:program(?:me)?|name|title|on))?", r"workshop(?:\s*(?:name|title))?", r"module",
]
_DEGREE_LABELS = [r"degree", r"qualification"]
_SPECIALIZATION_LABELS = [r"specialization", r"specialisation", r"major", r"stream", r"discipline"]
_DEPARTMENT_LABELS = [r"department", r"dept\.?", r"branch", r"faculty"]
_ISSUER_LABELS = [
    r"issued\s*by", r"issuer", r"awarded\s*by", r"authori[sz]ed\s*signatory", r"signed\s*by",
    r"approved\s*by", r"certified\s*by", r"signatory",
]
_ISSUER_DESIGNATION_LABELS = [r"designation", r"position", r"role"]
_LOCATION_LABELS = [
    r"address", r"location", r"place\s*(?:&|and)\s*date",
    r"place(?:\s*of\s*(?:issue|training|examination|birth|residence))?",
    r"city", r"state|province|region|country",
    r"postal(?:\s*code)?|zip(?:\s*code)?|pin(?:\s*code)?",
    r"residence", r"venue", r"held\s*at",
]

# --------------------------------------------------------------------------- #
# Issuer: sentence cues and signature block
# --------------------------------------------------------------------------- #

_ISSUER_CUE = re.compile(
    r"\b(?:(?:issued|awarded|presented|conducted|organi[sz]ed|offered|provided|delivered|certified|"
    r"authori[sz]ed|accredited|approved)\s+by|in\s+(?:association|collaboration)\s+with|powered\s+by)\b[\s:\-]*",
    re.IGNORECASE,
)

_DESIGNATION_WORDS = (
    r"(?:director|principal|registrar|dean|controller|chairman|chairperson|chairwoman|chancellor|"
    r"vice[- ]chancellor|president|vice[- ]president|ceo|cto|coo|cfo|founder|co[- ]?founder|manager|"
    r"head|hod|professor|lecturer|instructor|trainer|mentor|coordinator|co-ordinator|secretary|"
    r"signatory|examiner|officer|administrator|superintendent|convener|proprietor|partner|"
    r"supervisor|in[- ]charge)"
)
_DESIGNATION_RE = re.compile(r"\b" + _DESIGNATION_WORDS + r"\b", re.IGNORECASE)


def _segments(line: str) -> List[str]:
    """Split a line at wide gaps (OCR of side-by-side signature columns)."""
    return [seg.strip() for seg in re.split(r"\t+|\s{2,}", line) if seg.strip()]


def _find_signature_block(text: str) -> Optional[Tuple[Optional[str], str, str]]:
    """
    Locate a signature block: a short designation line ("Director",
    "Head of Department") with a person-like name directly above (or below)
    it. Scans from the bottom of the page up. Returns
    (name_or_None, designation, source_snippet).
    """
    lines = _non_empty_lines(text)
    count = len(lines)
    for idx in range(count - 1, -1, -1):
        segments = _segments(lines[idx])
        if not segments:
            continue
        candidate = segments[0]
        if ":" in candidate or any(ch.isdigit() for ch in candidate):
            continue
        if len(candidate.split()) > 8 or _SENTENCE_WORDS.search(candidate) or not _DESIGNATION_RE.search(candidate):
            continue

        name: Optional[str] = None
        for j in (idx - 1, idx + 1):
            if 0 <= j < count:
                neighbour = _segments(lines[j])
                if neighbour and not _DESIGNATION_RE.search(neighbour[0]) \
                        and _looks_like_person_name(neighbour[0], min_words=2):
                    name = _clean_value(neighbour[0])
                    break
        if name or idx >= count // 2:
            source = f"{name} / {candidate}" if name else candidate
            return name, _clean_value(candidate), source
    return None


def _extract_issuer_name(text: str) -> Optional[ExtractedField]:
    labeled = _extract_labeled_field(text, _ISSUER_LABELS, ConfidenceLevel.HIGH)
    if labeled:
        labeled.value = labeled.value.strip("() ")
        return labeled

    # Prefer an explicit prose attribution such as "conducted by <issuer>"
    # over a footer/signature heuristic.
    for match in _ISSUER_CUE.finditer(text):
        phrase = re.sub(r"^(?:the|our)\s+", "", _phrase_after(text, match.end()), flags=re.IGNORECASE)
        phrase = _clean_value(phrase, strip_quotes=True).strip("()")
        if 3 <= len(phrase) <= 80 and phrase[0].isalpha() and not _PHRASE_LEADING_STOP.match(phrase):
            return ExtractedField(
                value=phrase, confidence=ConfidenceLevel.MEDIUM,
                source=f"{match.group(0).strip()} {phrase}", method="context_phrase",
            )

    block = _find_signature_block(text)
    if block and block[0]:
        return ExtractedField(value=block[0], confidence=ConfidenceLevel.MEDIUM, source=block[2], method="signature_block")
    for match in _ISSUER_CUE.finditer(text):
        phrase = re.sub(r"^(?:the|our)\s+", "", _phrase_after(text, match.end()), flags=re.IGNORECASE)
        if 3 <= len(phrase) <= 80 and phrase[0].isalpha() and not _PHRASE_LEADING_STOP.match(phrase):
            return ExtractedField(
                value=phrase, confidence=ConfidenceLevel.MEDIUM,
                source=f"{match.group(0).strip()} {phrase}", method="context_phrase",
            )
    return None


def _extract_issuer_designation(text: str) -> Optional[ExtractedField]:
    labeled = _extract_labeled_field(text, _ISSUER_DESIGNATION_LABELS, ConfidenceLevel.HIGH)
    if labeled:
        return labeled
    block = _find_signature_block(text)
    if block:
        return ExtractedField(value=block[1], confidence=ConfidenceLevel.MEDIUM, source=block[2], method="signature_block")
    return None


# --------------------------------------------------------------------------- #
# Course, degree, specialization
# --------------------------------------------------------------------------- #

_COURSE_KIND = (
    r"(?:course|training|program(?:me)?|workshop|internship|module|bootcamp|seminar|"
    r"certification|webinar|class(?:es)?)"
)
_COURSE_CUE = re.compile(
    r"(?:successfully\s+)?(?:complet(?:ed|ing|ion\s+of)|attend(?:ed|ing)|undergone|undergoing|"
    r"participat(?:ed|ing)\s+in|passed|cleared|qualified\s+in|enrolled\s+in|pursu(?:ed|ing))\s+"
    r"(?:the\s+|a\s+|an\s+|our\s+|her\s+|his\s+|their\s+|this\s+)?"
    r"(?:(?:(?:online|offline|professional|certification|certificate|training|short[- ]term|internship)\s+)*"
    + _COURSE_KIND + r"\s*(?:on|in|of|titled|entitled|named|called|for)?\s*[:\-]?\s*)?"
    r"[\"\u201c'\u2018]?",
    re.IGNORECASE,
)


def _plausible_title_phrase(phrase: str) -> bool:
    if not (3 <= len(phrase) <= 120) or not phrase[0].isalpha():
        return False
    if _PHRASE_LEADING_STOP.match(phrase) or _ANY_DATE_RE.fullmatch(phrase):
        return False
    return sum(ch.isalpha() for ch in phrase) >= 3


def _extract_course_name(text: str) -> Optional[ExtractedField]:
    labeled = _extract_labeled_field(text, _COURSE_LABELS, ConfidenceLevel.HIGH)
    if labeled and _plausible_title_phrase(labeled.value):
        return labeled

    # Common certificate wording: "certification program on <course>" or
    # "training program on <course>".  Stop before the date/conducted-by
    # portion rather than returning the entire remainder of the sentence.
    direct = re.search(
        r"\b(?:certification|training|internship|summer|skill)?[ \t]*"
        r"program(?:me)?\s+on\s+(.+?)(?=\s+(?:from|conducted|organized|offered|provided|by)\b|[.,;]|$)",
        text, re.IGNORECASE,
    )
    if direct:
        phrase = _clean_value(direct.group(1), strip_quotes=True)
        if _plausible_title_phrase(phrase):
            return ExtractedField(
                value=phrase, confidence=ConfidenceLevel.MEDIUM,
                source=direct.group(0).strip(), method="context_phrase",
            )

    for match in _COURSE_CUE.finditer(text):
        phrase = _phrase_after(text, match.end())
        if _plausible_title_phrase(phrase):
            return ExtractedField(
                value=phrase, confidence=ConfidenceLevel.MEDIUM,
                source=_WHITESPACE.sub(" ", f"{match.group(0).strip()} {phrase}"), method="context_phrase",
            )
    return None


_DEGREE_FULL = re.compile(
    r"\b((?:(?:Post[- ]?Graduate|Advanced)[ \t]+)?(?:Bachelor|Master|Doctor|Associate|Diploma)(?:'s|s)?[ \t]+(?:of|in)[ \t]+[A-Za-z&]+"
    r"(?:[ \t]+(?:and|&|of)[ \t]+[A-Za-z&]+"
    r"|[ \t]+(?!in\b|with\b|from\b|at\b|on\b|by\b|has\b|having\b|under\b|specializ)[A-Za-z&]+){0,2})"
    r"(?:[ \t]*\(([^)\n]{2,60})\)"
    r"|[ \t]+(?:in|with[ \t]+(?:a[ \t]+)?(?:major|specializ\w+)[ \t]+in|specializ\w+[ \t]+in)[ \t]+"
    r"([A-Za-z&' \-]{2,60}?)(?=[ \t]*(?:[,;.(\n]|\bfrom\b|\bat\b|\bwith\b|\bon\b|\bby\b|\bhas\b|\bhaving\b|\bunder\b|$)))?",
    re.IGNORECASE,
)
_DEGREE_ABBR = re.compile(
    r"(?<![A-Za-z.])((?:B\.?[ ]?Tech|M\.?[ ]?Tech|B\.?[ ]?Sc|M\.?[ ]?Sc|B\.?[ ]?Com|M\.?[ ]?Com|"
    r"B\.?[ ]?Ed|M\.?[ ]?Ed|B\.?[ ]?Arch|B\.?[ ]?Pharm|M\.?[ ]?Pharm|B\.?[ ]?Des|"
    r"B\.E|M\.E|B\.A|M\.A|B\.S|M\.S|Ph\.?[ ]?D|MBA|BBA|BCA|MCA|LL\.?B|LL\.?M|MBBS)\.?)(?![A-Za-z])"
    r"(?:[ \t]*\(([^)\n]{2,60})\)"
    r"|[ \t]+in[ \t]+([A-Za-z&' \-]{2,60}?)(?=[ \t]*(?:[,;.(\n]|from\b|at\b|with\b|on\b|$)))?"
)
_ABBREVIATION_ONLY = re.compile(r"^[A-Z.]{2,8}$")


def _scan_degree(text: str) -> Optional[Tuple[str, Optional[str], str]]:
    """Find a degree in prose; returns (degree, specialization_or_None, source)."""
    for pattern in (_DEGREE_FULL, _DEGREE_ABBR):
        match = pattern.search(text)
        if not match:
            continue
        degree = _clean_value(match.group(1))
        spec_raw = match.group(3) or match.group(2)
        specialization = None
        if spec_raw:
            spec_clean = _clean_value(spec_raw)
            if spec_clean and not _ABBREVIATION_ONLY.match(spec_clean):
                specialization = spec_clean
        return degree, specialization, _WHITESPACE.sub(" ", match.group(0)).strip()
    return None


def _extract_degree_name(text: str) -> Optional[ExtractedField]:
    labeled = _extract_labeled_field(text, _DEGREE_LABELS, ConfidenceLevel.HIGH)
    if labeled and _plausible_title_phrase(labeled.value):
        return labeled
    found = _scan_degree(text)
    if found:
        return ExtractedField(value=found[0], confidence=ConfidenceLevel.MEDIUM, source=found[2], method="context_phrase")
    return None


def _extract_specialization(text: str) -> Optional[ExtractedField]:
    labeled = _extract_labeled_field(text, _SPECIALIZATION_LABELS, ConfidenceLevel.HIGH)
    if labeled:
        return labeled
    found = _scan_degree(text)
    if found and found[1]:
        return ExtractedField(value=found[1], confidence=ConfidenceLevel.MEDIUM, source=found[2], method="context_phrase")
    return None


# --------------------------------------------------------------------------- #
# Academic values: CGPA/GPA, percentage, marks, grade
# --------------------------------------------------------------------------- #

def _extract_cgpa(text: str) -> Optional[ExtractedField]:
    match = re.search(
        r"\b(?:CGPA|SGPA|GPA|CPI|SPI|grade\s+point\s+average)\b\s*[:\-=]?\s*(?:of\s+|is\s+)?"
        r"(\d+(?:\.\d+)?)(?:\s*(?:/|out\s+of)\s*(\d+(?:\.\d+)?))?",
        text, re.IGNORECASE,
    )
    if not match:
        return None
    value = match.group(1) if not match.group(2) else f"{match.group(1)}/{match.group(2)}"
    return ExtractedField(value=value, confidence=ConfidenceLevel.HIGH, source=match.group(0).strip(), method="pattern")


def _extract_percentage(text: str) -> Optional[ExtractedField]:
    labeled_match = re.search(r"\b(?:percentage|aggregate)\b\s*[:\-]?\s*(\d{1,3}(?:\.\d+)?)\s*(?:%|per\s*cent|percent)?", text, re.IGNORECASE)
    if labeled_match and float(labeled_match.group(1)) <= 100:
        return ExtractedField(
            value=f"{labeled_match.group(1)}%", confidence=ConfidenceLevel.HIGH,
            source=labeled_match.group(0).strip(), method="label",
        )
    bare_match = re.search(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*(?:%|per\s*cent\b|percent\b)", text, re.IGNORECASE)
    if bare_match and float(bare_match.group(1)) <= 100:
        return ExtractedField(
            value=f"{bare_match.group(1)}%", confidence=ConfidenceLevel.MEDIUM,
            source=bare_match.group(0).strip(), method="pattern",
        )
    return None


_FRACTION = r"(\d+(?:\.\d+)?\s*(?:/|out\s+of)\s*\d+(?:\.\d+)?)"


def _extract_marks(text: str) -> Optional[ExtractedField]:
    patterns = [
        # "Total Marks: 452/600" - preferred over per-subject marks
        r"\btotal(?:\s+marks)?(?:\s+(?:obtained|secured))?\b\s*[:\-]?\s*" + _FRACTION,
        r"\bmarks(?:\s+(?:obtained|secured))?\b\s*[:\-]?\s*" + _FRACTION,
        r"\b(?:secured|obtained|scored|awarded)\b\s*[:\-]?\s*" + _FRACTION,
        # bare number only next to an explicit "marks" label
        r"\b(?:total\s+)?marks(?:\s+(?:obtained|secured))?\b\s*[:\-]\s*(\d+(?:\.\d+)?)(?!\s*(?:%|st\b|nd\b|rd\b|th\b))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            confidence = ConfidenceLevel.HIGH if re.search(r"[:\-]", match.group(0)) else ConfidenceLevel.MEDIUM
            return ExtractedField(
                value=_WHITESPACE.sub("", match.group(1)) if "/" in match.group(1) else _WHITESPACE.sub(" ", match.group(1)).strip(),
                confidence=confidence, source=match.group(0).strip(), method="label",
            )
    return None


def _extract_grade(text: str) -> Optional[ExtractedField]:
    match = re.search(
        r"\b(?:final\s+|overall\s+|letter\s+)?grade\b\s*[:\-=]?\s*(?:of\s+|is\s+)?((?-i:[A-F][+\-]?|O|S))(?![A-Za-z])",
        text, re.IGNORECASE,
    )
    if match:
        return ExtractedField(value=match.group(1), confidence=ConfidenceLevel.HIGH, source=match.group(0).strip(), method="label")

    descriptive = re.search(
        r"(?<![A-Za-z])(?:grade|result|classification|class|division|performance|remarks?)\s*[:\-\u2013]\s*"
        r"([A-Za-z][A-Za-z +\-]{1,30})",
        text, re.IGNORECASE,
    )
    if descriptive:
        value = _clean_value(re.split(r"\s{2,}|\t", descriptive.group(1))[0])
        if value:
            return ExtractedField(value=value, confidence=ConfidenceLevel.HIGH, source=descriptive.group(0).strip(), method="label")

    sentence = re.search(
        r"\b(?:with|in|achiev\w*|secur\w*|obtain\w*|awarded|passed\s+with)\s+"
        r"((?:first|second|third|1st|2nd)\s+(?:class|division)(?:\s+with\s+distinction)?|distinction|"
        r"honou?rs?|high(?:est)?\s+distinction|merit|(?:summa\s+|magna\s+)?cum\s+laude)\b",
        text, re.IGNORECASE,
    )
    if sentence:
        return ExtractedField(
            value=sentence.group(1), confidence=ConfidenceLevel.MEDIUM,
            source=sentence.group(0).strip(), method="context_phrase",
        )
    return None


def _extract_location(text: str) -> Optional[ExtractedField]:
    found = _extract_labeled_field(text, _LOCATION_LABELS, ConfidenceLevel.HIGH, strip_quotes=False)
    if found:
        without_dates = _clean_value(_ANY_DATE_RE.sub("", found.value))
        if without_dates:
            found.value = without_dates
            return found

    # Footer/address form without an explicit "Address:" label.
    # Generic address/footer heuristic; no city, state, or country is assumed.
    address_re = re.compile(
        r"(?:road|rd\.?|street|st\.?|avenue|ave\.?|lane|ln\.?|drive|dr\.?|"
        r"boulevard|blvd\.?|nagar|colony|estate|district|sector|block|building|"
        r"floor|suite|unit|postcode|postal|zip|pin\s*code)",
        re.IGNORECASE,
    )
    for line in reversed(_non_empty_lines(text)):
        candidate = _clean_value(line, strip_quotes=False)
        if len(candidate) > 140 or _LABEL_LIKE_LINE.match(candidate):
            continue
        if re.search(r"\b(?:date|expiry|issue|birth|joining|completion)\b", candidate, re.IGNORECASE):
            continue
        if address_re.search(candidate) or (
            re.search(r"\d", candidate)
            and ("," in candidate or re.search(r"\b(?:city|state|province|country)\b", candidate, re.IGNORECASE))
        ):
            return ExtractedField(
                value=candidate, confidence=ConfidenceLevel.MEDIUM,
                source=line, method="footer_heuristic",
            )
    return None


# --------------------------------------------------------------------------- #
# Document type
# --------------------------------------------------------------------------- #

# Checked in order; the first rule that matches wins. Specific kinds come
# before the generic "certificate" catch-all.
_DOCUMENT_TYPE_RULES: List[Tuple[DocumentType, Pattern[str]]] = [
    (DocumentType.MARKSHEET, re.compile(r"mark\s*sheet|statement\s+of\s+marks|grade\s+(?:card|sheet)|report\s+card|marks\s+memo", re.I)),
    (DocumentType.TRANSCRIPT, re.compile(r"transcript", re.I)),
    (DocumentType.DIPLOMA, re.compile(r"diploma", re.I)),
    (DocumentType.DEGREE, re.compile(r"degree\s+(?:of|certificate)|bachelor(?:'s)?\s+(?:of|in)|master(?:'s)?\s+(?:of|in)|doctor(?:ate)?\s+of|\bph\.?\s?d\b|\bb\.?\s?tech\b|\bm\.?\s?tech\b|\bb\.?\s?sc\b|\bm\.?\s?sc\b", re.I)),
    (DocumentType.TRAINING_CERTIFICATE, re.compile(r"training|internship|workshop|bootcamp|seminar|webinar|course\s+completion|certificate\s+of\s+(?:completion|participation)|successfully\s+completed", re.I)),
    (DocumentType.AWARD, re.compile(r"\baward\b|\bprize\b|\bmedal\b|scholarship|appreciation|recognition|excellence|achievement|\bmerit\b|\bwinner\b|runner[- ]up", re.I)),
    (DocumentType.CREDENTIAL, re.compile(r"credential|licen[cs]e|accreditation|\bbadge\b", re.I)),
    (DocumentType.CERTIFICATE, re.compile(r"certificat|certif(?:y|ies|ied|ication)", re.I)),
]
_GENERIC_DOCUMENT_TYPE_RULES: List[Tuple[DocumentType, Pattern[str]]] = [
    (DocumentType.PASSPORT, re.compile(r"\bpassport\b|\bnationality\b", re.I)),
    (DocumentType.DRIVERS_LICENSE, re.compile(r"\bdriver'?s?\s+licen[cs]e\b|\bdriving\s+licen[cs]e\b", re.I)),
    (DocumentType.ID_CARD, re.compile(r"\b(?:identity|identification|id)\s+card\b|\bnational\s+id\b", re.I)),
    (DocumentType.INVOICE, re.compile(r"\binvoice\b|\b(?:subtotal|tax|vat|gst)\b", re.I)),
    (DocumentType.BANK_STATEMENT, re.compile(r"\bbank\s+statement\b|\baccount\s+(?:statement|balance)\b|\b(?:debit|credit)\s+transaction\b", re.I)),
    (DocumentType.EMPLOYMENT_LETTER, re.compile(r"\b(?:employment|appointment|offer)\s+letter\b|\bdate\s+of\s+joining\b", re.I)),
    (DocumentType.LEGAL_DOCUMENT, re.compile(r"\b(?:agreement|contract|affidavit|deed|notice|petition|legal\s+document)\b|\bwhereas\b", re.I)),
    (DocumentType.MEDICAL_DOCUMENT, re.compile(r"\b(?:medical|clinical)\s+(?:report|record|certificate)\b|\bpatient\s+(?:id|name)\b|\bdiagnosis\b|\bprescription\b", re.I)),
    (DocumentType.INSURANCE_DOCUMENT, re.compile(r"\binsurance\b|\bpolicy\s+(?:number|no|#)\b|\bclaim\s+(?:number|no|#)\b", re.I)),
]



def _classify_document_type(text: str, title: Optional[str] = None) -> ExtractedField:
    """Classify academic and generic documents from headings and structural signals."""
    if title:
        for doc_type, pattern in _DOCUMENT_TYPE_RULES + _GENERIC_DOCUMENT_TYPE_RULES:
            match = pattern.search(title)
            if match:
                return ExtractedField(value=doc_type.value, confidence=ConfidenceLevel.HIGH,
                                      source=match.group(0), method="heading_heuristic")
    for doc_type, pattern in _DOCUMENT_TYPE_RULES:
        match = pattern.search(text)
        if match:
            return ExtractedField(value=doc_type.value, confidence=ConfidenceLevel.MEDIUM,
                                  source=match.group(0), method="keyword")
    for doc_type, pattern in _GENERIC_DOCUMENT_TYPE_RULES:
        match = pattern.search(text)
        if match:
            return ExtractedField(value=doc_type.value, confidence=ConfidenceLevel.MEDIUM,
                                  source=match.group(0), method="keyword")
    generic_heading = re.compile(r"^\s*(?:document|form|record|statement|report|letter|notice|application|receipt|bill|order|claim|certificate)\s*$", re.IGNORECASE)
    for line in _non_empty_lines(text)[:20]:
        if generic_heading.match(line):
            return ExtractedField(value=DocumentType.OTHER.value, confidence=ConfidenceLevel.LOW,
                                  source=line, method="heading_heuristic")
    return ExtractedField(value=DocumentType.UNKNOWN.value, confidence=ConfidenceLevel.LOW,
                          source=None, method="default")


# --------------------------------------------------------------------------- #
# Field extractor registry (page-scoped; title/type/extras handled separately)
# --------------------------------------------------------------------------- #

_FIELD_EXTRACTORS: Dict[str, Callable[[str], Optional[ExtractedField]]] = {
    "recipient_name": _extract_recipient_name,
    "student_id": lambda t: _extract_id_field(t, _ID_LABELS["student_id"]),
    "certificate_number": lambda t: _extract_id_field(t, _ID_LABELS["certificate_number"]),
    "institution_name": lambda t: _extract_organization(t, _INSTITUTION_WORDS, _INSTITUTION_LABELS),
    "university_name": lambda t: _extract_organization(t, _UNIVERSITY_WORDS, _UNIVERSITY_LABELS),
    "issuer_name": _extract_issuer_name,
    "issuer_designation": _extract_issuer_designation,
    "course_name": _extract_course_name,
    "degree_name": _extract_degree_name,
    "specialization": _extract_specialization,
    "department": lambda t: _extract_labeled_field(t, _DEPARTMENT_LABELS, ConfidenceLevel.HIGH),
    "issue_date": _extract_issue_date,
    "start_date": _extract_start_date,
    "completion_date": _extract_completion_date,
    "expiry_date": _extract_expiry_date,
    "grade": _extract_grade,
    "marks": _extract_marks,
    "percentage": _extract_percentage,
    "cgpa": _extract_cgpa,
    "email": _extract_email,
    "website": _extract_website,
    "location": _extract_location,
}


# --------------------------------------------------------------------------- #
# Additional (unmodelled) labelled fields
# --------------------------------------------------------------------------- #

def _all_known_label_regexes() -> List[str]:
    known: List[str] = []
    for group in _DATE_LABELS.values():
        known.extend(group)
    for group in _ID_LABELS.values():
        known.extend(group)
    for group in (
        _QUALIFIED_NAME_LABELS, _INSTITUTION_LABELS, _UNIVERSITY_LABELS, _COURSE_LABELS, _DEGREE_LABELS,
        _SPECIALIZATION_LABELS, _DEPARTMENT_LABELS, _ISSUER_LABELS, _ISSUER_DESIGNATION_LABELS,
        _LOCATION_LABELS, _PLAIN_DATE_LABELS,
    ):
        known.extend(group)
    known.extend([
        r"name", r"cgpa|sgpa|gpa|cpi|spi", r"percentage|aggregate",
        r"(?:total\s+)?marks(?:\s+(?:obtained|secured))?",
        r"(?:final\s+|overall\s+|letter\s+)?grade|result|classification|class|division|performance|remarks?",
        r"e-?mail|website|web|url|http|https",
        r"passport(?:\s*(?:no|number|#))?", r"invoice(?:\s*(?:no|number|#))?",
        r"account(?:\s*(?:no|number|#|name|holder|balance))?",
        r"policy(?:\s*(?:no|number|#))?", r"claim(?:\s*(?:no|number|#))?",
    ])
    return known


_KNOWN_LABEL_RE = re.compile("^(?:" + "|".join("(?:" + p + ")" for p in _all_known_label_regexes()) + ")$", re.IGNORECASE)
_ANY_LABELED_LINE = re.compile(
    r"^[\d\W]*([A-Za-z][A-Za-z0-9 .()/&'\u2019#-]{1,44}?)\s*(?::|\uFF1A|\s[-\u2013\u2014]\s|\s=\s)\s*(\S.{0,200})$"
)
_MAX_ADDITIONAL_FIELDS = 40


def _extract_additional_info(pages: List[Tuple[Optional[int], str]]) -> Dict[str, ExtractedField]:
    """Keep 'Label: value' lines whose label the schema does not model."""
    extras: Dict[str, ExtractedField] = {}
    for page_number, page_text in pages:
        for raw_line in page_text.split("\n"):
            line = raw_line.strip()
            match = _ANY_LABELED_LINE.match(line)
            if not match:
                continue
            label = _WHITESPACE.sub(" ", match.group(1)).strip(" .")
            value = _clean_value(_truncate_at_next_label(match.group(2)))
            if not value or value.startswith("//") or len(label.split()) > 4:
                continue
            if _KNOWN_LABEL_RE.match(label):
                continue
            key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
            if not key or key in extras:
                continue
            extras[key] = ExtractedField(value=value, confidence=ConfidenceLevel.HIGH, source=line, method="label", page=page_number)
            if len(extras) >= _MAX_ADDITIONAL_FIELDS:
                return extras
    return extras


# --------------------------------------------------------------------------- #
# Candidate selection, confidence
# --------------------------------------------------------------------------- #

def _select_best_candidate(
    candidates: List[ExtractedField], field_name: str, warnings: List[str]
) -> Optional[ExtractedField]:
    """
    Choose the best candidate across pages: highest confidence wins, ties go to
    the earliest page. If pages disagree at the top tier, a warning is recorded
    instead of silently hiding the discrepancy.
    """
    if not candidates:
        return None

    top_rank = max(_CONFIDENCE_RANK.get(c.confidence, 0) for c in candidates)
    top_candidates = [c for c in candidates if _CONFIDENCE_RANK.get(c.confidence, 0) == top_rank]
    distinct_values = sorted({c.value for c in top_candidates})

    if len(distinct_values) > 1:
        warnings.append(
            f"Multiple differing values found for '{field_name}' across pages "
            f"({', '.join(distinct_values)}); using the first occurrence."
        )
    return top_candidates[0]


def _is_detected(name: str, extracted: Optional[ExtractedField]) -> bool:
    """An 'unknown' document type is a placeholder, not a detection."""
    if extracted is None:
        return False
    return not (name == "document_type" and extracted.value == DocumentType.UNKNOWN.value)


def _compute_overall_confidence(document_info: ExtractedDocumentInfo) -> Optional[ConfidenceLevel]:
    ranks = [
        _CONFIDENCE_RANK[extracted.confidence]
        for name in _SCHEMA_FIELD_NAMES
        if _is_detected(name, extracted := getattr(document_info, name))
    ]
    if not ranks:
        return None
    average = sum(ranks) / len(ranks)
    if average >= 2.5:
        return ConfidenceLevel.HIGH
    if average >= 1.5:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


_DATE_FIELD_NAMES = ("issue_date", "start_date", "completion_date", "expiry_date")


def _apply_document_level_rules(
    document_info: ExtractedDocumentInfo, cleaned_text: str, warnings: List[str]
) -> None:
    """Cross-field clean-up that needs the whole document."""
    # The signing authority is not the recipient.
    issuer, recipient = document_info.issuer_name, document_info.recipient_name
    if issuer and recipient and issuer.value.lower() == recipient.value.lower():
        document_info.issuer_name = None

    # Weak fallback: exactly one date in the whole document and no date field
    # found -> most likely the issue date (LOW confidence, clearly flagged).
    if not any(getattr(document_info, name) for name in _DATE_FIELD_NAMES):
        distinct_dates = {d.lower() for d in find_all_dates(cleaned_text)}
        if len(distinct_dates) == 1:
            date_str = find_all_dates(cleaned_text)[0]
            document_info.issue_date = ExtractedField(
                value=date_str, confidence=ConfidenceLevel.LOW,
                source=date_str, method="single_date_fallback",
            )
            warnings.append("Only one unlabelled date was found; it was assumed to be the issue date (low confidence).")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def extract_information(cleaned_text: Optional[str]) -> ExtractionResult:
    """
    Extract structured information from cleaned OCR/typed text using
    deterministic rules. Academic extraction remains available as a
    domain-specific layer; generic documents use universal/contextual fields.

    Args:
        cleaned_text: Cleaned text (single page, or several pages separated by
            "----- Page N -----" markers).

    Returns:
        An `ExtractionResult`. Fields that could not be found are `None`.
        `status` is:
            "empty"   - no text given
            "failed"  - text given but no field could be identified
            "success" - no errors, and the core fields were found (document type,
                        a recipient, an issuing organisation/person, and a date)
            "partial" - anything in between

    Raises:
        InvalidInputError: If `cleaned_text` is None or not a string.
        InformationExtractionError: On any other unexpected failure.
    """
    try:
        if cleaned_text is None:
            raise InvalidInputError("cleaned_text is None; expected a string.")
        if not isinstance(cleaned_text, str):
            raise InvalidInputError(f"cleaned_text must be a string, got {type(cleaned_text).__name__}.")

        if not cleaned_text.strip():
            logger.warning("Received empty cleaned text; nothing to extract.")
            return ExtractionResult(
                document_info=ExtractedDocumentInfo(),
                status="empty",
                warnings=["Cleaned text is empty; no extraction was performed."],
                errors=[],
                statistics=ExtractionStatistics(),
                overall_confidence=None,
                cleaned_text=cleaned_text,
            )

        warnings: List[str] = []
        errors: List[str] = []
        stats = ExtractionStatistics()

        pages = _split_pages(cleaned_text)
        stats.pages_processed = len(pages)
        document_info = ExtractedDocumentInfo()

        # ------------------------------------------------------------------ #
        # 1) Generic extraction: title, document context/type, and flexible
        #    label/value pairs. These are domain-neutral and run first.
        # ------------------------------------------------------------------ #
        first_page_text = pages[0][1] if pages else ""
        try:
            document_info.document_title = _extract_document_title(first_page_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Document title extraction failed: %s", exc)
            errors.append(f"Document title extraction failed: {exc}")
        if document_info.document_title is not None:
            document_info.document_title.page = pages[0][0]

        try:
            title = document_info.document_title
            title_text = title.value if title and title.confidence != ConfidenceLevel.LOW else None
            document_info.document_type = _classify_document_type(cleaned_text, title_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Document type classification failed: %s", exc)
            errors.append(f"Document type classification failed: {exc}")

        try:
            document_info.additional_info = _extract_additional_info(pages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Additional-info extraction failed: %s", exc)
            errors.append(f"Additional-info extraction failed: {exc}")

        # ------------------------------------------------------------------ #
        # 2) Domain-specific extraction: the existing academic strategies are
        #    retained and remain optional for non-academic documents.
        # ------------------------------------------------------------------ #
        for field_name, extractor in _FIELD_EXTRACTORS.items():
            candidates: List[ExtractedField] = []
            for page_number, page_text in pages:
                if not page_text.strip():
                    continue
                try:
                    result = extractor(page_text)
                except Exception as exc:  # noqa: BLE001 - one field must never break the whole run
                    logger.warning("Extractor for '%s' failed on page %s: %s", field_name, page_number, exc)
                    errors.append(f"Extractor for '{field_name}' failed on page {page_number}: {exc}")
                    continue
                if result is not None:
                    result.page = page_number
                    candidates.append(result)
            setattr(document_info, field_name, _select_best_candidate(candidates, field_name, warnings))

        try:
            _apply_document_level_rules(document_info, cleaned_text, warnings)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Document-level rules failed: %s", exc)
            errors.append(f"Document-level rules failed: {exc}")


        # Input-quality hints: extraction cannot outperform the OCR text.
        non_empty = _non_empty_lines(cleaned_text)
        letters = sum(ch.isalpha() for ch in cleaned_text)
        if len(non_empty) < 4 or letters < 60:
            warnings.append(
                f"Very little text was provided ({len(non_empty)} non-empty line(s), {letters} letters); "
                "if the document has more content, check the OCR / text-cleaning stages."
            )
        if document_info.document_type is not None and document_info.document_type.value == DocumentType.UNKNOWN.value:
            warnings.append("No known document-type signal was found; the document type remains unknown.")

        detected = [_is_detected(name, getattr(document_info, name)) for name in _SCHEMA_FIELD_NAMES]
        stats.fields_detected = sum(detected)
        stats.fields_not_detected = len(detected) - stats.fields_detected
        stats.dates_detected = len(find_all_dates(cleaned_text))
        stats.emails_detected = len(find_all_emails(cleaned_text))
        stats.urls_detected = len(find_all_urls(cleaned_text))
        stats.ids_detected = sum(
            1 for value in (document_info.student_id, document_info.certificate_number) if value is not None
        )

        overall_confidence = _compute_overall_confidence(document_info)

        has_type = _is_detected("document_type", document_info.document_type)
        has_party = any(
            getattr(document_info, name) is not None
            for name in ("institution_name", "university_name", "issuer_name")
        )
        has_date = any(getattr(document_info, name) is not None for name in _DATE_FIELD_NAMES)
        has_generic_fields = bool(document_info.additional_info) or any(
            getattr(document_info, name) is not None
            for name in ("document_title", "email", "website", "location", "certificate_number")
        )
        if stats.fields_detected == 0 and not has_generic_fields:
            status = "failed"
            warnings.append("No recognizable fields could be extracted from the provided text.")
        elif not errors and has_type and (
            (document_info.recipient_name and (has_party or has_generic_fields))
            or has_generic_fields or has_party or has_date
        ):
            status = "success"
        else:
            status = "partial"

        logger.info(
            "Information extraction complete: status=%s, fields_detected=%d/%d, overall_confidence=%s.",
            status, stats.fields_detected, len(detected), overall_confidence,
        )

        return ExtractionResult(
            document_info=document_info,
            status=status,
            warnings=warnings,
            errors=errors,
            statistics=stats,
            overall_confidence=overall_confidence,
            cleaned_text=cleaned_text,
        )

    except InvalidInputError:
        raise
    except InformationExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected error during information extraction")
        raise InformationExtractionError(f"Unexpected error during information extraction: {exc}") from exc


def extract_information_from_file(path: Path) -> ExtractionResult:
    """
    Convenience wrapper: read UTF-8 cleaned text from `path` and run
    `extract_information` on it.

    Raises:
        InvalidInputError: If the file does not exist, is not a file, or
            cannot be decoded as UTF-8.
        InformationExtractionError: If the file cannot be read for any
            other reason.
    """
    if not isinstance(path, Path):
        path = Path(path)

    if not path.exists() or not path.is_file():
        raise InvalidInputError(f"Input text file does not exist: {path}")

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidInputError(f"Failed to decode file as UTF-8: {path}") from exc
    except OSError as exc:
        raise InformationExtractionError(f"Failed to read input file: {path}") from exc

    return extract_information(text)


__all__ = [
    "InformationExtractionError",
    "InvalidInputError",
    "ConfidenceLevel",
    "DocumentType",
    "ExtractedField",
    "ExtractedDocumentInfo",
    "ExtractionStatistics",
    "ExtractionResult",
    "find_all_dates",
    "find_all_emails",
    "find_all_urls",
    "extract_information",
    "extract_information_from_file",
]