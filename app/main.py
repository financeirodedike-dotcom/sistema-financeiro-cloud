import hashlib
from datetime import date

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE, create_session_token, current_company, current_user, hash_password, verify_password
from app.classifier import classify_account
from app.database import get_db, init_db
from app.models import ClassificationRule, Company, Debt, FinancialAccount, ImportBatch, Membership, Transaction, User
from app.ofx_parser import parse_ofx
from app.reports import balance_sheet, dashboard, dashboard_charts, debt_evolution, dre, monthly_cashflow, purchases


app = FastAPI(title="Business360 AI")
templates = Jinja2Templates(directory="app/templates")


DEFAULT_ACCOUNTS = [
    ("A classificar", "Outras", "Outras Receitas/Despesas", "Operacional"),
    ("Venda a vista", "Receitas", "Receita Bruta", "Operacional"),
    ("Venda a prazo antecipadas", "Receitas", "Receita Bruta", "Operacional"),
    ("Materia prima", "Custos e Compras", "Custos e Compras", "Operacional"),
    ("Material de consumo", "Custos e Compras", "Custos e Compras", "Operacional"),
    ("Frete compras", "Custos e Compras", "Custos e Compras", "Operacional"),
    ("SALARIO", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("Aluguel do imovel", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("Energia eletrica", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("Combustiveis", "Operacional", "Despesas Operacionais", "Operacional"),
    ("Pedagio", "Operacional", "Despesas Operacionais", "Operacional"),
    ("Tarifas Bancarias", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("Juros por atraso", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("Transferencia entre contas", "Transferencias", "Transferencias", "Transferencia"),
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
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def debt_overdue_days(debt: Debt) -> int:
    if not debt.due_date or debt.status != "Ativo":
        return 0
    return max((date.today() - debt.due_date).days, 0)


def seed_company_accounts(db: Session, company: Company) -> None:
    existing = db.scalar(select(FinancialAccount).where(FinancialAccount.company_id == company.id).limit(1))
    if existing:
        return
    for name, group, dre_line, cashflow in DEFAULT_ACCOUNTS:
        db.add(
            FinancialAccount(
                company_id=company.id,
                name=name,
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


@app.get("/", response_class=HTMLResponse)
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
    date_from = parse_filter_date(date_from_raw)
    date_to = parse_filter_date(date_to_raw)
    transaction_query = select(Transaction).where(Transaction.company_id == company.id)
    if date_from:
        transaction_query = transaction_query.where(Transaction.date >= date_from)
    if date_to:
        transaction_query = transaction_query.where(Transaction.date <= date_to)
    if bank_filter:
        transaction_query = transaction_query.where(Transaction.bank == bank_filter)
    transactions = db.scalars(transaction_query.order_by(Transaction.date.desc()).limit(500)).all()
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
    active_users = sum(1 for membership in user_memberships if membership.user.is_active)
    current_user_membership = current_membership(user, company, db)
    debts = db.scalars(select(Debt).where(Debt.company_id == company.id).order_by(Debt.created_at.desc())).all()
    debt_rows = [{"debt": debt, "overdue_days": debt_overdue_days(debt)} for debt in debts]
    purchases_report = purchases(db, company.id)
    report_debt_id = request.query_params.get("debt_report")
    report_months_raw = request.query_params.get("debt_months", "12")
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
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user,
            "company": company,
            "accounts": accounts,
            "rules": rules,
            "transactions": transactions,
            "imports": imports,
            "user_memberships": user_memberships,
            "access_summary": {
                "total": len(user_memberships),
                "active": active_users,
                "inactive": len(user_memberships) - active_users,
                "admins": sum(1 for membership in user_memberships if membership.role in {"owner", "admin"}),
            },
            "current_membership": current_user_membership,
            "can_manage_access": can_manage_access(current_user_membership),
            "debts": debts,
            "debt_rows": debt_rows,
            "debt_report": debt_evolution(selected_debt, report_months),
            "debt_report_months": report_months,
            "bank_sources": BANK_SOURCES,
            "bank_options": bank_options,
            "filters": {
                "date_from": date_from_raw,
                "date_to": date_to_raw,
                "bank": bank_filter,
            },
            "active_tab": request.query_params.get("tab", "dashboard"),
            "dashboard": dashboard(db, company.id),
            "cashflow": monthly_cashflow(db, company.id),
            "dre": dre(db, company.id),
            "balance": balance_sheet(db, company.id),
            "purchases": purchases_report,
            "charts": dashboard_charts(db, company.id),
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
    source = bank_other.strip() if bank_account == "Outro" and bank_other.strip() else bank_account.strip()
    batch = ImportBatch(company_id=company.id, filename=file.filename or "arquivo.ofx")
    db.add(batch)
    db.flush()
    imported = 0
    skipped = 0
    for item in parsed:
        exists = None
        if item.get("fitid"):
            exists = db.scalar(
                select(Transaction).where(
                    Transaction.company_id == company.id,
                    Transaction.fitid == item["fitid"],
                    Transaction.amount == item["amount"],
                    Transaction.date == item["date"],
                )
            )
        if exists:
            skipped += 1
            continue
        if source:
            item["bank"] = source
        account = classify_account(db, company.id, item["history"])
        db.add(Transaction(**item, company_id=company.id, import_batch_id=batch.id, account=account))
        imported += 1
    batch.imported_count = imported
    batch.skipped_count = skipped
    db.commit()
    return RedirectResponse(f"/?tab=extratos&imported={imported}&skipped={skipped}", status_code=303)


@app.post("/transactions/manual")
def create_manual_transaction(
    request: Request,
    transaction_date: date = Form(...),
    history: str = Form(...),
    amount: float = Form(...),
    bank_account: str = Form("Caixa Interno"),
    bank_other: str = Form(""),
    account_id: int | None = Form(None),
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
    fingerprint = f"{company.id}|{transaction_date.isoformat()}|{history.strip()}|{amount}|{source}"
    db.add(
        Transaction(
            company_id=company.id,
            date=transaction_date,
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
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    existing = db.scalar(
        select(FinancialAccount).where(FinancialAccount.company_id == company.id, FinancialAccount.name == name.strip())
    )
    if existing:
        existing.group_name = group_name
        existing.dre_line = dre_line
        existing.cashflow_class = cashflow_class
    else:
        db.add(
            FinancialAccount(
                company_id=company.id,
                name=name.strip(),
                group_name=group_name,
                dre_line=dre_line,
                cashflow_class=cashflow_class,
            )
        )
    db.commit()
    return RedirectResponse("/", status_code=303)


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
    return RedirectResponse("/", status_code=303)


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
    return RedirectResponse("/#endividamento", status_code=303)


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
    return RedirectResponse("/#endividamento", status_code=303)


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
        row.account_id = account.id
        db.commit()
    return RedirectResponse("/?tab=extratos", status_code=303)
