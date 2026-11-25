import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import User, Document
from backend.verification.duplicate_detector import detect_duplicate


class DuplicateDetectorTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.engine = create_engine(
            f"sqlite:///{self.root / 'test.db'}"
        )

        Base.metadata.create_all(self.engine)

        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.file = self.root / "certificate.pdf"
        self.file.write_bytes(
            b"sample academic certificate content"
        )

        user = User(
            full_name="Test Student",
            email="student@example.com",
            password_hash="test-hash",
            role="user",
        )

        self.db.add(user)
        self.db.commit()
        self.user_id = user.id

        document = Document(
            user_id=self.user_id,
            original_filename="certificate.pdf",
            stored_filename="certificate.pdf",
            file_path=str(self.file),
            status="uploaded",
        )

        self.db.add(document)
        self.db.commit()
        self.document_id = document.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_exact_duplicate(self):
        result = detect_duplicate(
            b"sample academic certificate content",
            self.db,
            current_user_id=self.user_id,
        )

        self.assertTrue(result["is_duplicate"])
        self.assertEqual(
            result["status"],
            "duplicate_same_user"
        )

    def test_unique_file(self):
        result = detect_duplicate(
            b"a completely different certificate",
            self.db,
            current_user_id=self.user_id,
        )

        self.assertFalse(result["is_duplicate"])
        self.assertEqual(
            result["status"],
            "unique_file"
        )

    def test_exclude_current_document(self):
        result = detect_duplicate(
            b"sample academic certificate content",
            self.db,
            current_user_id=self.user_id,
            exclude_document_id=self.document_id,
        )

        self.assertFalse(result["is_duplicate"])


if __name__ == "__main__":
    unittest.main(verbosity=2)