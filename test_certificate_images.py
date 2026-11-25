from pathlib import Path
from PIL import Image
import pytesseract
import re
import pytesseract

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

BASE_DIR = Path(__file__).resolve().parent
TEST_DIR = BASE_DIR / "test_documents"

CERTIFICATES = {
    "Peter Weaver": TEST_DIR / "peter_weaver.png",
    "Riya Verma": TEST_DIR / "riya_verma.png",
}

def extract_certificate_id(image_path):
    image = Image.open(image_path).convert("RGB")
    text = pytesseract.image_to_string(image)

    print("\nExtracted text:")
    print(text)

    match = re.search(
        r"Certificate\s*ID\s*:\s*([\d-]+)",
        text,
        re.IGNORECASE,
    )

    return match.group(1) if match else None


results = {}

for student, path in CERTIFICATES.items():
    if not path.exists():
        print(f"File not found: {path}")
        continue

    print(f"\nTesting certificate: {student}")
    results[student] = extract_certificate_id(path)

print("\n========== CERTIFICATE CODE TEST ==========")

for student, code in results.items():
    print(f"{student}: {code}")

if len(results) == 2:
    peter_code = results["Peter Weaver"]
    riya_code = results["Riya Verma"]

    if peter_code and riya_code and peter_code == riya_code:
        print("\nRESULT: MATCHING CERTIFICATE IDs DETECTED")
        print("The documents should be flagged for further verification.")
    else:
        print("\nRESULT: No matching IDs extracted.")
        print("Check OCR output and certificate ID formatting.")