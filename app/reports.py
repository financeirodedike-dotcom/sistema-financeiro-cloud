from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction


def dashboard(db: Session, company_id: int) -> dict:
    rows = db.scalars(select(Transaction).where(Transaction.company_id == company_id)).all()
    receitas = sum(row.entrada for row in rows)
    despesas = sum(row.saida for row in rows)
    pendentes = sum(1 for row in rows if not row.account or row.account.name == "A classificar")
    return {
        "receitas": receitas,
        "despesas": despesas,
        "resultado": receitas - despesas,
        "saldo": receitas - despesas,
        "pendentes": pendentes,
        "total_lancamentos": len(rows),
    }


def monthly_cashflow(db: Session, company_id: int) -> list[dict]:
    rows = db.scalars(select(Transaction).where(Transaction.company_id == company_id)).all()
    by_month = defaultdict(lambda: {"entradas": 0, "saidas": 0})
    for row in rows:
        key = row.date.strftime("%Y-%m")
        by_month[key]["entradas"] += row.entrada
        by_month[key]["saidas"] += row.saida
    saldo = 0
    output = []
    for month in sorted(by_month):
        entradas = by_month[month]["entradas"]
        saidas = by_month[month]["saidas"]
        saldo_mes = entradas - saidas
        saldo += saldo_mes
        output.append(
            {
                "month": month,
                "entradas": entradas,
                "saidas": saidas,
                "saldo_mes": saldo_mes,
                "saldo_acumulado": saldo,
            }
        )
    return output


def dre(db: Session, company_id: int) -> list[dict]:
    rows = db.scalars(select(Transaction).where(Transaction.company_id == company_id)).all()
    lines = defaultdict(float)
    for row in rows:
        line = row.account.dre_line if row.account else "Outras Receitas/Despesas"
        lines[line] += row.entrada - row.saida
    return [{"line": line, "value": value} for line, value in sorted(lines.items())]

