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
    table_names = inspector.get_table_names()

    with engine.begin() as connection:
        if "debts" in table_names:
            existing_columns = {column["name"] for column in inspector.get_columns("debts")}
            new_columns = {
                "debt_date": "DATE",
                "due_date": "DATE",
                "creditor_type": "VARCHAR(60) DEFAULT 'Banco'",
                "interest_type": "VARCHAR(40) DEFAULT 'Compostos'",
            }
            for name, ddl in new_columns.items():
                if name not in existing_columns:
                    connection.execute(text(f"ALTER TABLE debts ADD COLUMN {name} {ddl}"))

        if "import_batches" in table_names:
            existing_columns = {column["name"] for column in inspector.get_columns("import_batches")}
            new_columns = {
                "bank": "VARCHAR(160) DEFAULT ''",
                "start_date": "DATE",
                "end_date": "DATE",
                "opening_balance": "FLOAT",
                "closing_balance": "FLOAT",
                "balance_source": "VARCHAR(40) DEFAULT ''",
            }
            for name, ddl in new_columns.items():
                if name not in existing_columns:
                    connection.execute(text(f"ALTER TABLE import_batches ADD COLUMN {name} {ddl}"))

        if "anticipations" in table_names:
            existing_columns = {column["name"] for column in inspector.get_columns("anticipations")}
            new_columns = {
                "receivable_id": "INTEGER",
                "advanced_value": "FLOAT DEFAULT 0",
            }
            for name, ddl in new_columns.items():
                if name not in existing_columns:
                    connection.execute(text(f"ALTER TABLE anticipations ADD COLUMN {name} {ddl}"))

        index_statements = [
            ("transactions", "CREATE INDEX IF NOT EXISTS idx_transactions_company_date_id ON transactions (company_id, date DESC, id DESC)"),
            ("transactions", "CREATE INDEX IF NOT EXISTS idx_transactions_company_bank_date ON transactions (company_id, bank, date DESC)"),
            ("transactions", "CREATE INDEX IF NOT EXISTS idx_transactions_company_account ON transactions (company_id, account_id)"),
            ("transactions", "CREATE INDEX IF NOT EXISTS idx_transactions_company_fitid ON transactions (company_id, fitid)"),
            ("transaction_splits", "CREATE INDEX IF NOT EXISTS idx_transaction_splits_transaction ON transaction_splits (transaction_id)"),
            ("transaction_splits", "CREATE INDEX IF NOT EXISTS idx_transaction_splits_company_account ON transaction_splits (company_id, account_id)"),
            ("import_batches", "CREATE INDEX IF NOT EXISTS idx_import_batches_company_created ON import_batches (company_id, created_at DESC)"),
            ("receivables", "CREATE INDEX IF NOT EXISTS idx_receivables_company_due ON receivables (company_id, due_date DESC)"),
            ("debts", "CREATE INDEX IF NOT EXISTS idx_debts_company_status_due ON debts (company_id, status, due_date)"),
            ("anticipations", "CREATE INDEX IF NOT EXISTS idx_anticipations_company_created ON anticipations (company_id, created_at DESC)"),
        ]
        for table_name, statement in index_statements:
            if table_name in table_names:
                connection.execute(text(statement))
