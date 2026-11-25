import sqlite3
import shutil
from pathlib import Path

from backend.database import DATABASE_PATH

db_path = Path(DATABASE_PATH)

if not db_path.exists():
    raise FileNotFoundError(f"Database not found: {db_path}")

# Create a backup before modifying the database
backup_path = db_path.with_name("authenticity_validator_backup.db")
shutil.copy2(db_path, backup_path)

print(f"Backup created: {backup_path}")

# Connect to the existing database
connection = sqlite3.connect(db_path)

try:
    cursor = connection.cursor()

    # Check existing columns
    cursor.execute("PRAGMA table_info(documents)")
    columns = [column[1] for column in cursor.fetchall()]

    if "document_category" not in columns:
        cursor.execute("""
            ALTER TABLE documents
            ADD COLUMN document_category VARCHAR(50)
            NOT NULL DEFAULT 'academic'
        """)

        connection.commit()
        print("SUCCESS: document_category column added.")

    else:
        print("Column already exists. No changes needed.")

    # Verify the column
    cursor.execute("PRAGMA table_info(documents)")
    print("Current documents columns:")
    for column in cursor.fetchall():
        print(column[1])

finally:
    connection.close()