from datetime import date

from pydantic import BaseModel


class AccountCreate(BaseModel):
    name: str
    group_name: str = "Outras"
    dre_line: str = "Outras Receitas/Despesas"
    cashflow_class: str = "Operacional"


class RuleCreate(BaseModel):
    keyword: str
    account_id: int


class TransactionUpdate(BaseModel):
    account_id: int | None = None
    history: str | None = None
    date: date | None = None
    notes: str | None = None
