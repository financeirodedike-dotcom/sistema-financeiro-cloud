import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/financeiro.db")

if DATABASE_URL.startswith("sqlite:///./"):
    os.makedirs("data", exist_ok=True)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_lightweight_migrations()


def ensure_lightweight_migrations():
    inspector = inspect(engine)
    if "debts" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("debts")}
    new_columns = {
        "debt_date": "DATE",
        "creditor_type": "VARCHAR(60) DEFAULT 'Banco'",
        "interest_type": "VARCHAR(40) DEFAULT 'Compostos'",
    }
    with engine.begin() as connection:
        for name, ddl in new_columns.items():
            if name not in existing_columns:
                connection.execute(text(f"ALTER TABLE debts ADD COLUMN {name} {ddl}"))
