from collections import defaultdict
from datetime import date
from calendar import monthrange

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import BankReconciliation, CashflowPlan, Debt, FinancialAccount, Transaction, TransactionSplit


def load_transactions(db: Session, company_id: int) -> list[Transaction]:
    return db.scalars(
        select(Transaction)
        .where(Transaction.company_id == company_id)
        .options(
            selectinload(Transaction.account),
            selectinload(Transaction.splits).selectinload(TransactionSplit.account),
        )
    ).all()


def transaction_is_accounted(row: Transaction) -> bool:
    if row.splits:
        return any(split.account and split.account.name.upper() != "A CLASSIFICAR" for split in row.splits)
    return bool(row.account and row.account.name.upper() != "A CLASSIFICAR")


def classified_entries(rows: list[Transaction]) -> list[dict]:
    entries = []
    for row in rows:
        if row.splits:
            for split in row.splits:
                entries.append(
                    {
                        "transaction": row,
                        "account": split.account,
                        "entrada": split.entrada,
                        "saida": split.saida,
                    }
                )
        else:
            entries.append(
                {
                    "transaction": row,
                    "account": row.account,
                    "entrada": row.entrada,
                    "saida": row.saida,
                }
            )
    return entries


def dashboard(db: Session, company_id: int, rows: list[Transaction] | None = None) -> dict:
    rows = rows if rows is not None else load_transactions(db, company_id)
    receitas = sum(row.entrada for row in rows)
    despesas = sum(row.saida for row in rows)
    pendentes = sum(1 for row in rows if not transaction_is_accounted(row))
    return {
        "receitas": receitas,
        "despesas": despesas,
        "resultado": receitas - despesas,
        "saldo": receitas - despesas,
        "pendentes": pendentes,
        "total_lancamentos": len(rows),
    }


def monthly_cashflow(db: Session, company_id: int, rows: list[Transaction] | None = None) -> list[dict]:
    rows = rows if rows is not None else load_transactions(db, company_id)
    reconciliations = db.scalars(
        select(BankReconciliation).where(BankReconciliation.company_id == company_id)
    ).all()
    by_month = defaultdict(lambda: {"entradas": 0, "saidas": 0})
    opening_by_month = defaultdict(float)
    for row in rows:
        key = row.date.strftime("%Y-%m")
        by_month[key]["entradas"] += row.entrada
        by_month[key]["saidas"] += row.saida
    for reconciliation in reconciliations:
        opening_by_month[reconciliation.month] += reconciliation.opening_balance or 0

    saldo = 0
    output = []
    for month in sorted(by_month):
        saldo_inicial = opening_by_month[month] if month in opening_by_month else saldo
        entradas = by_month[month]["entradas"]
        saidas = by_month[month]["saidas"]
        saldo_mes = entradas - saidas
        saldo = saldo_inicial + saldo_mes
        output.append(
            {
                "month": month,
                "saldo_inicial": saldo_inicial,
                "entradas": entradas,
                "saidas": saidas,
                "saldo_mes": saldo_mes,
                "saldo_acumulado": saldo,
                "saldo_final": saldo,
                "saldo_inicial_informado": month in opening_by_month,
            }
        )
    return output


def cashflow_diagnostics(db: Session, company_id: int, rows: list[Transaction] | None = None) -> dict:
    rows = rows if rows is not None else load_transactions(db, company_id)
    entries = classified_entries(rows)
    by_month = defaultdict(lambda: {"entradas": 0, "saidas": 0, "saldo": 0})
    by_bank = defaultdict(lambda: {"entradas": 0, "saidas": 0, "saldo": 0})
    by_account = defaultdict(lambda: {"entradas": 0, "saidas": 0, "saldo": 0})
    by_group = defaultdict(float)
    unclassified_outflows = 0
    for row in rows:
        month = row.date.strftime("%Y-%m")
        movement = row.entrada - row.saida
        bank = row.bank or "Sem banco/caixa"
        by_month[month]["entradas"] += row.entrada
        by_month[month]["saidas"] += row.saida
        by_month[month]["saldo"] += movement
        by_bank[bank]["entradas"] += row.entrada
        by_bank[bank]["saidas"] += row.saida
        by_bank[bank]["saldo"] += movement
    for entry in entries:
        account = entry["account"]
        account_name = account.name if account else "A CLASSIFICAR"
        entrada = entry["entrada"]
        saida = entry["saida"]
        by_account[account_name]["entradas"] += entrada
        by_account[account_name]["saidas"] += saida
        by_account[account_name]["saldo"] += entrada - saida
        if saida > 0:
            group = account.group_name if account else "A CLASSIFICAR"
            by_group[group] += saida
            if group == "A CLASSIFICAR":
                unclassified_outflows += saida

    month_rows = [
        {"month": month, **values}
        for month, values in sorted(by_month.items(), key=lambda item: item[1]["saldo"])
    ]
    group_rows = [
        {"group": group, "value": value}
        for group, value in sorted(by_group.items(), key=lambda item: item[1], reverse=True)
    ]
    bank_rows = [
        {"bank": bank, **values}
        for bank, values in sorted(by_bank.items(), key=lambda item: abs(item[1]["saldo"]), reverse=True)
    ]
    account_rows = [
        {"account": account, **values}
        for account, values in sorted(by_account.items(), key=lambda item: abs(item[1]["saldo"]), reverse=True)
    ]
    negative_months_total = sum(row["saldo"] for row in month_rows if row["saldo"] < 0)
    positive_months_total = sum(row["saldo"] for row in month_rows if row["saldo"] > 0)
    return {
        "worst_months": month_rows[:5],
        "month_breakdown": month_rows,
        "bank_breakdown": bank_rows[:10],
        "account_breakdown": account_rows[:10],
        "expense_groups": group_rows[:6],
        "unclassified_outflows": unclassified_outflows,
        "negative_months_total": negative_months_total,
        "positive_months_total": positive_months_total,
        "net_difference": positive_months_total + negative_months_total,
    }


def planned_cashflow(db: Session, company_id: int, actual_rows: list[dict] | None = None) -> dict:
    actual_rows = actual_rows if actual_rows is not None else monthly_cashflow(db, company_id)
    actual_by_month = {row["month"]: row for row in actual_rows}
    plans = db.scalars(
        select(CashflowPlan).where(CashflowPlan.company_id == company_id).order_by(CashflowPlan.month.desc())
    ).all()
    plan_by_month = {row.month: row for row in plans}
    months = sorted(set(actual_by_month) | set(plan_by_month), reverse=True)
    rows = []
    for month in months[:18]:
        actual = actual_by_month.get(month, {"entradas": 0, "saidas": 0, "saldo_mes": 0})
        plan = plan_by_month.get(month)
        planned_inflows = plan.planned_inflows if plan else 0
        planned_outflows = plan.planned_outflows if plan else 0
        planned_balance = planned_inflows - planned_outflows
        actual_balance = actual["saldo_mes"]
        rows.append(
            {
                "month": month,
                "planned_inflows": planned_inflows,
                "planned_outflows": planned_outflows,
                "planned_balance": planned_balance,
                "actual_inflows": actual["entradas"],
                "actual_outflows": actual["saidas"],
                "actual_balance": actual_balance,
                "variance": actual_balance - planned_balance,
                "notes": plan.notes if plan else "",
            }
        )
    totals = {
        "planned_inflows": sum(row["planned_inflows"] for row in rows),
        "planned_outflows": sum(row["planned_outflows"] for row in rows),
        "planned_balance": sum(row["planned_balance"] for row in rows),
        "actual_balance": sum(row["actual_balance"] for row in rows),
        "variance": sum(row["variance"] for row in rows),
    }
    return {"rows": rows, "totals": totals}


def cashflow_matrix(actual_rows: list[dict], planned_report: dict) -> dict:
    actual_by_month = {row["month"]: row for row in actual_rows}
    planned_by_month = {row["month"]: row for row in planned_report.get("rows", [])}
    months = sorted(set(actual_by_month) | set(planned_by_month))

    def actual_value(month: str, field: str) -> float:
        return actual_by_month.get(month, {}).get(field, 0) or 0

    def planned_value(month: str, field: str) -> float:
        return planned_by_month.get(month, {}).get(field, 0) or 0

    row_specs = [
        ("SALDO INICIAL", "Saldo inicial realizado", "saldo", lambda month: actual_value(month, "saldo_inicial")),
        ("ENTRADAS", "Entradas realizadas", "entrada", lambda month: actual_value(month, "entradas")),
        ("ENTRADAS", "Entradas planejadas", "planejado", lambda month: planned_value(month, "planned_inflows")),
        ("ENTRADAS", "Diferença das entradas", "variacao", lambda month: actual_value(month, "entradas") - planned_value(month, "planned_inflows")),
        ("SAÍDAS", "Saídas realizadas", "saida", lambda month: actual_value(month, "saidas")),
        ("SAÍDAS", "Saídas planejadas", "planejado", lambda month: planned_value(month, "planned_outflows")),
        ("SAÍDAS", "Diferença das saídas", "variacao", lambda month: planned_value(month, "planned_outflows") - actual_value(month, "saidas")),
        ("RESULTADO", "Saldo do mês realizado", "resultado", lambda month: actual_value(month, "saldo_mes")),
        ("RESULTADO", "Saldo do mês planejado", "planejado", lambda month: planned_value(month, "planned_balance")),
        ("RESULTADO", "Variação realizado x planejado", "variacao", lambda month: planned_value(month, "variance")),
        ("SALDO FINAL", "Saldo final realizado", "saldo", lambda month: actual_value(month, "saldo_final")),
    ]

    rows = []
    current_section = None
    for section, label, kind, getter in row_specs:
        if section != current_section:
            rows.append({"type": "section", "label": section, "cells": ["" for _month in months], "total": ""})
            current_section = section
        values = [getter(month) for month in months]
        total = values[-1] if kind == "saldo" and values else sum(values)
        rows.append({"type": "value", "label": label, "kind": kind, "cells": values, "total": total})

    return {"months": months, "rows": rows}


def bank_reconciliation_report(db: Session, company_id: int, transactions: list[Transaction] | None = None) -> dict:
    transactions = transactions if transactions is not None else load_transactions(db, company_id)
    reconciliations = db.scalars(
        select(BankReconciliation).where(BankReconciliation.company_id == company_id).order_by(BankReconciliation.month.desc(), BankReconciliation.bank)
    ).all()
    movement_by_key = defaultdict(lambda: {"entradas": 0, "saidas": 0})
    for row in transactions:
        key = (row.date.strftime("%Y-%m"), row.bank or "Sem banco")
        movement_by_key[key]["entradas"] += row.entrada
        movement_by_key[key]["saidas"] += row.saida

    reconciliation_by_key = {(row.month, row.bank): row for row in reconciliations}
    keys = sorted(set(movement_by_key) | set(reconciliation_by_key), reverse=True)
    rows = []
    for month, bank in keys:
        movement = movement_by_key.get((month, bank), {"entradas": 0, "saidas": 0})
        reconciliation = reconciliation_by_key.get((month, bank))
        opening = reconciliation.opening_balance if reconciliation else 0
        informed = reconciliation.closing_balance_informed if reconciliation else 0
        calculated = opening + movement["entradas"] - movement["saidas"]
        difference = informed - calculated
        rows.append(
            {
                "month": month,
                "bank": bank,
                "opening_balance": opening,
                "entradas": movement["entradas"],
                "saidas": movement["saidas"],
                "calculated_closing": calculated,
                "informed_closing": informed,
                "difference": difference,
                "has_informed_balance": reconciliation is not None,
                "notes": reconciliation.notes if reconciliation else "",
            }
        )
    totals = {
        "entradas": sum(row["entradas"] for row in rows),
        "saidas": sum(row["saidas"] for row in rows),
        "difference": sum(row["difference"] for row in rows if row["has_informed_balance"]),
        "pending": sum(1 for row in rows if not row["has_informed_balance"]),
    }
    return {"rows": rows[:120], "totals": totals}


def dre(db: Session, company_id: int, rows: list[Transaction] | None = None) -> list[dict]:
    rows = rows if rows is not None else load_transactions(db, company_id)
    lines = defaultdict(float)
    for entry in classified_entries(rows):
        account = entry["account"]
        line = account.dre_line if account else "Outras Receitas/Despesas"
        lines[line] += entry["entrada"] - entry["saida"]

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


def purchases(db: Session, company_id: int, rows: list[Transaction] | None = None) -> dict:
    rows = rows if rows is not None else load_transactions(db, company_id)
    purchase_entries = [
        entry
        for entry in classified_entries(rows)
        if entry["account"] and entry["account"].group_name == "Custos e Compras" and entry["saida"] > 0
    ][:100]
    total = sum(entry["saida"] for entry in purchase_entries)
    return {"rows": purchase_entries, "total": total, "count": len(purchase_entries)}


def balance_sheet(db: Session, company_id: int, rows: list[Transaction] | None = None) -> dict:
    rows = rows if rows is not None else load_transactions(db, company_id)
    debts = db.scalars(select(Debt).where(Debt.company_id == company_id, Debt.status == "Ativo")).all()
    cash_balance = sum(row.entrada - row.saida for row in rows)
    debt_total = sum(current_debt_position(row)["current_balance"] for row in debts)
    equity = cash_balance - debt_total
    return {
        "cash_balance": cash_balance,
        "debt_total": debt_total,
        "equity": equity,
        "assets_total": cash_balance,
        "liabilities_total": debt_total,
    }


def dashboard_charts(
    db: Session,
    company_id: int,
    cashflow: list[dict] | None = None,
    rows: list[Transaction] | None = None,
) -> dict:
    cashflow = cashflow if cashflow is not None else monthly_cashflow(db, company_id)
    max_flow = max([row["entradas"] for row in cashflow] + [row["saidas"] for row in cashflow] + [1])
    flow_rows = [
        {
            **row,
            "entrada_pct": round((row["entradas"] / max_flow) * 100, 2),
            "saida_pct": round((row["saidas"] / max_flow) * 100, 2),
        }
        for row in cashflow[-12:]
    ]

    rows = rows if rows is not None else load_transactions(db, company_id)
    by_group = defaultdict(float)
    for entry in classified_entries(rows):
        if entry["saida"] <= 0:
            continue
        account = entry["account"]
        group = account.group_name if account else "A CLASSIFICAR"
        by_group[group] += entry["saida"]
    max_group = max(list(by_group.values()) + [1])
    expense_groups = [
        {"group": group, "value": value, "pct": round((value / max_group) * 100, 2)}
        for group, value in sorted(by_group.items(), key=lambda item: item[1], reverse=True)[:8]
    ]

    debts = db.scalars(select(Debt).where(Debt.company_id == company_id, Debt.status == "Ativo")).all()
    total_debt = sum(current_debt_position(row)["current_balance"] for row in debts)
    monthly_installments = sum(row.installment_value for row in debts)
    return {
        "flow_rows": flow_rows,
        "expense_groups": expense_groups,
        "total_debt": total_debt,
        "monthly_installments": monthly_installments,
    }


def add_months(value: date, months: int = 1) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def debt_evolution(debt: Debt | None, months: int = 120, reference_date: date | None = None) -> dict:
    reference_date = reference_date or date.today()
    if not debt:
        return {"debt": None, "rows": [], "months": months, "summary": {}}

    months = max(1, min(months, 120))
    capital = debt.capital_value or 0
    rate = (debt.monthly_interest_rate or 0) / 100
    installment = debt.installment_value or 0
    start_date = debt.debt_date or debt.due_date or reference_date
    first_due_date = debt.due_date or add_months(start_date)
    balance = capital
    rows = []

    period_start = start_date
    period_due = first_due_date
    for month in range(1, months + 1):
        if period_start > reference_date or balance <= 0:
            break
        period_end = min(period_due, reference_date)
        days = max((period_end - period_start).days, 0)
        opening_balance = balance
        interest_base = capital if debt.interest_type == "Simples" else opening_balance
        daily_interest = (interest_base * rate) / 30 if rate else 0
        interest = daily_interest * days
        credit_value = opening_balance + interest
        payment = min(installment, credit_value) if installment > 0 and period_due <= reference_date else 0
        balance = max(credit_value - payment, 0)
        rows.append(
            {
                "month": month,
                "period_start": period_start,
                "due_date": period_due,
                "days": days,
                "opening_balance": opening_balance,
                "rate_pct": debt.monthly_interest_rate or 0,
                "daily_interest": daily_interest,
                "interest": interest,
                "credit_value": credit_value,
                "installment": payment,
                "closing_balance": balance,
            }
        )
        period_start = period_due
        period_due = add_months(period_due)
    return {
        "debt": debt,
        "rows": rows,
        "months": months,
        "summary": {
            "reference_date": reference_date,
            "total_interest": sum(row["interest"] for row in rows),
            "total_paid": sum(row["installment"] for row in rows),
            "final_balance": rows[-1]["closing_balance"] if rows else capital,
            "rows_count": len(rows),
        },
    }


def debt_months_elapsed(debt: Debt, reference_date: date | None = None) -> int:
    reference_date = reference_date or date.today()
    start_date = debt.debt_date or debt.due_date
    if not start_date or reference_date <= start_date:
        return 0
    months = (reference_date.year - start_date.year) * 12 + (reference_date.month - start_date.month)
    if reference_date.day >= start_date.day:
        months += 1
    return max(months, 0)


def current_debt_position(debt: Debt, reference_date: date | None = None) -> dict:
    reference_date = reference_date or date.today()
    if debt.status != "Ativo":
        return {
            "months_elapsed": 0,
            "interest_total": 0,
            "paid_total": 0,
            "current_balance": 0,
            "reference_date": reference_date,
        }

    evolution = debt_evolution(debt, 120, reference_date)
    summary = evolution["summary"]

    return {
        "months_elapsed": summary["rows_count"],
        "interest_total": summary["total_interest"],
        "paid_total": summary["total_paid"],
        "current_balance": summary["final_balance"],
        "reference_date": reference_date,
    }
