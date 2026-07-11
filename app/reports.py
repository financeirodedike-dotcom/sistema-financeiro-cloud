from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Debt, FinancialAccount, Transaction


def dashboard(db: Session, company_id: int) -> dict:
    rows = db.scalars(select(Transaction).where(Transaction.company_id == company_id)).all()
    receitas = sum(row.entrada for row in rows)
    despesas = sum(row.saida for row in rows)
    pendentes = sum(1 for row in rows if not row.account or row.account.name.upper() == "A CLASSIFICAR")
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

    receita_bruta = lines["Receita Bruta"]
    outras_receitas = lines["Outras Receitas"]
    receita_total = receita_bruta + outras_receitas
    custos = lines["Custos e Compras"]
    margem_bruta = receita_total + custos

    despesas_operacionais = (
        lines["Despesas Comerciais"]
        + lines["Despesas Fixas"]
        + lines["Despesas Operacionais"]
        + lines["Despesas com Pessoal"]
        + lines["Encargos sobre Folha"]
        + lines["Impostos"]
    )
    resultado_operacional = margem_bruta + despesas_operacionais
    resultado_gerencial = resultado_operacional + lines["Resultado Financeiro"] + lines["Outras Receitas/Despesas"]
    movimentacoes_nao_operacionais = lines["Investimentos"] + lines["Distribuições/Sócios"] + lines["Transferências"]

    def row(label: str, value: float, kind: str = "line") -> dict:
        pct = (value / receita_total * 100) if receita_total else 0
        return {"line": label, "value": value, "pct": pct, "kind": kind}

    return [
        row("Receita Bruta", receita_bruta),
        row("Outras Receitas", outras_receitas),
        row("Receita Total", receita_total, "subtotal"),
        row("(-) Custos e Compras", custos),
        row("Margem Bruta", margem_bruta, "subtotal"),
        row("(-) Despesas Comerciais", lines["Despesas Comerciais"]),
        row("(-) Despesas Fixas", lines["Despesas Fixas"]),
        row("(-) Despesas Operacionais", lines["Despesas Operacionais"]),
        row("(-) Despesas com Pessoal", lines["Despesas com Pessoal"]),
        row("(-) Encargos sobre Folha", lines["Encargos sobre Folha"]),
        row("(-) Impostos", lines["Impostos"]),
        row("Resultado Operacional", resultado_operacional, "subtotal"),
        row("Resultado Financeiro", lines["Resultado Financeiro"]),
        row("Outras Receitas/Despesas", lines["Outras Receitas/Despesas"]),
        row("Resultado Gerencial", resultado_gerencial, "final"),
        row("Investimentos", lines["Investimentos"], "support"),
        row("Distribuições/Sócios", lines["Distribuições/Sócios"], "support"),
        row("Transferências", lines["Transferências"], "support"),
        row("Movimentações não operacionais", movimentacoes_nao_operacionais, "support-total"),
    ]


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
        group = row.account.group_name if row.account else "A CLASSIFICAR"
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


def debt_evolution(debt: Debt | None, months: int = 12) -> dict:
    if not debt:
        return {"debt": None, "rows": [], "months": months}

    months = max(1, min(months, 120))
    capital = debt.capital_value or 0
    rate = (debt.monthly_interest_rate or 0) / 100
    installment = debt.installment_value or 0
    balance = capital
    rows = []

    for month in range(1, months + 1):
        opening_balance = balance
        if debt.interest_type == "Simples":
            interest = capital * rate
        else:
            interest = opening_balance * rate
        balance = max(opening_balance + interest - installment, 0)
        rows.append(
            {
                "month": month,
                "opening_balance": opening_balance,
                "interest": interest,
                "installment": installment,
                "closing_balance": balance,
            }
        )
    return {"debt": debt, "rows": rows, "months": months}
