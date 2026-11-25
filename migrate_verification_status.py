
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "authenticity_validator.db"

connection = sqlite3.connect(DATABASE_PATH)

try:
    cursor = connection.cursor()

    # Check whether the column already exists
    cursor.execute("PRAGMA table_info(assignment_submissions)")
    columns = [column[1] for column in cursor.fetchall()]

    if "verification_status" not in columns:
        cursor.execute("""
            ALTER TABLE assignment_submissions
            ADD COLUMN verification_status
            VARCHAR(30) NOT NULL DEFAULT 'queued'
        """)
        print("Added verification_status column.")
    else:
        print("verification_status column already exists.")

    # Mark submissions with existing verification results as completed
    cursor.execute("""
        UPDATE assignment_submissions
        SET verification_status = 'completed'
        WHERE document_id IN (
            SELECT document_id FROM verification_results
        )
    """)

    connection.commit()
    print("Database migration completed successfully.")

except Exception:
    connection.rollback()
    raise

finally:
    connection.close()
