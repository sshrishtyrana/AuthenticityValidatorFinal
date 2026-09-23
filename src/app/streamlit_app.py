import sys
from pathlib import Path

import streamlit as st


# ---------------------------------------------------------
# PROJECT PATH
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------
# PROJECT MODULES
# ---------------------------------------------------------

from src.ai_detection.ai_detector import AIContentDetector
from src.document_understanding.document_classifier import DocumentClassifier
from src.ingestion.document_loader import validate_document
from src.ocr.ocr_pipeline import OCRPipeline
from src.similarity.similarity_checker import SimilarityChecker
# ---------------------------------------------------------
# STREAMLIT CONFIGURATION
# ---------------------------------------------------------

st.set_page_config(
    page_title="Academic Document Authenticity Validator",
    page_icon="🔎",
    layout="wide"
)


# ---------------------------------------------------------
# HEADER
# ---------------------------------------------------------

st.title(
    "Academic Document Authenticity Validator"
)

st.write(
    "Upload a document for automated OCR, "
    "document understanding and authenticity analysis."
)


# ---------------------------------------------------------
# FILE UPLOAD
# ---------------------------------------------------------

uploaded_file = st.file_uploader(
    "Upload Document",
    type=[
        "pdf",
        "png",
        "jpg",
        "jpeg",
        "bmp",
        "tif",
        "tiff",
        "webp"
    ]
)


# ---------------------------------------------------------
# DOCUMENT ANALYSIS
# ---------------------------------------------------------

if uploaded_file is not None:

    raw_directory = PROJECT_ROOT / "data" / "raw"

    raw_directory.mkdir(
        parents=True,
        exist_ok=True
    )

    file_path = raw_directory / uploaded_file.name

    with open(file_path, "wb") as file:
        file.write(
            uploaded_file.getbuffer()
        )

    st.success(
        f"Document uploaded successfully: "
        f"{uploaded_file.name}"
    )

    if st.button(
        "Analyze Document",
        type="primary"
    ):

        try:

            # -------------------------------------------------
            # VALIDATION
            # -------------------------------------------------

            validate_document(
                str(file_path)
            )

            # -------------------------------------------------
            # OCR
            # -------------------------------------------------

            pipeline = OCRPipeline()

            with st.spinner(
                "Extracting text from document. "
                "Please wait..."
            ):

                result = pipeline.extract(
                    str(file_path)
                )
            # -------------------------------------------------
            # DOCUMENT CLASSIFICATION
            # -------------------------------------------------

            document_classifier = DocumentClassifier()

            classification_result = document_classifier.classify(
                result["text"]
            )

            # -------------------------------------------------
            # SUMMARY
            # -------------------------------------------------

            st.success(
                "Document OCR completed successfully."
            )

            col1, col2, col3 = st.columns(3)

            with col1:

                st.metric(
                    "Pages",
                    result.get(
                        "page_count",
                        0
                    )
                )

            with col2:

                st.metric(
                    "Characters",
                    len(
                        result.get(
                            "text",
                            ""
                        )
                    )
                )

            with col3:

                pages = result.get(
                    "pages",
                    []
                )

                if pages:

                    confidence = pages[0].get(
                        "ocr_confidence",
                        {}
                    )

                    average_confidence = (
                        confidence.get(
                            "average",
                            0
                        ) * 100
                    )

                else:

                    average_confidence = 0

                st.metric(
                    "OCR Confidence",
                    f"{average_confidence:.2f}%"
                )
            # -------------------------------------------------
            # DOCUMENT CLASSIFICATION DISPLAY
            # -------------------------------------------------

            st.subheader(
                "Document Classification"
            )

            col1, col2 = st.columns(2)

            with col1:

                st.metric(
                    "Detected Document Type",
                    classification_result["document_type"]
                )

            with col2:

                st.metric(
                    "Classification Confidence",
                    f"{classification_result['confidence_percentage']}%"
                )

            with st.expander(
                    "Classification Features"
            ):

                features = classification_result.get(
                    "features",
                    {}
                )

                for feature, value in features.items():
                    st.write(
                        f"**{feature.replace('_', ' ').title()}:** "
                        f"{value}"
                    )

            # -------------------------------------------------
            # EXTRACTED TEXT
            # -------------------------------------------------

            st.subheader(
                "Extracted Text"
            )

            extracted_text = result.get(
                "text",
                ""
            )

            if extracted_text:

                st.text_area(
                    "OCR Output",
                    extracted_text,
                    height=400
                )

            else:

                st.warning(
                    "No text was extracted "
                    "from the document."
                )
            # -------------------------------------------------
            # AI CONTENT ANALYSIS
            # -------------------------------------------------

            st.subheader(
                "AI Content Analysis"
            )

            with st.spinner(
                    "Analyzing linguistic characteristics. "
                    "Please wait..."
            ):

                ai_detector = AIContentDetector()

                ai_result = ai_detector.analyze(
                    extracted_text
                )

            if ai_result["status"] == "success":

                st.metric(
                    "AI-Content Indicator",
                    f"{ai_result['indicator_percentage']}%"
                )

                st.write(
                    f"**Assessment:** "
                    f"{ai_result['assessment']}"
                )

                st.subheader(
                    "Linguistic Features"
                )

                features = ai_result.get(
                    "features",
                    {}
                )

                col1, col2, col3 = st.columns(3)

                with col1:

                    st.metric(
                        "Word Count",
                        features.get(
                            "word_count",
                            0
                        )
                    )

                    st.metric(
                        "Unique Words",
                        features.get(
                            "unique_word_count",
                            0
                        )
                    )

                with col2:

                    st.metric(
                        "Sentence Count",
                        features.get(
                            "sentence_count",
                            0
                        )
                    )

                    st.metric(
                        "Vocabulary Ratio",
                        f"{features.get('vocabulary_ratio', 0):.4f}"
                    )

                with col3:

                    st.metric(
                        "Repetition Ratio",
                        f"{features.get('repetition_ratio', 0):.4f}"
                    )

                    st.metric(
                        "Lexical Complexity",
                        f"{features.get('lexical_complexity', 0):.4f}"
                    )

            else:

                st.warning(
                    ai_result.get(
                        "assessment",
                        "Insufficient text for AI-content analysis."
                    )
                )

            # -------------------------------------------------
            # OCR CONFIDENCE
            # -------------------------------------------------

            if pages:

                st.subheader(
                    "OCR Confidence"
                )

                confidence = pages[0].get(
                    "ocr_confidence",
                    {}
                )

                col1, col2, col3 = st.columns(3)

                with col1:

                    st.metric(
                        "Average",
                        f"{confidence.get('average', 0) * 100:.2f}%"
                    )

                with col2:

                    st.metric(
                        "Minimum",
                        f"{confidence.get('minimum', 0) * 100:.2f}%"
                    )

                with col3:

                    st.metric(
                        "Maximum",
                        f"{confidence.get('maximum', 0) * 100:.2f}%"
                    )


            # -------------------------------------------------
            # DOCUMENT SIMILARITY
            # -------------------------------------------------

            st.subheader(
                "Document Similarity Analysis"
            )

            with st.spinner(
                "Comparing document with reference documents. "
                "Please wait..."
            ):

                similarity_checker = SimilarityChecker()

                similarity_results = (
                    similarity_checker.compare_with_references(
                        extracted_text,
                        str(
                            PROJECT_ROOT
                            / "data"
                            / "references"
                        )
                    )
                )


            if similarity_results:

                for similarity_result in similarity_results:

                    st.write(
                        f"**{similarity_result['reference_file']}**"
                    )

                    st.progress(
                        min(
                            similarity_result[
                                "similarity_score"
                            ],
                            1.0
                        )
                    )

                    st.write(
                        "Similarity: "
                        f"{similarity_result['similarity_percentage']}%"
                    )

            else:

                st.info(
                    "No reference PDF documents "
                    "were found."
                )


            # -------------------------------------------------
            # DETECTED DOCUMENT BLOCKS
            # -------------------------------------------------

            st.subheader(
                "Detected Document Structure"
            )

            if pages:

                blocks = pages[0].get(
                    "blocks",
                    []
                )

                if blocks:

                    for index, block in enumerate(
                        blocks
                    ):

                        block_type = block.get(
                            "type",
                            "Text"
                        )

                        block_text = block.get(
                            "text",
                            ""
                        )

                        block_confidence = block.get(
                            "confidence"
                        )

                        title = (
                            f"{index + 1}. "
                            f"{block_type.title()}"
                        )

                        with st.expander(
                            title
                        ):

                            st.write(
                                block_text
                            )

                            if block_confidence is not None:

                                st.caption(
                                    "OCR confidence: "
                                    f"{block_confidence * 100:.2f}%"
                                )

                else:

                    st.info(
                        "No document blocks "
                        "were detected."
                    )


            # -------------------------------------------------
            # RAW OCR DATA
            # -------------------------------------------------

            with st.expander(
                "View Raw OCR Text"
            ):

                st.text_area(
                    "Raw OCR",
                    result.get(
                        "raw_text",
                        ""
                    ),
                    height=300
                )


        except Exception as error:

            st.error(
                f"Analysis failed: {error}"
            )