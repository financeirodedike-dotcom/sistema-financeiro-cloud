import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ClassificationRule, FinancialAccount


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    return "".join(char for char in value if not unicodedata.combining(char)).upper()


def classify_account(db: Session, company_id: int, history: str) -> FinancialAccount | None:
    normalized = normalize(history)
    rules = db.scalars(
        select(ClassificationRule)
        .join(FinancialAccount)
        .where(ClassificationRule.company_id == company_id)
        .order_by(ClassificationRule.keyword)
    ).all()
    for rule in rules:
        if normalize(rule.keyword) in normalized:
            return rule.account
    return db.scalar(
        select(FinancialAccount).where(
            FinancialAccount.company_id == company_id,
            FinancialAccount.name == "A CLASSIFICAR",
        )
    )
