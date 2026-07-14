import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta
from xml.etree import ElementTree

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth import SESSION_COOKIE, create_session_token, current_company, current_user, hash_password, verify_password
from app.classifier import classify_account
from app.database import get_db, init_db
from app.models import Anticipation, AnticipationAttachment, BankReconciliation, CashflowPlan, ClassificationRule, Company, CompanyNote, CompanyTask, Customer, Debt, FinancialAccount, ImportBatch, Membership, Receivable, Supplier, Transaction, TransactionSplit, User
from app.ofx_parser import parse_ofx, parse_ofx_balances
from app.reports import balance_sheet, bank_reconciliation_report, cashflow_diagnostics, current_debt_position, dashboard, dashboard_charts, debt_evolution, dre, monthly_cashflow, planned_cashflow, purchases


app = FastAPI(title="Business360 AI")
templates = Jinja2Templates(directory="app/templates")


def format_brl(value: float | int | None) -> str:
    amount = float(value or 0)
    formatted = f"{abs(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if amount < 0:
        return f"-R$ {formatted}"
    return f"R$ {formatted}"


templates.env.filters["brl"] = format_brl


def format_date_br(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    parsed = parse_filter_date(str(value))
    return parsed.strftime("%d/%m/%Y") if parsed else str(value)


def format_month_br(value: str | None) -> str:
    if not value:
        return ""
    try:
        year, month = value[:7].split("-")
        return f"{month}/{year}"
    except ValueError:
        return value


templates.env.filters["date_br"] = format_date_br
templates.env.filters["month_br"] = format_month_br


DEFAULT_ACCOUNTS = [
    ("A CLASSIFICAR", "Outras", "Outras Receitas/Despesas", "Operacional"),
    ("VENDA À VISTA", "Receitas", "Receita Bruta", "Operacional"),
    ("VENDA A PRAZO ANTECIPADAS", "Receitas", "Receita Bruta", "Operacional"),
    ("VENDAS REFORMA", "Receitas", "Receita Bruta", "Operacional"),
    ("VENDA DE SERVIÇO", "Receitas", "Receita Bruta", "Operacional"),
    ("VENDA DE SUCATA", "Receitas", "Receita Bruta", "Operacional"),
    ("VENDA IMOBILIZADO", "Receitas", "Outras Receitas", "Investimento"),
    ("MATÉRIA PRIMA", "Custos e Compras", "Custos e Compras", "Operacional"),
    ("MATERIAL DE CONSUMO", "Custos e Compras", "Custos e Compras", "Operacional"),
    ("ALUGUEL DO IMÓVEL", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("ENERGIA ELÉTRICA", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("ÁGUA", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("TELEFONIA MÓVEL", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("INTERNET", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("LOCAÇÃO DE SOFTWARE", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("HONORÁRIOS ADVOCATÍCIOS", "Serviços", "Despesas Operacionais", "Operacional"),
    ("HONORÁRIOS CONTÁBEIS", "Serviços", "Despesas Operacionais", "Operacional"),
    ("COMBUSTÍVEIS", "Operacional", "Despesas Operacionais", "Operacional"),
    ("PEDÁGIO", "Operacional", "Despesas Operacionais", "Operacional"),
    ("MANUTENÇÃO DE VEÍCULOS", "Operacional", "Despesas Operacionais", "Operacional"),
    ("SEGUROS DE VEÍCULOS", "Operacional", "Despesas Operacionais", "Operacional"),
    ("IPVA", "Operacional", "Despesas Operacionais", "Operacional"),
    ("LICENCIAMENTO ANUAL", "Operacional", "Despesas Operacionais", "Operacional"),
    ("FINANCIAMENTO STRADA", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("MATERIAL DE ESCRITÓRIO", "Administrativo", "Despesas Operacionais", "Operacional"),
    ("MATERIAL DE LIMPEZA", "Administrativo", "Despesas Operacionais", "Operacional"),
    ("DIARISTA / LIMPEZA", "Administrativo", "Despesas Operacionais", "Operacional"),
    ("ALIMENTAÇÃO/ MERCADO", "Administrativo", "Despesas Operacionais", "Operacional"),
    ("FRETE COMPRAS", "Custos e Compras", "Custos e Compras", "Operacional"),
    ("MANUTENÇÃO EMPRESA", "Manutenção", "Despesas Operacionais", "Operacional"),
    ("MANUTENÇÃO MÁQUINAS E EQUIPAMENTOS", "Manutenção", "Despesas Operacionais", "Operacional"),
    ("MÓVEIS E UTENSÍLIOS", "Investimentos", "Investimentos", "Investimento"),
    ("ESTACIONAMENTO", "Operacional", "Despesas Operacionais", "Operacional"),
    ("SERASA", "Administrativo", "Despesas Operacionais", "Operacional"),
    ("HOSPEDAGEM SITE", "Marketing", "Despesas Operacionais", "Operacional"),
    ("CERTIFICADO DIGITAL", "Fiscal", "Despesas Operacionais", "Operacional"),
    ("ROSELI FAUSTIN", "Outras", "Outras Receitas/Despesas", "Operacional"),
    ("FERRAMENTAS", "Investimentos", "Investimentos", "Investimento"),
    ("EQUIPAMENTOS DE T.I.", "Investimentos", "Investimentos", "Investimento"),
    ("MARKETING", "Marketing", "Despesas Comerciais", "Operacional"),
    ("COMISSÃO", "Comercial", "Despesas Comerciais", "Operacional"),
    ("FRETE VENDAS", "Comercial", "Despesas Comerciais", "Operacional"),
    ("SIMPLES NACIONAL DAS", "Fiscal", "Impostos", "Operacional"),
    ("SERVIÇOS TERCEIRIZADOS", "Serviços", "Despesas Operacionais", "Operacional"),
    ("SALÁRIO", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA AJUDA DE CUSTO", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA VALE COMPRA/TRANSPORTE", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("HORAS EXTRAS", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("13 SALÁRIO", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("FÉRIAS FUNCIONÁRIOS", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA RESCISÃO", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA MULTA RESCISÃO 40% FGTS", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA ASSISTÊNCIA MÉDICA / PLANO DE SAÚDE", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("FARMÁCIA", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("INSS", "Pessoal", "Encargos sobre Folha", "Operacional"),
    ("FGTS", "Pessoal", "Encargos sobre Folha", "Operacional"),
    ("DESPESA IRRF SALÁRIOS", "Pessoal", "Encargos sobre Folha", "Operacional"),
    ("DESPESA UNIFORMES", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA MEDICINA OCUPACIONAL", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("EPI", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA BÔNUS PONTUALIDADE", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA ENDOMARKETING", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DEPÓSITO JUDICIAL TRABALHISTA", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("CLARA JAILMA M T COSTA", "Sócios", "Distribuições/Sócios", "Financiamento"),
    ("ANDRÉ LUIS DA COSTA", "Sócios", "Distribuições/Sócios", "Financiamento"),
    ("ALTAMIR DA COSTA", "Sócios", "Distribuições/Sócios", "Financiamento"),
    ("RODRIGO JOSÉ DA COSTA", "Sócios", "Distribuições/Sócios", "Financiamento"),
    ("LUIZ HENRIQUE DA COSTA", "Sócios", "Distribuições/Sócios", "Financiamento"),
    ("TARIFAS BANCÁRIAS", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("BORDÊRO", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("JUROS ANTECIPAÇÕES DE TÍTULOS", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("JUROS POR ATRASO", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("JUROS LIMITE", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("JUROS EMPRÉSTIMOS", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("TAXA CARTÃO CRÉDITO/DÉBITO", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("IOF", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("ROTATIVO CRESOL", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("TARIFA FLAT BB", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("TRANSFERÊNCIA ENTRE CONTAS", "Transferências", "Transferências", "Transferência"),
]

BANK_SOURCES = [
    "Banco do Brasil",
    "Caixa Interno",
    "Caixa Economica",
    "Itau",
    "Bradesco",
    "Santander",
    "Sicredi",
    "Sicoob",
    "Outro",
]


def parse_filter_date(value: str | None) -> date | None:
    if not value:
        return None
    clean_value = value.strip()
    try:
        return date.fromisoformat(clean_value)
    except ValueError:
        pass
    for pattern in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(clean_value, pattern).date()
        except ValueError:
            continue
    return None


def is_transaction_accounted(row: Transaction) -> bool:
    if row.splits:
        return any(split.account and split.account.name.upper() != "A CLASSIFICAR" for split in row.splits)
    return bool(row.account and row.account.name.upper() != "A CLASSIFICAR")


def transaction_direction_values(row: Transaction, value: float | None = None) -> tuple[float, float]:
    amount = abs(float(value if value is not None else (row.entrada or row.saida or row.amount or 0)))
    if row.entrada > 0 or row.amount > 0:
        return amount, 0
    return 0, amount


def reset_transaction_splits(db: Session, row: Transaction) -> None:
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id == row.id))


def create_full_transaction_split(db: Session, company: Company, row: Transaction, account: FinancialAccount) -> None:
    reset_transaction_splits(db, row)
    entrada, saida = transaction_direction_values(row)
    db.add(
        TransactionSplit(
            company_id=company.id,
            transaction_id=row.id,
            account_id=account.id,
            entrada=entrada,
            saida=saida,
            notes="Classificacao simples",
        )
    )
    row.account_id = account.id


def build_accounted_groups(rows: list[Transaction], account_filter_id: int | None = None) -> list[dict]:
    grouped: dict[int, dict] = {}
    for row in rows:
        entries = []
        if row.splits:
            entries = [
                {
                    "account": split.account,
                    "entrada": split.entrada,
                    "saida": split.saida,
                    "transaction": row,
                    "notes": split.notes,
                }
                for split in row.splits
                if split.account and split.account.name.upper() != "A CLASSIFICAR"
            ]
        elif row.account and row.account.name.upper() != "A CLASSIFICAR":
            entries = [
                {
                    "account": row.account,
                    "entrada": row.entrada,
                    "saida": row.saida,
                    "transaction": row,
                    "notes": row.notes,
                }
            ]
        for entry in entries:
            account = entry["account"]
            if account_filter_id and account.id != account_filter_id:
                continue
            group = grouped.setdefault(
                account.id,
                {"account": account, "entries": [], "entrada": 0, "saida": 0, "saldo": 0, "count": 0},
            )
            group["entries"].append(entry)
            group["entrada"] += entry["entrada"]
            group["saida"] += entry["saida"]
            group["saldo"] += entry["entrada"] - entry["saida"]
            group["count"] += 1
    return sorted(grouped.values(), key=lambda item: item["account"].name)


def update_reconciliation_from_ofx(
    db: Session,
    company: Company,
    bank: str,
    parsed: list[dict],
    ofx_balances: dict,
    filename: str,
) -> BankReconciliation | None:
    if not bank or not parsed or ofx_balances.get("closing_balance") is None:
        return None
    end_date = ofx_balances.get("end_date") or max(item["date"] for item in parsed)
    month = end_date.strftime("%Y-%m")
    file_inflows = sum(item["entrada"] for item in parsed if item["date"].strftime("%Y-%m") == month)
    file_outflows = sum(item["saida"] for item in parsed if item["date"].strftime("%Y-%m") == month)
    closing_balance = float(ofx_balances["closing_balance"] or 0)
    opening_balance = closing_balance - file_inflows + file_outflows
    reconciliation = db.scalar(
        select(BankReconciliation).where(
            BankReconciliation.company_id == company.id,
            BankReconciliation.month == month,
            BankReconciliation.bank == bank,
        )
    )
    if not reconciliation:
        reconciliation = BankReconciliation(company_id=company.id, month=month, bank=bank)
        db.add(reconciliation)
    reconciliation.opening_balance = opening_balance
    reconciliation.closing_balance_informed = closing_balance
    reconciliation.notes = (
        f"Saldos puxados automaticamente do OFX {filename} "
        f"({ofx_balances.get('balance_source') or 'saldo OFX'})."
    )
    reconciliation.updated_at = datetime.utcnow()
    return reconciliation


def debt_overdue_days(debt: Debt) -> int:
    if not debt.due_date or debt.status != "Ativo":
        return 0
    return max((date.today() - debt.due_date).days, 0)


def receivable_status(row: Receivable) -> str:
    if row.paid_date:
        if row.due_date and row.paid_date > row.due_date:
            return "Pago em atraso"
        return "Pago em dia"
    if row.due_date and row.due_date < date.today():
        return "Vencido"
    return row.status or "Em aberto"


def receivable_overdue_days(row: Receivable) -> int:
    if not row.due_date:
        return 0
    reference_date = row.paid_date or date.today()
    return max((reference_date - row.due_date).days, 0)


def receivable_total(row: Receivable) -> float:
    return (row.installment_value or 0) - (row.discount_value or 0) + (row.interest_value or 0)


def anticipation_cost(title_value: float, title_fee_rate: float, interest_rate: float, iof_value: float, costs_value: float) -> float:
    return (title_value * (title_fee_rate / 100)) + (title_value * (interest_rate / 100)) + iof_value + costs_value


def build_control_agenda(tasks: list[CompanyTask], debts: list[Debt], receivable_rows: list[dict]) -> dict:
    today = date.today()
    week_end = today + timedelta(days=7)
    pending_tasks = [task for task in tasks if task.status != "Concluida"]
    today_tasks = [task for task in pending_tasks if task.due_date == today]
    week_tasks = [task for task in pending_tasks if task.due_date and today <= task.due_date <= week_end]
    payable_today = [debt for debt in debts if debt.status == "Ativo" and debt.due_date == today]
    payable_week = [debt for debt in debts if debt.status == "Ativo" and debt.due_date and today <= debt.due_date <= week_end]
    receivable_today = [row for row in receivable_rows if row["item"].due_date == today and not row["status"].startswith("Pago")]
    receivable_week = [
        row
        for row in receivable_rows
        if row["item"].due_date and today <= row["item"].due_date <= week_end and not row["status"].startswith("Pago")
    ]
    calendar_days = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        day_payables = [debt for debt in payable_week if debt.due_date == day]
        day_receivables = [row for row in receivable_week if row["item"].due_date == day]
        day_tasks = [task for task in week_tasks if task.due_date == day]
        calendar_days.append(
            {
                "date": day,
                "payables": day_payables,
                "receivables": day_receivables,
                "tasks": day_tasks,
                "payable_total": sum(debt.capital_value or 0 for debt in day_payables),
                "receivable_total": sum(row["total"] for row in day_receivables),
            }
        )
    return {
        "today": today,
        "week_end": week_end,
        "today_tasks": today_tasks,
        "week_tasks": week_tasks,
        "payable_today": payable_today,
        "payable_week": payable_week,
        "receivable_today": receivable_today,
        "receivable_week": receivable_week,
        "calendar_days": calendar_days,
        "payable_today_total": sum(debt.capital_value or 0 for debt in payable_today),
        "payable_week_total": sum(debt.capital_value or 0 for debt in payable_week),
        "receivable_today_total": sum(row["total"] for row in receivable_today),
        "receivable_week_total": sum(row["total"] for row in receivable_week),
    }


def empty_control_agenda() -> dict:
    today = date.today()
    return {
        "today": today,
        "week_end": today + timedelta(days=7),
        "today_tasks": [],
        "week_tasks": [],
        "payable_today": [],
        "payable_week": [],
        "receivable_today": [],
        "receivable_week": [],
        "calendar_days": [],
        "payable_today_total": 0,
        "payable_week_total": 0,
        "receivable_today_total": 0,
        "receivable_week_total": 0,
    }


def empty_cashflow_totals() -> dict:
    return {
        "saldo_inicial": 0,
        "entradas": 0,
        "saidas": 0,
        "saldo_periodo": 0,
        "saldo_acumulado": 0,
        "saldo_final": 0,
    }


def empty_cashflow_diagnostics() -> dict:
    return {
        "worst_months": [],
        "month_breakdown": [],
        "bank_breakdown": [],
        "account_breakdown": [],
        "expense_groups": [],
        "unclassified_outflows": 0,
        "negative_months_total": 0,
        "positive_months_total": 0,
        "net_difference": 0,
    }


def empty_planned_cashflow() -> dict:
    return {
        "rows": [],
        "totals": {
            "planned_inflows": 0,
            "planned_outflows": 0,
            "planned_balance": 0,
            "actual_balance": 0,
            "variance": 0,
        },
    }


def empty_bank_reconciliation() -> dict:
    return {
        "rows": [],
        "totals": {"entradas": 0, "saidas": 0, "difference": 0, "pending": 0},
    }


def empty_balance_sheet() -> dict:
    return {
        "cash_balance": 0,
        "receivables": 0,
        "assets_total": 0,
        "debt_total": 0,
        "equity": 0,
        "monthly_installments": 0,
    }


def empty_dashboard() -> dict:
    return {
        "receitas": 0,
        "despesas": 0,
        "resultado": 0,
        "saldo": 0,
        "pendentes": 0,
        "total_lancamentos": 0,
    }


def empty_charts() -> dict:
    return {"flow_rows": [], "expense_groups": [], "total_debt": 0, "monthly_installments": 0}


def normalize_account_name(name: str) -> str:
    return " ".join(name.strip().upper().split())


def account_dedupe_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", normalize_account_name(name))
    return "".join(char for char in normalized if not unicodedata.combining(char))


def safe_upload_filename(filename: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.strip())
    return cleaned[:160] or "arquivo"


def normalize_history(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", without_accents.upper()).split())


def duplicate_transaction_exists(db: Session, company_id: int, item: dict, bank: str) -> bool:
    if item.get("fitid"):
        exists_by_fitid = db.scalar(
            select(Transaction).where(
                Transaction.company_id == company_id,
                Transaction.fitid == item["fitid"],
                Transaction.amount == item["amount"],
                Transaction.date == item["date"],
            )
        )
        if exists_by_fitid:
            return True
    same_day_amount_bank = db.scalars(
        select(Transaction).where(
            Transaction.company_id == company_id,
            Transaction.date == item["date"],
            Transaction.amount == item["amount"],
            Transaction.bank == bank,
        )
    ).all()
    incoming_history = normalize_history(item.get("history", ""))
    return any(normalize_history(row.history) == incoming_history for row in same_day_amount_bank)


def seed_company_accounts(db: Session, company: Company) -> None:
    existing_accounts = db.scalars(
        select(FinancialAccount).where(FinancialAccount.company_id == company.id).order_by(FinancialAccount.id)
    ).all()
    default_by_key = {account_dedupe_key(name): (normalize_account_name(name), group, dre_line, cashflow) for name, group, dre_line, cashflow in DEFAULT_ACCOUNTS}
    grouped_accounts: dict[str, list[FinancialAccount]] = {}
    for account in existing_accounts:
        grouped_accounts.setdefault(account_dedupe_key(account.name), []).append(account)

    by_name = {}
    for key, grouped in grouped_accounts.items():
        preferred_name = default_by_key.get(key, (normalize_account_name(grouped[0].name), "", "", ""))[0]
        keeper = next((account for account in grouped if normalize_account_name(account.name) == preferred_name), grouped[0])
        for account in grouped:
            if account.id == keeper.id:
                continue
            for transaction in db.scalars(
                select(Transaction).where(Transaction.company_id == company.id, Transaction.account_id == account.id)
            ).all():
                transaction.account_id = keeper.id
            for rule in db.scalars(
                select(ClassificationRule).where(ClassificationRule.company_id == company.id, ClassificationRule.account_id == account.id)
            ).all():
                rule.account_id = keeper.id
            account.name = f"REMOVER DUPLICADA {account.id}"
            db.delete(account)
        keeper.name = preferred_name
        by_name[key] = keeper
    db.flush()
    for name, group, dre_line, cashflow in DEFAULT_ACCOUNTS:
        normalized = normalize_account_name(name)
        key = account_dedupe_key(name)
        if key in by_name:
            account = by_name[key]
            account.name = normalized
            account.group_name = group
            account.dre_line = dre_line
            account.cashflow_class = cashflow
            continue
        db.add(
            FinancialAccount(
                company_id=company.id,
                name=normalized,
                group_name=group,
                dre_line=dre_line,
                cashflow_class=cashflow,
            )
        )
    db.commit()


def require_context(request: Request, db: Session) -> tuple[User, Company] | RedirectResponse:
    user = current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    company = current_company(user, db)
    if not company:
        return RedirectResponse("/register", status_code=303)
    return user, company


def current_membership(user: User, company: Company, db: Session) -> Membership | None:
    return db.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.company_id == company.id).limit(1)
    )


def can_manage_access(membership: Membership | None) -> bool:
    return bool(membership and membership.role in {"owner", "admin"})


@app.on_event("startup")
def startup():
    init_db()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": ""})


@app.post("/login")
def login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == email.strip().lower(), User.is_active.is_(True)))
    if not user or not verify_password(password, user.password_hash):
        return RedirectResponse("/login?erro=1", status_code=303)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(SESSION_COOKIE, create_session_token(user.id), httponly=True, samesite="lax")
    return response


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(request=request, name="forgot_password.html", context={})


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html", context={"error": ""})


@app.post("/register")
def register(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    company_name: str = Form(...),
    document: str = Form(""),
    db: Session = Depends(get_db),
):
    user = User(name=name.strip(), email=email.strip().lower(), password_hash=hash_password(password))
    company = Company(name=company_name.strip(), document=document.strip())
    db.add_all([user, company])
    db.flush()
    db.add(Membership(user_id=user.id, company_id=company.id, role="owner"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return RedirectResponse("/register?erro=email", status_code=303)
    seed_company_accounts(db, company)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(SESSION_COOKIE, create_session_token(user.id), httponly=True, samesite="lax")
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/__old-home", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    user, company = context
    seed_company_accounts(db, company)
    accounts = db.scalars(
        select(FinancialAccount).where(FinancialAccount.company_id == company.id).order_by(FinancialAccount.name)
    ).all()
    rules = db.scalars(
        select(ClassificationRule).where(ClassificationRule.company_id == company.id).order_by(ClassificationRule.keyword)
    ).all()
    date_from_raw = request.query_params.get("date_from", "")
    date_to_raw = request.query_params.get("date_to", "")
    bank_filter = request.query_params.get("bank", "")
    history_filter = request.query_params.get("history", "").strip()
    sort_order = request.query_params.get("sort", "desc")
    accounted_account_raw = request.query_params.get("accounted_account_id", "")
    try:
        accounted_account_id = int(accounted_account_raw) if accounted_account_raw else None
    except ValueError:
        accounted_account_id = None
    date_from = parse_filter_date(date_from_raw)
    date_to = parse_filter_date(date_to_raw)
    transaction_query = (
        select(Transaction)
        .where(Transaction.company_id == company.id)
        .options(
            selectinload(Transaction.account),
            selectinload(Transaction.splits).selectinload(TransactionSplit.account),
        )
    )
    if date_from:
        transaction_query = transaction_query.where(Transaction.date >= date_from)
    if date_to:
        transaction_query = transaction_query.where(Transaction.date <= date_to)
    if bank_filter:
        transaction_query = transaction_query.where(Transaction.bank == bank_filter)
    if history_filter:
        transaction_query = transaction_query.where(Transaction.history.ilike(f"%{history_filter}%"))
    if sort_order == "asc":
        transaction_query = transaction_query.order_by(Transaction.date.asc(), Transaction.id.asc())
    else:
        sort_order = "desc"
        transaction_query = transaction_query.order_by(Transaction.date.desc(), Transaction.id.desc())
    transaction_rows = db.scalars(transaction_query.limit(2000)).all()
    report_transactions = db.scalars(
        select(Transaction)
        .where(Transaction.company_id == company.id)
        .options(
            selectinload(Transaction.account),
            selectinload(Transaction.splits).selectinload(TransactionSplit.account),
        )
    ).all()
    accounted_transactions = [row for row in transaction_rows if is_transaction_accounted(row)]
    accounted_groups = build_accounted_groups(accounted_transactions, accounted_account_id)
    transactions = [row for row in transaction_rows if not is_transaction_accounted(row)]
    classified_count = len(accounted_transactions)
    pending_count = len(transactions)
    bank_options = db.scalars(
        select(Transaction.bank)
        .where(Transaction.company_id == company.id, Transaction.bank != "")
        .distinct()
        .order_by(Transaction.bank)
    ).all()
    imports = db.scalars(
        select(ImportBatch).where(ImportBatch.company_id == company.id).order_by(ImportBatch.created_at.desc()).limit(10)
    ).all()
    user_memberships = db.scalars(
        select(Membership).where(Membership.company_id == company.id).order_by(Membership.created_at.desc())
    ).all()
    customers = db.scalars(select(Customer).where(Customer.company_id == company.id).order_by(Customer.created_at.desc())).all()
    suppliers = db.scalars(select(Supplier).where(Supplier.company_id == company.id).order_by(Supplier.created_at.desc())).all()
    receivables = db.scalars(select(Receivable).where(Receivable.company_id == company.id).order_by(Receivable.due_date.desc(), Receivable.created_at.desc())).all()
    receivable_rows = [
        {
            "item": row,
            "status": receivable_status(row),
            "overdue_days": receivable_overdue_days(row),
            "total": receivable_total(row),
        }
        for row in receivables
    ]
    receivable_summary = {
        "received_on_time": sum(item["total"] for item in receivable_rows if item["status"] == "Pago em dia"),
        "received_late": sum(item["total"] for item in receivable_rows if item["status"] == "Pago em atraso"),
        "open_total": sum(item["total"] for item in receivable_rows if item["status"] == "Em aberto"),
        "overdue_total": sum(item["total"] for item in receivable_rows if item["status"] == "Vencido"),
        "discount_total": sum(row.discount_value or 0 for row in receivables),
        "interest_total": sum(row.interest_value or 0 for row in receivables),
        "count": len(receivables),
    }
    active_users = sum(1 for membership in user_memberships if membership.user.is_active)
    current_user_membership = current_membership(user, company, db)
    debts = db.scalars(select(Debt).where(Debt.company_id == company.id).order_by(Debt.created_at.desc())).all()
    notes = db.scalars(
        select(CompanyNote).where(CompanyNote.company_id == company.id).order_by(CompanyNote.created_at.desc()).limit(5)
    ).all()
    tasks = db.scalars(
        select(CompanyTask).where(CompanyTask.company_id == company.id).order_by(CompanyTask.due_date.asc(), CompanyTask.created_at.desc())
    ).all()
    control_agenda = build_control_agenda(tasks, debts, receivable_rows)
    anticipations = db.scalars(
        select(Anticipation).where(Anticipation.company_id == company.id).order_by(Anticipation.created_at.desc())
    ).all()
    anticipation_attachment_rows = db.scalars(
        select(AnticipationAttachment)
        .where(AnticipationAttachment.company_id == company.id)
        .order_by(AnticipationAttachment.created_at.desc())
    ).all()
    anticipation_attachments: dict[int, list[AnticipationAttachment]] = {}
    for attachment in anticipation_attachment_rows:
        anticipation_attachments.setdefault(attachment.anticipation_id, []).append(attachment)
    anticipation_total_titles = sum(row.title_value for row in anticipations)
    anticipation_total_cost = sum(
        anticipation_cost(row.title_value or 0, row.title_fee_rate or 0, row.interest_rate or 0, row.iof_value or 0, row.costs_value or 0)
        for row in anticipations
    )
    debt_rows = [
        {"debt": debt, "overdue_days": debt_overdue_days(debt), "position": current_debt_position(debt)}
        for debt in debts
    ]
    purchases_report = purchases(db, company.id, report_transactions)
    report_debt_id = request.query_params.get("debt_report")
    report_months_raw = request.query_params.get("debt_months", "120")
    try:
        report_months = int(report_months_raw)
    except ValueError:
        report_months = 12
    selected_debt = None
    if report_debt_id:
        try:
            selected_debt = db.scalar(select(Debt).where(Debt.company_id == company.id, Debt.id == int(report_debt_id)))
        except ValueError:
            selected_debt = None
    cashflow_report = monthly_cashflow(db, company.id, report_transactions)
    cashflow_totals = {
        "saldo_inicial": cashflow_report[0]["saldo_inicial"] if cashflow_report else 0,
        "entradas": sum(row["entradas"] for row in cashflow_report),
        "saidas": sum(row["saidas"] for row in cashflow_report),
        "saldo_periodo": sum(row["saldo_mes"] for row in cashflow_report),
        "saldo_acumulado": cashflow_report[-1]["saldo_acumulado"] if cashflow_report else 0,
        "saldo_final": cashflow_report[-1]["saldo_final"] if cashflow_report else 0,
    }
    cashflow_explanation = (
        "As saidas do periodo ficaram maiores que as entradas."
        if cashflow_totals["saldo_periodo"] < 0
        else "As entradas do periodo ficaram maiores ou iguais as saidas."
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "company": company,
            "accounts": accounts,
            "rules": rules,
            "transactions": transactions,
            "accounted_transactions": accounted_transactions[:500],
            "accounted_groups": accounted_groups,
            "classified_count": classified_count,
            "pending_count": pending_count,
            "imports": imports,
            "user_memberships": user_memberships,
            "customers": customers,
            "suppliers": suppliers,
            "receivable_rows": receivable_rows,
            "receivable_summary": receivable_summary,
            "registry_summary": {
                "customers": len(customers),
                "active_customers": sum(1 for row in customers if row.status == "Ativo"),
                "suppliers": len(suppliers),
                "active_suppliers": sum(1 for row in suppliers if row.status == "Ativo"),
            },
            "access_summary": {
                "total": len(user_memberships),
                "active": active_users,
                "inactive": len(user_memberships) - active_users,
                "admins": sum(1 for membership in user_memberships if membership.role in {"owner", "admin"}),
            },
            "current_membership": current_user_membership,
            "can_manage_access": can_manage_access(current_user_membership),
            "debts": debts,
            "notes": notes,
            "tasks": tasks,
            "control_agenda": control_agenda,
            "anticipations": anticipations,
            "anticipation_attachments": anticipation_attachments,
            "anticipation_summary": {
                "title_total": anticipation_total_titles,
                "cost_total": anticipation_total_cost,
                "net_total": anticipation_total_titles - anticipation_total_cost,
            },
            "debt_rows": debt_rows,
            "debt_report": debt_evolution(selected_debt, report_months),
            "debt_report_months": report_months,
            "bank_sources": BANK_SOURCES,
            "bank_options": bank_options,
            "filters": {
                "date_from": date_from_raw,
                "date_to": date_to_raw,
                "bank": bank_filter,
                "history": history_filter,
                "sort": sort_order,
                "accounted_account_id": str(accounted_account_id or ""),
            },
            "active_tab": request.query_params.get("tab", "dashboard"),
            "dashboard": dashboard(db, company.id, report_transactions),
            "cashflow": cashflow_report,
            "cashflow_totals": cashflow_totals,
            "cashflow_diagnostics": cashflow_diagnostics(db, company.id, report_transactions),
            "cashflow_explanation": cashflow_explanation,
            "planned_cashflow": planned_cashflow(db, company.id, cashflow_report),
            "bank_reconciliation": bank_reconciliation_report(db, company.id, report_transactions),
            "dre": dre(db, company.id, report_transactions),
            "balance": balance_sheet(db, company.id, report_transactions),
            "purchases": purchases_report,
            "charts": dashboard_charts(db, company.id, cashflow_report, report_transactions),
        },
    )


@app.get("/", response_class=HTMLResponse)
def home_fast(request: Request, db: Session = Depends(get_db)):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    user, company = context
    seed_company_accounts(db, company)

    valid_tabs = {
        "dashboard",
        "financeiro",
        "cadastros",
        "extratos",
        "contabilizados",
        "classificacao",
        "compras",
        "fluxo",
        "conciliacao",
        "dre",
        "balanco",
        "endividamento",
        "contas-pagar",
        "contas-receber",
        "antecipacoes",
        "fiscal",
        "rh",
        "vendas",
        "marketing",
        "producao",
        "mapa",
        "acessos",
    }
    active_tab = request.query_params.get("tab", "dashboard")
    if active_tab == "caixa-planejado":
        active_tab = "fluxo"
    if active_tab not in valid_tabs:
        active_tab = "dashboard"

    report_tabs = {
        "dashboard",
        "financeiro",
        "compras",
        "fluxo",
        "conciliacao",
        "dre",
        "balanco",
        "contas-pagar",
        "mapa",
    }
    needs_reports = active_tab in report_tabs
    needs_transactions = active_tab in {"extratos", "contabilizados", "contas-receber"}
    needs_registry = active_tab in {"dashboard", "cadastros", "compras", "vendas"}
    needs_receivables = active_tab in {"dashboard", "contas-receber", "antecipacoes", "mapa"}
    needs_debts = active_tab in {"dashboard", "endividamento", "contas-pagar", "balanco", "mapa"}
    needs_agenda = active_tab in {"dashboard", "mapa"}
    needs_anticipations = active_tab == "antecipacoes"
    needs_access = active_tab == "acessos"

    accounts = db.scalars(
        select(FinancialAccount).where(FinancialAccount.company_id == company.id).order_by(FinancialAccount.name)
    ).all()
    rules = (
        db.scalars(
            select(ClassificationRule).where(ClassificationRule.company_id == company.id).order_by(ClassificationRule.keyword)
        ).all()
        if active_tab == "classificacao"
        else []
    )

    date_from_raw = request.query_params.get("date_from", "")
    date_to_raw = request.query_params.get("date_to", "")
    bank_filter = request.query_params.get("bank", "")
    history_filter = request.query_params.get("history", "").strip()
    sort_order = request.query_params.get("sort", "desc")
    accounted_account_raw = request.query_params.get("accounted_account_id", "")
    try:
        accounted_account_id = int(accounted_account_raw) if accounted_account_raw else None
    except ValueError:
        accounted_account_id = None
    date_from = parse_filter_date(date_from_raw)
    date_to = parse_filter_date(date_to_raw)

    transaction_rows = []
    if needs_transactions:
        transaction_query = (
            select(Transaction)
            .where(Transaction.company_id == company.id)
            .options(
                selectinload(Transaction.account),
                selectinload(Transaction.splits).selectinload(TransactionSplit.account),
            )
        )
        if date_from:
            transaction_query = transaction_query.where(Transaction.date >= date_from)
        if date_to:
            transaction_query = transaction_query.where(Transaction.date <= date_to)
        if bank_filter:
            transaction_query = transaction_query.where(Transaction.bank == bank_filter)
        if history_filter:
            transaction_query = transaction_query.where(Transaction.history.ilike(f"%{history_filter}%"))
        if sort_order == "asc":
            transaction_query = transaction_query.order_by(Transaction.date.asc(), Transaction.id.asc())
        else:
            sort_order = "desc"
            transaction_query = transaction_query.order_by(Transaction.date.desc(), Transaction.id.desc())
        transaction_rows = db.scalars(transaction_query.limit(600)).all()

    report_transactions = (
        db.scalars(
            select(Transaction)
            .where(Transaction.company_id == company.id)
            .options(
                selectinload(Transaction.account),
                selectinload(Transaction.splits).selectinload(TransactionSplit.account),
            )
        ).all()
        if needs_reports
        else []
    )
    accounted_transactions = [row for row in transaction_rows if is_transaction_accounted(row)] if needs_transactions else []
    accounted_groups = build_accounted_groups(accounted_transactions, accounted_account_id) if active_tab == "contabilizados" else []
    transactions = [row for row in transaction_rows if not is_transaction_accounted(row)] if needs_transactions else []
    classified_count = len(accounted_transactions)
    pending_count = len(transactions)

    bank_options = (
        db.scalars(
            select(Transaction.bank)
            .where(Transaction.company_id == company.id, Transaction.bank != "")
            .distinct()
            .order_by(Transaction.bank)
        ).all()
        if active_tab in {"extratos", "contabilizados", "conciliacao"}
        else []
    )
    imports = (
        db.scalars(
            select(ImportBatch).where(ImportBatch.company_id == company.id).order_by(ImportBatch.created_at.desc()).limit(10)
        ).all()
        if active_tab in {"dashboard", "extratos"}
        else []
    )

    current_user_membership = current_membership(user, company, db)
    user_memberships = (
        db.scalars(
            select(Membership)
            .where(Membership.company_id == company.id)
            .options(selectinload(Membership.user))
            .order_by(Membership.created_at.desc())
        ).all()
        if needs_access
        else []
    )
    customers = (
        db.scalars(select(Customer).where(Customer.company_id == company.id).order_by(Customer.created_at.desc())).all()
        if needs_registry
        else []
    )
    suppliers = (
        db.scalars(select(Supplier).where(Supplier.company_id == company.id).order_by(Supplier.created_at.desc())).all()
        if needs_registry
        else []
    )
    receivables = (
        db.scalars(
            select(Receivable)
            .where(Receivable.company_id == company.id)
            .order_by(Receivable.due_date.desc(), Receivable.created_at.desc())
        ).all()
        if needs_receivables
        else []
    )
    receivable_rows = [
        {
            "item": row,
            "status": receivable_status(row),
            "overdue_days": receivable_overdue_days(row),
            "total": receivable_total(row),
        }
        for row in receivables
    ]
    receivable_summary = {
        "received_on_time": sum(item["total"] for item in receivable_rows if item["status"] == "Pago em dia"),
        "received_late": sum(item["total"] for item in receivable_rows if item["status"] == "Pago em atraso"),
        "open_total": sum(item["total"] for item in receivable_rows if item["status"] == "Em aberto"),
        "overdue_total": sum(item["total"] for item in receivable_rows if item["status"] == "Vencido"),
        "discount_total": sum(row.discount_value or 0 for row in receivables),
        "interest_total": sum(row.interest_value or 0 for row in receivables),
        "count": len(receivables),
    }
    active_users = sum(1 for membership in user_memberships if membership.user.is_active)
    debts = (
        db.scalars(select(Debt).where(Debt.company_id == company.id).order_by(Debt.created_at.desc())).all()
        if needs_debts
        else []
    )
    notes = (
        db.scalars(
            select(CompanyNote).where(CompanyNote.company_id == company.id).order_by(CompanyNote.created_at.desc()).limit(5)
        ).all()
        if active_tab == "dashboard"
        else []
    )
    tasks = (
        db.scalars(
            select(CompanyTask)
            .where(CompanyTask.company_id == company.id)
            .order_by(CompanyTask.due_date.asc(), CompanyTask.created_at.desc())
        ).all()
        if needs_agenda
        else []
    )
    control_agenda = build_control_agenda(tasks, debts, receivable_rows) if needs_agenda else empty_control_agenda()

    anticipations = (
        db.scalars(
            select(Anticipation).where(Anticipation.company_id == company.id).order_by(Anticipation.created_at.desc())
        ).all()
        if needs_anticipations
        else []
    )
    anticipation_attachment_rows = (
        db.scalars(
            select(AnticipationAttachment)
            .where(AnticipationAttachment.company_id == company.id)
            .order_by(AnticipationAttachment.created_at.desc())
        ).all()
        if needs_anticipations
        else []
    )
    anticipation_attachments: dict[int, list[AnticipationAttachment]] = {}
    for attachment in anticipation_attachment_rows:
        anticipation_attachments.setdefault(attachment.anticipation_id, []).append(attachment)
    anticipation_total_titles = sum(row.title_value for row in anticipations)
    anticipation_total_cost = sum(
        anticipation_cost(row.title_value or 0, row.title_fee_rate or 0, row.interest_rate or 0, row.iof_value or 0, row.costs_value or 0)
        for row in anticipations
    )

    debt_rows = [
        {"debt": debt, "overdue_days": debt_overdue_days(debt), "position": current_debt_position(debt)}
        for debt in debts
    ] if active_tab == "endividamento" else []
    report_debt_id = request.query_params.get("debt_report")
    report_months_raw = request.query_params.get("debt_months", "120")
    try:
        report_months = int(report_months_raw)
    except ValueError:
        report_months = 12
    selected_debt = None
    if active_tab == "endividamento" and report_debt_id:
        try:
            selected_debt = db.scalar(select(Debt).where(Debt.company_id == company.id, Debt.id == int(report_debt_id)))
        except ValueError:
            selected_debt = None

    cashflow_report = monthly_cashflow(db, company.id, report_transactions) if needs_reports else []
    cashflow_totals = (
        {
            "saldo_inicial": cashflow_report[0]["saldo_inicial"] if cashflow_report else 0,
            "entradas": sum(row["entradas"] for row in cashflow_report),
            "saidas": sum(row["saidas"] for row in cashflow_report),
            "saldo_periodo": sum(row["saldo_mes"] for row in cashflow_report),
            "saldo_acumulado": cashflow_report[-1]["saldo_acumulado"] if cashflow_report else 0,
            "saldo_final": cashflow_report[-1]["saldo_final"] if cashflow_report else 0,
        }
        if needs_reports
        else empty_cashflow_totals()
    )
    cashflow_explanation = (
        "As saidas do periodo ficaram maiores que as entradas."
        if cashflow_totals["saldo_periodo"] < 0
        else "As entradas do periodo ficaram maiores ou iguais as saidas."
    )

    dashboard_report = dashboard(db, company.id, report_transactions) if needs_reports else empty_dashboard()
    cashflow_diagnostics_report = (
        cashflow_diagnostics(db, company.id, report_transactions)
        if active_tab in {"dashboard", "financeiro"}
        else empty_cashflow_diagnostics()
    )
    planned_cashflow_report = (
        planned_cashflow(db, company.id, cashflow_report)
        if active_tab in {"dashboard", "fluxo"}
        else empty_planned_cashflow()
    )
    bank_reconciliation = (
        bank_reconciliation_report(db, company.id, report_transactions)
        if active_tab == "conciliacao"
        else empty_bank_reconciliation()
    )
    dre_report = dre(db, company.id, report_transactions) if active_tab == "dre" else []
    balance_report = balance_sheet(db, company.id, report_transactions) if active_tab in {"dashboard", "balanco"} else empty_balance_sheet()
    purchases_report = purchases(db, company.id, report_transactions) if active_tab in {"dashboard", "compras"} else {"rows": [], "total": 0, "count": 0}
    charts_report = (
        dashboard_charts(db, company.id, cashflow_report, report_transactions)
        if active_tab == "dashboard"
        else empty_charts()
    )

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "company": company,
            "accounts": accounts,
            "rules": rules,
            "transactions": transactions,
            "accounted_transactions": accounted_transactions[:500],
            "accounted_groups": accounted_groups,
            "classified_count": classified_count,
            "pending_count": pending_count,
            "imports": imports,
            "user_memberships": user_memberships,
            "customers": customers,
            "suppliers": suppliers,
            "receivable_rows": receivable_rows,
            "receivable_summary": receivable_summary,
            "registry_summary": {
                "customers": len(customers),
                "active_customers": sum(1 for row in customers if row.status == "Ativo"),
                "suppliers": len(suppliers),
                "active_suppliers": sum(1 for row in suppliers if row.status == "Ativo"),
            },
            "access_summary": {
                "total": len(user_memberships),
                "active": active_users,
                "inactive": len(user_memberships) - active_users,
                "admins": sum(1 for membership in user_memberships if membership.role in {"owner", "admin"}),
            },
            "current_membership": current_user_membership,
            "can_manage_access": can_manage_access(current_user_membership),
            "debts": debts,
            "notes": notes,
            "tasks": tasks,
            "control_agenda": control_agenda,
            "anticipations": anticipations,
            "anticipation_attachments": anticipation_attachments,
            "anticipation_summary": {
                "title_total": anticipation_total_titles,
                "cost_total": anticipation_total_cost,
                "net_total": anticipation_total_titles - anticipation_total_cost,
            },
            "debt_rows": debt_rows,
            "debt_report": debt_evolution(selected_debt, report_months),
            "debt_report_months": report_months,
            "bank_sources": BANK_SOURCES,
            "bank_options": bank_options,
            "filters": {
                "date_from": date_from_raw,
                "date_to": date_to_raw,
                "bank": bank_filter,
                "history": history_filter,
                "sort": sort_order,
                "accounted_account_id": str(accounted_account_id or ""),
            },
            "active_tab": active_tab,
            "dashboard": dashboard_report,
            "cashflow": cashflow_report,
            "cashflow_totals": cashflow_totals,
            "cashflow_diagnostics": cashflow_diagnostics_report,
            "cashflow_explanation": cashflow_explanation,
            "planned_cashflow": planned_cashflow_report,
            "bank_reconciliation": bank_reconciliation,
            "dre": dre_report,
            "balance": balance_report,
            "purchases": purchases_report,
            "charts": charts_report,
        },
    )


@app.post("/import-ofx")
async def import_ofx(
    request: Request,
    file: UploadFile = File(...),
    bank_account: str = Form(""),
    bank_other: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    content = await file.read()
    parsed = parse_ofx(content, file.filename or "arquivo.ofx")
    ofx_balances = parse_ofx_balances(content)
    source = bank_other.strip() if bank_account == "Outro" and bank_other.strip() else bank_account.strip()
    filename = file.filename or "arquivo.ofx"
    batch = ImportBatch(
        company_id=company.id,
        filename=filename,
        bank=source,
        start_date=ofx_balances.get("start_date"),
        end_date=ofx_balances.get("end_date"),
        closing_balance=ofx_balances.get("closing_balance"),
        balance_source=ofx_balances.get("balance_source") or "",
    )
    db.add(batch)
    db.flush()
    imported = 0
    skipped = 0
    for item in parsed:
        if source:
            item["bank"] = source
        if duplicate_transaction_exists(db, company.id, item, item.get("bank", "")):
            skipped += 1
            continue
        account = classify_account(db, company.id, item["history"])
        db.add(Transaction(**item, company_id=company.id, import_batch_id=batch.id, account=account))
        imported += 1
    batch.imported_count = imported
    batch.skipped_count = skipped
    reconciliation = update_reconciliation_from_ofx(db, company, source, parsed, ofx_balances, filename)
    if reconciliation:
        batch.opening_balance = reconciliation.opening_balance
    db.commit()
    balance_imported = 1 if reconciliation else 0
    return RedirectResponse(f"/?tab=extratos&imported={imported}&skipped={skipped}&balance_imported={balance_imported}", status_code=303)


@app.post("/import-ofx-balances")
async def import_ofx_balances_only(
    request: Request,
    file: UploadFile = File(...),
    bank_account: str = Form(""),
    bank_other: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    content = await file.read()
    filename = file.filename or "arquivo.ofx"
    parsed = parse_ofx(content, filename)
    ofx_balances = parse_ofx_balances(content)
    source = bank_other.strip() if bank_account == "Outro" and bank_other.strip() else bank_account.strip()
    reconciliation = update_reconciliation_from_ofx(db, company, source, parsed, ofx_balances, filename)
    db.add(
        ImportBatch(
            company_id=company.id,
            filename=f"SALDOS - {filename}",
            bank=source,
            start_date=ofx_balances.get("start_date"),
            end_date=ofx_balances.get("end_date"),
            opening_balance=reconciliation.opening_balance if reconciliation else None,
            closing_balance=ofx_balances.get("closing_balance"),
            balance_source=ofx_balances.get("balance_source") or "",
            imported_count=0,
            skipped_count=len(parsed),
        )
    )
    db.commit()
    balance_imported = 1 if reconciliation else 0
    return RedirectResponse(f"/?tab=conciliacao&balance_imported={balance_imported}", status_code=303)


@app.post("/transactions/manual")
def create_manual_transaction(
    request: Request,
    transaction_date: str = Form(...),
    history: str = Form(...),
    amount: float = Form(...),
    bank_account: str = Form("Caixa Interno"),
    bank_other: str = Form(""),
    account_id: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    source = bank_other.strip() if bank_account == "Outro" and bank_other.strip() else bank_account.strip()
    account = None
    if account_id:
        account = db.scalar(
            select(FinancialAccount).where(FinancialAccount.company_id == company.id, FinancialAccount.id == account_id)
        )
    if not account:
        account = classify_account(db, company.id, history)
    parsed_date = parse_filter_date(transaction_date)
    if not parsed_date:
        return RedirectResponse("/?tab=extratos&date_error=1", status_code=303)
    fingerprint = f"{company.id}|{parsed_date.isoformat()}|{history.strip()}|{amount}|{source}"
    db.add(
        Transaction(
            company_id=company.id,
            date=parsed_date,
            history=history.strip(),
            bank=source or "Caixa Interno",
            fitid="manual-" + hashlib.sha1(fingerprint.encode("utf-8")).hexdigest(),
            amount=amount,
            entrada=amount if amount > 0 else 0,
            saida=abs(amount) if amount < 0 else 0,
            notes=notes.strip() or "Lancamento manual",
            account=account,
        )
    )
    db.commit()
    return RedirectResponse("/?tab=extratos", status_code=303)


@app.post("/accounts")
def create_account(
    request: Request,
    name: str = Form(...),
    group_name: str = Form("Outras"),
    dre_line: str = Form("Outras Receitas/Despesas"),
    cashflow_class: str = Form("Operacional"),
    return_tab: str = Form("classificacao"),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    clean_name = normalize_account_name(name)
    default_by_key = {account_dedupe_key(default_name): normalize_account_name(default_name) for default_name, *_ in DEFAULT_ACCOUNTS}
    canonical_key = account_dedupe_key(clean_name)
    clean_name = default_by_key.get(canonical_key, clean_name)
    existing = next(
        (
            account
            for account in db.scalars(select(FinancialAccount).where(FinancialAccount.company_id == company.id)).all()
            if account_dedupe_key(account.name) == canonical_key
        ),
        None,
    )
    if existing:
        existing.name = clean_name
        existing.group_name = group_name
        existing.dre_line = dre_line
        existing.cashflow_class = cashflow_class
    else:
        db.add(
            FinancialAccount(
                company_id=company.id,
                name=clean_name,
                group_name=group_name,
                dre_line=dre_line,
                cashflow_class=cashflow_class,
            )
        )
    db.commit()
    if return_tab not in {"classificacao", "extratos", "financeiro"}:
        return_tab = "classificacao"
    return RedirectResponse(f"/?tab={return_tab}", status_code=303)


@app.post("/access/users")
def create_access_user(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("consulta"),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    user, company = context
    if not can_manage_access(current_membership(user, company, db)):
        return RedirectResponse("/?tab=acessos", status_code=303)
    clean_email = email.strip().lower()
    allowed_roles = {"owner", "admin", "financeiro", "operacao", "consulta"}
    selected_role = role if role in allowed_roles else "consulta"
    invited_user = db.scalar(select(User).where(User.email == clean_email))
    if invited_user:
        invited_user.name = name.strip() or invited_user.name
        invited_user.is_active = True
        if password.strip():
            invited_user.password_hash = hash_password(password)
    else:
        invited_user = User(name=name.strip(), email=clean_email, password_hash=hash_password(password), is_active=True)
        db.add(invited_user)
        db.flush()
    membership = db.scalar(
        select(Membership).where(Membership.user_id == invited_user.id, Membership.company_id == company.id)
    )
    if membership:
        membership.role = selected_role
    else:
        db.add(Membership(user_id=invited_user.id, company_id=company.id, role=selected_role))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return RedirectResponse("/?tab=acessos", status_code=303)


@app.post("/access/users/{membership_id}/update")
def update_access_user(
    request: Request,
    membership_id: int,
    name: str = Form(...),
    role: str = Form("consulta"),
    new_password: str = Form(""),
    is_active: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    user, company = context
    if not can_manage_access(current_membership(user, company, db)):
        return RedirectResponse("/?tab=acessos", status_code=303)
    membership = db.scalar(select(Membership).where(Membership.company_id == company.id, Membership.id == membership_id))
    allowed_roles = {"owner", "admin", "financeiro", "operacao", "consulta"}
    if membership:
        membership.user.name = name.strip() or membership.user.name
        membership.role = role if role in allowed_roles else membership.role
        if new_password.strip():
            membership.user.password_hash = hash_password(new_password.strip())
            membership.user.is_active = True
        if membership.user_id != user.id:
            membership.user.is_active = is_active == "on"
        db.commit()
    return RedirectResponse("/?tab=acessos", status_code=303)


@app.post("/rules")
def create_rule(request: Request, keyword: str = Form(...), account_id: int = Form(...), db: Session = Depends(get_db)):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    account = db.scalar(
        select(FinancialAccount).where(FinancialAccount.company_id == company.id, FinancialAccount.id == account_id)
    )
    if account:
        db.add(ClassificationRule(company_id=company.id, keyword=keyword.strip(), account_id=account.id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return RedirectResponse("/?tab=classificacao", status_code=303)


@app.post("/customers")
def create_customer(
    request: Request,
    name: str = Form(...),
    document: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    segment: str = Form(""),
    status: str = Form("Ativo"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    clean_document = document.strip()
    customer = None
    if clean_document:
        customer = db.scalar(
            select(Customer).where(Customer.company_id == company.id, Customer.document == clean_document)
        )
    if not customer:
        customer = Customer(company_id=company.id, name=name.strip())
        db.add(customer)
    customer.name = name.strip()
    customer.document = clean_document
    customer.phone = phone.strip()
    customer.email = email.strip().lower()
    customer.city = city.strip()
    customer.state = state.strip().upper()
    customer.segment = segment.strip()
    customer.status = status if status in {"Ativo", "Inativo", "Prospect"} else "Ativo"
    customer.notes = notes.strip()
    db.commit()
    return RedirectResponse("/?tab=cadastros", status_code=303)


@app.post("/suppliers")
def create_supplier(
    request: Request,
    name: str = Form(...),
    document: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    city: str = Form(""),
    state: str = Form(""),
    category: str = Form(""),
    payment_terms: str = Form(""),
    status: str = Form("Ativo"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    clean_document = document.strip()
    supplier = None
    if clean_document:
        supplier = db.scalar(
            select(Supplier).where(Supplier.company_id == company.id, Supplier.document == clean_document)
        )
    if not supplier:
        supplier = Supplier(company_id=company.id, name=name.strip())
        db.add(supplier)
    supplier.name = name.strip()
    supplier.document = clean_document
    supplier.phone = phone.strip()
    supplier.email = email.strip().lower()
    supplier.city = city.strip()
    supplier.state = state.strip().upper()
    supplier.category = category.strip()
    supplier.payment_terms = payment_terms.strip()
    supplier.status = status if status in {"Ativo", "Inativo", "Bloqueado"} else "Ativo"
    supplier.notes = notes.strip()
    db.commit()
    return RedirectResponse("/?tab=cadastros", status_code=303)


@app.post("/receivables")
def create_receivable(
    request: Request,
    due_date: str = Form(""),
    customer_name: str = Form(...),
    account_id: str = Form(""),
    description: str = Form(""),
    document_number: str = Form(""),
    installment: str = Form(""),
    bank_account: str = Form(""),
    status: str = Form("Em aberto"),
    paid_date: str = Form(""),
    installment_value: float = Form(0),
    total_value: float = Form(0),
    discount_value: float = Form(0),
    interest_value: float = Form(0),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    allowed_status = {"Em aberto", "Pago em dia", "Pago em atraso", "Vencido"}
    db.add(
        Receivable(
            company_id=company.id,
            due_date=parse_filter_date(due_date),
            customer_name=customer_name.strip(),
            account_id=int(account_id) if account_id else None,
            description=description.strip(),
            document_number=document_number.strip(),
            installment=installment.strip(),
            bank_account=bank_account.strip(),
            status=status if status in allowed_status else "Em aberto",
            paid_date=parse_filter_date(paid_date),
            installment_value=installment_value,
            total_value=total_value or installment_value,
            discount_value=discount_value,
            interest_value=interest_value,
            notes=notes.strip(),
        )
    )
    db.commit()
    return RedirectResponse("/?tab=contas-receber", status_code=303)


@app.post("/receivables/{receivable_id}/anticipate")
def anticipate_receivable(
    request: Request,
    receivable_id: int,
    anticipation_date: str = Form(""),
    counterparty: str = Form(...),
    counterparty_type: str = Form("Empresa"),
    advanced_value: float = Form(0),
    interest_rate: float = Form(0),
    title_fee_rate: float = Form(0),
    iof_value: float = Form(0),
    costs_value: float = Form(0),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    receivable = db.scalar(select(Receivable).where(Receivable.company_id == company.id, Receivable.id == receivable_id))
    if receivable:
        title_value = receivable_total(receivable)
        estimated_cost = anticipation_cost(title_value, title_fee_rate, interest_rate, iof_value, costs_value)
        final_advanced = advanced_value if advanced_value > 0 else max(title_value - estimated_cost, 0)
        db.add(
            Anticipation(
                company_id=company.id,
                receivable_id=receivable.id,
                anticipation_date=parse_filter_date(anticipation_date) or date.today(),
                counterparty=counterparty.strip(),
                counterparty_type=counterparty_type,
                title_value=title_value,
                advanced_value=final_advanced,
                title_fee_rate=title_fee_rate,
                interest_rate=interest_rate,
                iof_value=iof_value,
                costs_value=costs_value,
                notes=notes.strip() or f"Antecipacao do titulo {receivable.document_number or receivable.description}",
            )
        )
        receivable.notes = " | ".join(part for part in [receivable.notes, f"Antecipado com {counterparty.strip()}"] if part)
        db.commit()
    return RedirectResponse("/?tab=contas-receber", status_code=303)


@app.post("/receivables/{receivable_id}/update")
def update_receivable(
    request: Request,
    receivable_id: int,
    status: str = Form("Em aberto"),
    paid_date: str = Form(""),
    discount_value: float = Form(0),
    interest_value: float = Form(0),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    row = db.scalar(select(Receivable).where(Receivable.company_id == company.id, Receivable.id == receivable_id))
    allowed_status = {"Em aberto", "Pago em dia", "Pago em atraso", "Vencido"}
    if row:
        row.status = status if status in allowed_status else row.status
        row.paid_date = parse_filter_date(paid_date)
        row.discount_value = discount_value
        row.interest_value = interest_value
        db.commit()
    return RedirectResponse("/?tab=contas-receber", status_code=303)


@app.post("/notes")
def create_note(
    request: Request,
    title: str = Form(""),
    content: str = Form(...),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    db.add(CompanyNote(company_id=company.id, title=title.strip(), content=content.strip()))
    db.commit()
    return RedirectResponse("/?tab=dashboard", status_code=303)


@app.post("/tasks")
def create_task(
    request: Request,
    due_date: str = Form(""),
    description: str = Form(...),
    priority: str = Form("Normal"),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    db.add(
        CompanyTask(
            company_id=company.id,
            due_date=parse_filter_date(due_date),
            description=description.strip(),
            priority=priority if priority in {"Baixa", "Normal", "Alta"} else "Normal",
            status="Pendente",
        )
    )
    db.commit()
    return RedirectResponse("/?tab=dashboard", status_code=303)


@app.post("/tasks/{task_id}/done")
def complete_task(request: Request, task_id: int, db: Session = Depends(get_db)):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    task = db.scalar(select(CompanyTask).where(CompanyTask.company_id == company.id, CompanyTask.id == task_id))
    if task:
        task.status = "Concluida"
        db.commit()
    return RedirectResponse("/?tab=dashboard", status_code=303)


@app.post("/debts")
def create_debt(
    request: Request,
    debt_date: str = Form(""),
    due_date: str = Form(""),
    creditor: str = Form(...),
    creditor_type: str = Form("Banco"),
    description: str = Form(""),
    capital_value: float = Form(0),
    monthly_interest_rate: float = Form(0),
    interest_type: str = Form("Compostos"),
    installment_value: float = Form(0),
    due_day: int = Form(1),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    db.add(
        Debt(
            company_id=company.id,
            debt_date=parse_filter_date(debt_date),
            due_date=parse_filter_date(due_date),
            creditor=creditor.strip(),
            creditor_type=creditor_type,
            description=description.strip(),
            capital_value=capital_value,
            monthly_interest_rate=monthly_interest_rate,
            interest_type=interest_type,
            installment_value=installment_value,
            due_day=due_day,
            notes=notes.strip(),
        )
    )
    db.commit()
    return RedirectResponse("/?tab=endividamento", status_code=303)


@app.post("/debts/{debt_id}/update")
def update_debt(
    request: Request,
    debt_id: int,
    debt_date: str = Form(""),
    due_date: str = Form(""),
    creditor: str = Form(...),
    creditor_type: str = Form("Banco"),
    description: str = Form(""),
    capital_value: float = Form(0),
    monthly_interest_rate: float = Form(0),
    interest_type: str = Form("Compostos"),
    installment_value: float = Form(0),
    due_day: int = Form(1),
    status: str = Form("Ativo"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    debt = db.scalar(select(Debt).where(Debt.company_id == company.id, Debt.id == debt_id))
    if debt:
        debt.debt_date = parse_filter_date(debt_date)
        debt.due_date = parse_filter_date(due_date)
        debt.creditor = creditor.strip()
        debt.creditor_type = creditor_type
        debt.description = description.strip()
        debt.capital_value = capital_value
        debt.monthly_interest_rate = monthly_interest_rate
        debt.interest_type = interest_type
        debt.installment_value = installment_value
        debt.due_day = due_day
        debt.status = status
        debt.notes = notes.strip()
        db.commit()
    return RedirectResponse("/?tab=endividamento", status_code=303)


@app.post("/cashflow-plans")
def save_cashflow_plan(
    request: Request,
    month: str = Form(...),
    planned_inflows: float = Form(0),
    planned_outflows: float = Form(0),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    clean_month = month[:7]
    if len(clean_month) != 7:
        return RedirectResponse("/?tab=fluxo", status_code=303)
    plan = db.scalar(select(CashflowPlan).where(CashflowPlan.company_id == company.id, CashflowPlan.month == clean_month))
    if plan:
        plan.planned_inflows = planned_inflows
        plan.planned_outflows = planned_outflows
        plan.notes = notes.strip()
        plan.updated_at = datetime.utcnow()
    else:
        db.add(
            CashflowPlan(
                company_id=company.id,
                month=clean_month,
                planned_inflows=planned_inflows,
                planned_outflows=planned_outflows,
                notes=notes.strip(),
            )
        )
    db.commit()
    return RedirectResponse("/?tab=fluxo", status_code=303)


@app.post("/bank-reconciliations")
def save_bank_reconciliation(
    request: Request,
    month: str = Form(...),
    bank_account: str = Form(...),
    bank_other: str = Form(""),
    opening_balance: float = Form(0),
    closing_balance_informed: float = Form(0),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    bank = bank_other.strip() if bank_account == "Outro" and bank_other.strip() else bank_account.strip()
    if not bank:
        return RedirectResponse("/?tab=conciliacao", status_code=303)
    reconciliation = db.scalar(
        select(BankReconciliation).where(
            BankReconciliation.company_id == company.id,
            BankReconciliation.month == month,
            BankReconciliation.bank == bank,
        )
    )
    if not reconciliation:
        reconciliation = BankReconciliation(company_id=company.id, month=month, bank=bank)
        db.add(reconciliation)
    reconciliation.opening_balance = opening_balance
    reconciliation.closing_balance_informed = closing_balance_informed
    reconciliation.notes = notes.strip()
    reconciliation.updated_at = datetime.utcnow()
    db.commit()
    return RedirectResponse("/?tab=conciliacao", status_code=303)


@app.post("/transactions/bulk-classify")
def bulk_classify_transactions(
    request: Request,
    transaction_ids: list[int] = Form([]),
    account_id: int = Form(...),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    account = db.scalar(
        select(FinancialAccount).where(FinancialAccount.company_id == company.id, FinancialAccount.id == account_id)
    )
    if account and transaction_ids:
        rows = db.scalars(
            select(Transaction).where(Transaction.company_id == company.id, Transaction.id.in_(transaction_ids))
        ).all()
        for row in rows:
            create_full_transaction_split(db, company, row, account)
        db.commit()
    return RedirectResponse("/?tab=extratos", status_code=303)


@app.post("/anticipations")
def create_anticipation(
    request: Request,
    anticipation_date: str = Form(""),
    counterparty: str = Form(...),
    counterparty_type: str = Form("Empresa"),
    title_value: float = Form(0),
    advanced_value: float = Form(0),
    title_fee_rate: float = Form(0),
    interest_rate: float = Form(0),
    iof_value: float = Form(0),
    costs_value: float = Form(0),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    estimated_cost = anticipation_cost(title_value, title_fee_rate, interest_rate, iof_value, costs_value)
    db.add(
        Anticipation(
            company_id=company.id,
            anticipation_date=parse_filter_date(anticipation_date),
            counterparty=counterparty.strip(),
            counterparty_type=counterparty_type,
            title_value=title_value,
            advanced_value=advanced_value if advanced_value > 0 else max(title_value - estimated_cost, 0),
            title_fee_rate=title_fee_rate,
            interest_rate=interest_rate,
            iof_value=iof_value,
            costs_value=costs_value,
            notes=notes.strip(),
        )
    )
    db.commit()
    return RedirectResponse("/?tab=antecipacoes", status_code=303)


@app.post("/anticipations/{anticipation_id}/attachments")
async def upload_anticipation_attachment(
    request: Request,
    anticipation_id: int,
    file: UploadFile = File(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    anticipation = db.scalar(
        select(Anticipation).where(Anticipation.company_id == company.id, Anticipation.id == anticipation_id)
    )
    if not anticipation or not file.filename:
        return RedirectResponse("/?tab=antecipacoes", status_code=303)

    content = await file.read()
    if not content:
        return RedirectResponse("/?tab=antecipacoes", status_code=303)

    original_filename = safe_upload_filename(file.filename)
    stored_filename = f"{anticipation.id}_{int(datetime.utcnow().timestamp())}_{original_filename}"
    db.add(
        AnticipationAttachment(
            company_id=company.id,
            anticipation_id=anticipation.id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            content_type=file.content_type or "",
            file_data=content,
            notes=notes.strip(),
        )
    )
    db.commit()
    return RedirectResponse("/?tab=antecipacoes", status_code=303)


@app.get("/anticipations/attachments/{attachment_id}")
def download_anticipation_attachment(request: Request, attachment_id: int, db: Session = Depends(get_db)):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    attachment = db.scalar(
        select(AnticipationAttachment).where(
            AnticipationAttachment.company_id == company.id,
            AnticipationAttachment.id == attachment_id,
        )
    )
    if not attachment:
        return RedirectResponse("/?tab=antecipacoes", status_code=303)
    headers = {"Content-Disposition": f'attachment; filename="{attachment.original_filename}"'}
    return Response(content=attachment.file_data, media_type=attachment.content_type or "application/octet-stream", headers=headers)


@app.post("/fiscal/import-xml")
async def import_fiscal_xml(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    content = await file.read()
    status = "xml_ok"
    try:
        ElementTree.fromstring(content)
    except ElementTree.ParseError:
        status = "xml_erro"
    filename = file.filename or "arquivo.xml"
    return RedirectResponse(f"/?tab=fiscal&{status}=1&xml={filename}", status_code=303)


@app.post("/transactions/{transaction_id}/classify")
def classify_transaction(
    request: Request,
    transaction_id: int,
    account_id: int = Form(...),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    row = db.scalar(select(Transaction).where(Transaction.company_id == company.id, Transaction.id == transaction_id))
    account = db.scalar(
        select(FinancialAccount).where(FinancialAccount.company_id == company.id, FinancialAccount.id == account_id)
    )
    if row and account:
        create_full_transaction_split(db, company, row, account)
        db.commit()
    return RedirectResponse("/?tab=extratos", status_code=303)


@app.post("/transactions/{transaction_id}/split")
def split_transaction(
    request: Request,
    transaction_id: int,
    split_account_id: list[int] = Form([]),
    split_value: list[str] = Form([]),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    row = db.scalar(select(Transaction).where(Transaction.company_id == company.id, Transaction.id == transaction_id))
    if not row:
        return RedirectResponse("/?tab=extratos", status_code=303)

    valid_splits: list[tuple[FinancialAccount, float]] = []
    for account_id, value in zip(split_account_id, split_value):
        try:
            amount = float((value or "0").replace(",", "."))
        except ValueError:
            amount = 0
        if amount <= 0:
            continue
        account = db.scalar(
            select(FinancialAccount).where(FinancialAccount.company_id == company.id, FinancialAccount.id == account_id)
        )
        if account:
            valid_splits.append((account, amount))

    if valid_splits:
        reset_transaction_splits(db, row)
        row.account_id = valid_splits[0][0].id
        target_total = abs(row.entrada or row.saida or row.amount or 0)
        split_total = sum(value for _account, value in valid_splits)
        difference = target_total - split_total
        for account, amount in valid_splits:
            entrada, saida = transaction_direction_values(row, amount)
            db.add(
                TransactionSplit(
                    company_id=company.id,
                    transaction_id=row.id,
                    account_id=account.id,
                    entrada=entrada,
                    saida=saida,
                    notes="Rateio manual",
                )
            )
        if abs(difference) > 0.01:
            row.notes = f"{row.notes}\nRateio com diferenca de {format_brl(difference)}.".strip()
        db.commit()
    return RedirectResponse("/?tab=extratos", status_code=303)
