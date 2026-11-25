
from sqlalchemy import inspect, text

from .database import engine, Base
from . import models


def migrate():
    inspector = inspect(engine)

    existing_columns = {
        column["name"]
        for column in inspector.get_columns("users")
    }

    new_columns = {
        "course": "VARCHAR(150)",
        "department": "VARCHAR(150)",
        "academic_year": "VARCHAR(50)",
        "semester": "VARCHAR(50)",
        "admission_batch": "VARCHAR(100)",
    }

    with engine.begin() as connection:
        for column_name, column_type in new_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(
                        f"ALTER TABLE users ADD COLUMN "
                        f"{column_name} {column_type}"
                    )
                )
                print(f"Added users.{column_name}")
            else:
                print(f"Already exists: users.{column_name}")

    # Create new assignment-related tables.
    Base.metadata.create_all(bind=engine)

    print("\nDatabase migration completed successfully.")


if __name__ == "__main__":
    migrate()
