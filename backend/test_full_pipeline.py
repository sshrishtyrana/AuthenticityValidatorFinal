from pathlib import Path

from processing.preprocessing import preprocess_document
from processing.ocr import run_ocr
from processing.text_cleaning import clean_text
from processing.information_extraction import extract_information


# ============================================================
# CHANGE ONLY THIS FILE NAME
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

input_file = BASE_DIR / "test_files" / "certificate .jpeg"

output_dir = BASE_DIR / "test_files" / "processed"


try:
    # ========================================================
    # STEP 1: PREPROCESSING
    # ========================================================

    print("\n" + "=" * 60)
    print("STEP 1 - PREPROCESSING")
    print("=" * 60)

    metadata = preprocess_document(
        input_path=input_file,
        output_dir=output_dir,
    )

    print("Preprocessing successful!")
    print(f"Document type: {metadata.document_type.value}")
    print(f"Pages: {metadata.num_pages}")
    print(f"OCR required: {metadata.ocr_required}")
    print(f"Text extraction available: {metadata.text_extraction_available}")


    # ========================================================
    # STEP 2: OCR / TEXT EXTRACTION
    # ========================================================

    print("\n" + "=" * 60)
    print("STEP 2 - OCR / TEXT EXTRACTION")
    print("=" * 60)

    ocr_result = run_ocr(
        document_metadata=metadata,
        original_document_path=input_file,
        lang="eng",
        save_output=True,
    )

    print("OCR successful!")
    print(f"Pages processed: {len(ocr_result.pages)}")
    print(f"Average confidence: {ocr_result.average_confidence:.2f}%")

    if ocr_result.output_text_path:
        print(f"OCR text saved to: {ocr_result.output_text_path}")


    # ========================================================
    # STEP 3: TEXT CLEANING
    # ========================================================

    print("\n" + "=" * 60)
    print("STEP 3 - TEXT CLEANING")
    print("=" * 60)

    cleaning_result = clean_text(
        ocr_result.combined_text
    )

    print("Text cleaning successful!")
    print(f"Cleaning status: {cleaning_result.status}")
    print(
        f"Characters: "
        f"{cleaning_result.original_char_count} -> "
        f"{cleaning_result.cleaned_char_count}"
    )

    print("\nCLEANED TEXT:")
    print("-" * 60)
    print(cleaning_result.cleaned_text)


    # ========================================================
    # STEP 4: INFORMATION EXTRACTION
    # ========================================================

    print("\n" + "=" * 60)
    print("STEP 4 - INFORMATION EXTRACTION")
    print("=" * 60)

    extraction_result = extract_information(
        cleaning_result.cleaned_text
    )

    print("Information extraction completed!")

    print(f"\nStatus: {extraction_result.status}")
    print(
        f"Overall confidence: "
        f"{extraction_result.overall_confidence}"
    )


    # ========================================================
    # DISPLAY EXTRACTED INFORMATION
    # ========================================================

    info = extraction_result.document_info

    fields = [
        "document_title",
        "document_type",
        "recipient_name",
        "student_id",
        "certificate_number",
        "institution_name",
        "university_name",
        "issuer_name",
        "issuer_designation",
        "course_name",
        "degree_name",
        "specialization",
        "department",
        "issue_date",
        "start_date",
        "completion_date",
        "expiry_date",
        "grade",
        "marks",
        "percentage",
        "cgpa",
        "email",
        "website",
        "location",
    ]

    print("\n" + "=" * 60)
    print("EXTRACTED INFORMATION")
    print("=" * 60)

    for field_name in fields:

        field = getattr(info, field_name)

        if field is not None:

            print(f"\n{field_name}: {field.value}")
            print(f"  Confidence: {field.confidence.value}")
            print(f"  Method: {field.method}")
            print(f"  Source: {field.source}")

        else:

            print(f"\n{field_name}: None")


    # ========================================================
    # STATISTICS
    # ========================================================

    stats = extraction_result.statistics

    print("\n" + "=" * 60)
    print("EXTRACTION STATISTICS")
    print("=" * 60)

    print(f"Pages processed: {stats.pages_processed}")
    print(f"Fields detected: {stats.fields_detected}")
    print(f"Fields not detected: {stats.fields_not_detected}")
    print(f"Dates detected: {stats.dates_detected}")
    print(f"IDs detected: {stats.ids_detected}")
    print(f"Emails detected: {stats.emails_detected}")
    print(f"URLs detected: {stats.urls_detected}")


    # ========================================================
    # WARNINGS / ERRORS
    # ========================================================

    if extraction_result.warnings:

        print("\nWARNINGS:")

        for warning in extraction_result.warnings:
            print(f"- {warning}")


    if extraction_result.errors:

        print("\nERRORS:")

        for error in extraction_result.errors:
            print(f"- {error}")


    print("\n" + "=" * 60)
    print("FULL PIPELINE TEST COMPLETED")
    print("=" * 60)


except Exception as error:

    print("\n" + "=" * 60)
    print("PIPELINE TEST FAILED")
    print("=" * 60)

    print(f"Error: {error}")