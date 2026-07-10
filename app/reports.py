from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Debt, FinancialAccount, Transaction


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


def purchases(db: Session, company_id: int) -> dict:
    rows = db.scalars(
        select(Transaction)
        .join(FinancialAccount)
        .where(Transaction.company_id == company_id, FinancialAccount.group_name == "Custos e Compras")
        .order_by(Transaction.date.desc())
        .limit(100)
    ).all()
    total = sum(row.saida for row in rows)
    return {"rows": rows, "total": total, "count": len(rows)}


def balance_sheet(db: Session, company_id: int) -> dict:
    rows = db.scalars(select(Transaction).where(Transaction.company_id == company_id)).all()
    debts = db.scalars(select(Debt).where(Debt.company_id == company_id, Debt.status == "Ativo")).all()
    cash_balance = sum(row.entrada - row.saida for row in rows)
    debt_total = sum(row.capital_value for row in debts)
    equity = cash_balance - debt_total
    return {
        "cash_balance": cash_balance,
        "debt_total": debt_total,
        "equity": equity,
        "assets_total": cash_balance,
        "liabilities_total": debt_total,
    }


def dashboard_charts(db: Session, company_id: int) -> dict:
    cashflow = monthly_cashflow(db, company_id)
    max_flow = max([row["entradas"] for row in cashflow] + [row["saidas"] for row in cashflow] + [1])
    flow_rows = [
        {
            **row,
            "entrada_pct": round((row["entradas"] / max_flow) * 100, 2),
            "saida_pct": round((row["saidas"] / max_flow) * 100, 2),
        }
        for row in cashflow[-12:]
    ]

    rows = db.scalars(select(Transaction).where(Transaction.company_id == company_id)).all()
    by_group = defaultdict(float)
    for row in rows:
        if row.saida <= 0:
            continue
        group = row.account.group_name if row.account else "A classificar"
        by_group[group] += row.saida
    max_group = max(list(by_group.values()) + [1])
    expense_groups = [
        {"group": group, "value": value, "pct": round((value / max_group) * 100, 2)}
        for group, value in sorted(by_group.items(), key=lambda item: item[1], reverse=True)[:8]
    ]

    debts = db.scalars(select(Debt).where(Debt.company_id == company_id, Debt.status == "Ativo")).all()
    total_debt = sum(row.capital_value for row in debts)
    monthly_installments = sum(row.installment_value for row in debts)
    return {
        "flow_rows": flow_rows,
        "expense_groups": expense_groups,
        "total_debt": total_debt,
        "monthly_installments": monthly_installments,
    }
