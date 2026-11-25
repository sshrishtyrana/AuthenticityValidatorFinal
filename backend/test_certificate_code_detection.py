import unittest


def normalize_certificate_code(value):
    """Normalize a certificate code before comparing it."""
    if value is None:
        return ""

    return "".join(
        char for char in str(value).upper()
        if char.isalnum()
    )


def normalize_identity(value):
    """Normalize identity information before comparison."""
    if value is None:
        return ""

    return " ".join(str(value).casefold().split())


def check_certificate_code(
    certificate_number,
    recipient_name,
    student_id,
    previous_records,
):
    """
    Compare a certificate code with previous records.

    Each previous record must contain:
    certificate_number, recipient_name, and student_id.
    """

    current_code = normalize_certificate_code(
        certificate_number
    )

    if not current_code:
        return "code_not_found"

    matches = []

    for record in previous_records:
        previous_code = normalize_certificate_code(
            record.get("certificate_number")
        )

        if previous_code != current_code:
            continue

        same_name = (
            normalize_identity(record.get("recipient_name"))
            == normalize_identity(recipient_name)
        )

        same_student_id = (
            normalize_identity(record.get("student_id"))
            == normalize_identity(student_id)
        )

        same_identity = (
            same_name
            and same_student_id
            and bool(normalize_identity(recipient_name))
            and bool(normalize_identity(student_id))
        )

        matches.append(same_identity)

    if not matches:
        return "no_previous_match"

    if any(not same_identity for same_identity in matches):
        return "possible_code_reuse"

    return "previously_seen_same_identity"


class CertificateCodeDetectionTests(unittest.TestCase):

    def setUp(self):
        self.previous_records = [
            {
                "certificate_number": "DEMO-CERT-2026-0042",
                "recipient_name": "Aarav Sharma",
                "student_id": "STU101",
            }
        ]

    def test_new_certificate_code(self):
        result = check_certificate_code(
            "DEMO-CERT-2026-0099",
            "Riya Verma",
            "STU202",
            self.previous_records,
        )

        self.assertEqual(result, "no_previous_match")

    def test_same_code_different_student(self):
        result = check_certificate_code(
            "DEMO-CERT-2026-0042",
            "Riya Verma",
            "STU202",
            self.previous_records,
        )

        self.assertEqual(result, "possible_code_reuse")

    def test_same_code_same_student(self):
        result = check_certificate_code(
            "DEMO-CERT-2026-0042",
            "Aarav Sharma",
            "STU101",
            self.previous_records,
        )

        self.assertEqual(
            result,
            "previously_seen_same_identity"
        )

    def test_certificate_code_with_different_formatting(self):
        result = check_certificate_code(
            "demo cert 2026 0042",
            "Riya Verma",
            "STU202",
            self.previous_records,
        )

        self.assertEqual(result, "possible_code_reuse")

    def test_missing_certificate_code(self):
        result = check_certificate_code(
            None,
            "Riya Verma",
            "STU202",
            self.previous_records,
        )

        self.assertEqual(result, "code_not_found")


if __name__ == "__main__":
    unittest.main(verbosity=2)