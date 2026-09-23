from pathlib import Path
import sys

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.ocr.ocr_pipeline import OCRPipeline


RAW_DATA_DIRECTORY = PROJECT_ROOT / "data" / "raw"


st.set_page_config(
    page_title="Authenticity Validator",
    page_icon="🔎",
    layout="wide"
)


st.title("🔎 Authenticity Validator for Academia")

st.write(
    "Upload a document to extract and analyze its content "
    "using OCR and document processing."
)


uploaded_file = st.file_uploader(
    "Upload a document",
    type=[
        "pdf",
        "png",
        "jpg",
        "jpeg"
    ]
)


if uploaded_file is not None:

    RAW_DATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True
    )

    file_path = (
        RAW_DATA_DIRECTORY /
        uploaded_file.name
    )

    with open(
        file_path,
        "wb"
    ) as file:

        file.write(
            uploaded_file.getbuffer()
        )

    st.success(
        f"Document uploaded: {uploaded_file.name}"
    )


    if st.button(
        "Validate Document",
        type="primary"
    ):

        try:

            with st.spinner(
                "Processing document..."
            ):

                ocr_pipeline = OCRPipeline()

                result = ocr_pipeline.extract(
                    str(file_path)
                )


            st.success(
                "Document processing completed."
            )


            st.divider()

            st.subheader(
                "Document Summary"
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

                text_length = len(
                    result.get(
                        "text",
                        ""
                    )
                )

                st.metric(
                    "Extracted Characters",
                    text_length
                )


            with col3:

                pages = result.get(
                    "pages",
                    []
                )

                confidence_values = []

                for page in pages:

                    confidence = page.get(
                        "ocr_confidence",
                        {}
                    )

                    average = confidence.get(
                        "average"
                    )

                    if average is not None:
                        confidence_values.append(
                            average
                        )


                if confidence_values:

                    overall_confidence = (
                        sum(confidence_values)
                        /
                        len(confidence_values)
                    )

                else:

                    overall_confidence = 0.0


                st.metric(
                    "OCR Confidence",
                    f"{overall_confidence * 100:.2f}%"
                )


            st.divider()


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
                    height=300
                )

            else:

                st.warning(
                    "No text was detected in the document."
                )


            st.divider()


            st.subheader(
                "OCR Confidence Details"
            )


            if pages:

                for page_number, page in enumerate(
                    pages,
                    start=1
                ):

                    confidence = page.get(
                        "ocr_confidence",
                        {}
                    )


                    st.write(
                        f"Page {page_number}"
                    )


                    confidence_col1, confidence_col2, confidence_col3 = (
                        st.columns(3)
                    )


                    with confidence_col1:

                        st.metric(
                            "Average",
                            f"{confidence.get('average', 0) * 100:.2f}%"
                        )


                    with confidence_col2:

                        st.metric(
                            "Minimum",
                            f"{confidence.get('minimum', 0) * 100:.2f}%"
                        )


                    with confidence_col3:

                        st.metric(
                            "Maximum",
                            f"{confidence.get('maximum', 0) * 100:.2f}%"
                        )


            st.divider()


            st.subheader(
                "Detected Text Blocks"
            )


            for page_number, page in enumerate(
                pages,
                start=1
            ):

                blocks = page.get(
                    "blocks",
                    []
                )


                if not blocks:

                    continue


                st.write(
                    f"Page {page_number}"
                )


                for block_number, block in enumerate(
                    blocks,
                    start=1
                ):

                    block_text = block.get(
                        "text",
                        ""
                    )

                    block_confidence = block.get(
                        "confidence"
                    )


                    if block_confidence is not None:

                        st.write(
                            f"{block_number}. "
                            f"{block_text} "
                            f"({block_confidence * 100:.2f}%)"
                        )

                    else:

                        st.write(
                            f"{block_number}. "
                            f"{block_text}"
                        )


            st.divider()


            st.subheader(
                "Raw OCR Output"
            )


            with st.expander(
                "View raw OCR data"
            ):

                st.json(
                    result
                )


        except Exception as error:

            st.error(
                "Document processing failed."
            )

            st.exception(
                error
            )