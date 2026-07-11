import hashlib
from datetime import date
from xml.etree import ElementTree

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE, create_session_token, current_company, current_user, hash_password, verify_password
from app.classifier import classify_account
from app.database import get_db, init_db
from app.models import Anticipation, ClassificationRule, Company, Debt, FinancialAccount, ImportBatch, Membership, Transaction, User
from app.ofx_parser import parse_ofx
from app.reports import balance_sheet, dashboard, dashboard_charts, debt_evolution, dre, monthly_cashflow, purchases


app = FastAPI(title="Business360 AI")
templates = Jinja2Templates(directory="app/templates")


def format_brl(value: float | int | None) -> str:
    amount = float(value or 0)
    formatted = f"{abs(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if amount < 0:
        return f"-R$ {formatted}"
    return f"R$ {formatted}"


templates.env.filters["brl"] = format_brl


DEFAULT_ACCOUNTS = [
    ("A classificar", "Outras", "Outras Receitas/Despesas", "Operacional"),
    ("VENDA A VISTA", "Receitas", "Receita Bruta", "Operacional"),
    ("VENDA A PRAZO ANTECIPADAS", "Receitas", "Receita Bruta", "Operacional"),
    ("VENDAS REFORMA", "Receitas", "Receita Bruta", "Operacional"),
    ("VENDA DE SERVIÇO", "Receitas", "Receita Bruta", "Operacional"),
    ("VENDA DE SUCATA", "Receitas", "Receita Bruta", "Operacional"),
    ("VENDA IMOBILIZADO", "Receitas", "Outras Receitas", "Investimento"),
    ("MATÉRIA PRIMA", "Custos e Compras", "Custos e Compras", "Operacional"),
    ("MATERIAL DE CONSUMO", "Custos e Compras", "Custos e Compras", "Operacional"),
    ("ALUGUEL DO IMÓVEL", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("ENERGIA ELETRICA", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("AGUA", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("TELEFONIA MOVEL", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("INTERNET", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("LOCAÇÃO DE SOFTWAE", "Despesas Fixas", "Despesas Fixas", "Operacional"),
    ("HONORARIOS ADVOCATÍCIOS", "Serviços", "Despesas Operacionais", "Operacional"),
    ("HONORÁRIOS CONTÁBEIS", "Serviços", "Despesas Operacionais", "Operacional"),
    ("COMBUSTIVEIS", "Operacional", "Despesas Operacionais", "Operacional"),
    ("PEDÁGIO", "Operacional", "Despesas Operacionais", "Operacional"),
    ("MANUTENÇÃO DE VEICULOS", "Operacional", "Despesas Operacionais", "Operacional"),
    ("SEGUROS DE VEÍCULOS", "Operacional", "Despesas Operacionais", "Operacional"),
    ("IPVA", "Operacional", "Despesas Operacionais", "Operacional"),
    ("LICENCIAMENTO ANUAL", "Operacional", "Despesas Operacionais", "Operacional"),
    ("FINANCIAMENTO STRADA", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("MATÉRIAL DE ESCRITÓRIO", "Administrativo", "Despesas Operacionais", "Operacional"),
    ("MATÉRIAL DE LIMPEZA", "Administrativo", "Despesas Operacionais", "Operacional"),
    ("DIARISTA / LIMPEZA", "Administrativo", "Despesas Operacionais", "Operacional"),
    ("ALIMENTAÇÃO/ MERCADO", "Administrativo", "Despesas Operacionais", "Operacional"),
    ("FRETE COMPRAS", "Custos e Compras", "Custos e Compras", "Operacional"),
    ("MANUTENÇÃO EMPRESA", "Manutenção", "Despesas Operacionais", "Operacional"),
    ("MANUTENÇÃO MAQUINAS E EQUIPAMENTOS", "Manutenção", "Despesas Operacionais", "Operacional"),
    ("MOVEIS E UTENSILIOS", "Investimentos", "Investimentos", "Investimento"),
    ("ESTACIONAMENTO", "Operacional", "Despesas Operacionais", "Operacional"),
    ("SERASA", "Administrativo", "Despesas Operacionais", "Operacional"),
    ("HOSPEDAGEM SITE", "Marketing", "Despesas Operacionais", "Operacional"),
    ("CERTIFICADO DIGITAL", "Fiscal", "Despesas Operacionais", "Operacional"),
    ("ROSELI FAUSTIN", "Outras", "Outras Receitas/Despesas", "Operacional"),
    ("FERRAMENTAS", "Investimentos", "Investimentos", "Investimento"),
    ("EQUIPAMENTOS DE T.I.", "Investimentos", "Investimentos", "Investimento"),
    ("MARKETING", "Marketing", "Despesas Comerciais", "Operacional"),
    ("COMISSAO", "Comercial", "Despesas Comerciais", "Operacional"),
    ("FRETE VENDAS", "Comercial", "Despesas Comerciais", "Operacional"),
    ("SIMPLES NACIONAL DAS", "Fiscal", "Impostos", "Operacional"),
    ("SERVIÇOS TERCEIRIZADOS", "Serviços", "Despesas Operacionais", "Operacional"),
    ("SALARIO", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA AJUDA DE CUSTO", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA VALE COMPRA/TRANSPORTE", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("HORAS EXTRAS", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("13 SALARIO", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("FÉRIAS FUNCIONÁRIOS", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA RESCISÃO", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA MULTA RECISÃO 40% FGTS", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA ASSISTÊNCIA MÉDICA / PLANO DE SAÚDE", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("FARMÁCIA", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("INSS", "Pessoal", "Encargos sobre Folha", "Operacional"),
    ("FGTS", "Pessoal", "Encargos sobre Folha", "Operacional"),
    ("DESPESA IRRF SALÁRIOS", "Pessoal", "Encargos sobre Folha", "Operacional"),
    ("DESPESA UNIFORMES", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA MEDICINA OCUPACIONAL", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("EPI", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA BONUS PONTUALIDADE", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DESPESA ENDOMARKETING", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("DEPOSITO JUDICIAL TRABALHISTA", "Pessoal", "Despesas com Pessoal", "Operacional"),
    ("CLARA JAILMA M T COSTA", "Sócios", "Distribuições/Sócios", "Financiamento"),
    ("ANDRÉ LUIS DA COSTA", "Sócios", "Distribuições/Sócios", "Financiamento"),
    ("ALTAMIR DA COSTA", "Sócios", "Distribuições/Sócios", "Financiamento"),
    ("RODRIGO JOSÉ DA COSTA", "Sócios", "Distribuições/Sócios", "Financiamento"),
    ("LUIZ HENRIQUE DA COSTA", "Sócios", "Distribuições/Sócios", "Financiamento"),
    ("TARIFAS BANCÁRIAS", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("BORDÊRO", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("JUROS ANTECIPAÇÕES DE TITULOS", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("JUROS POR ATRASO", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("JUROS LIMITE", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("JUROS EMPRÉSTIMOS", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("TAXA CARTÃO CRÉDITO/DÉBITO", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("IOF", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("ROTATIVO CRESOL", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("TARIFA FLAT BB", "Financeiro", "Resultado Financeiro", "Financiamento"),
    ("TRANSFERENCIA ENTRE CONTAS", "Transferencias", "Transferencias", "Transferencia"),
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


def normalize_account_name(name: str) -> str:
    return " ".join(name.strip().upper().split())


def seed_company_accounts(db: Session, company: Company) -> None:
    existing_accounts = db.scalars(
        select(FinancialAccount).where(FinancialAccount.company_id == company.id).order_by(FinancialAccount.id)
    ).all()
    by_name = {}
    duplicates_found = False
    for account in existing_accounts:
        normalized = normalize_account_name(account.name)
        if normalized in by_name:
            keeper = by_name[normalized]
            for transaction in db.scalars(
                select(Transaction).where(Transaction.company_id == company.id, Transaction.account_id == account.id)
            ).all():
                transaction.account_id = keeper.id
            account.name = f"REMOVER DUPLICADA {account.id}"
            db.delete(account)
            duplicates_found = True
            continue
        by_name[normalized] = account
    if duplicates_found:
        db.flush()
    for normalized, account in by_name.items():
        account.name = normalized
    for name, group, dre_line, cashflow in DEFAULT_ACCOUNTS:
        normalized = normalize_account_name(name)
        if normalized in by_name:
            account = by_name[normalized]
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
    history_filter = request.query_params.get("history", "").strip()
    sort_order = request.query_params.get("sort", "desc")
    date_from = parse_filter_date(date_from_raw)
    date_to = parse_filter_date(date_to_raw)
    transaction_query = select(Transaction).where(Transaction.company_id == company.id)
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
    transactions = db.scalars(transaction_query.limit(500)).all()
    classified_count = sum(1 for row in transactions if row.account and row.account.name.upper() != "A CLASSIFICAR")
    pending_count = len(transactions) - classified_count
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
    anticipations = db.scalars(
        select(Anticipation).where(Anticipation.company_id == company.id).order_by(Anticipation.created_at.desc())
    ).all()
    anticipation_total_titles = sum(row.title_value for row in anticipations)
    anticipation_total_cost = sum(
        (row.title_value * (row.title_fee_rate / 100)) + (row.title_value * (row.interest_rate / 100)) + row.iof_value + row.costs_value
        for row in anticipations
    )
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
    cashflow_report = monthly_cashflow(db, company.id)
    cashflow_totals = {
        "entradas": sum(row["entradas"] for row in cashflow_report),
        "saidas": sum(row["saidas"] for row in cashflow_report),
        "saldo_periodo": sum(row["saldo_mes"] for row in cashflow_report),
        "saldo_acumulado": cashflow_report[-1]["saldo_acumulado"] if cashflow_report else 0,
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
            "classified_count": classified_count,
            "pending_count": pending_count,
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
            "anticipations": anticipations,
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
            },
            "active_tab": request.query_params.get("tab", "dashboard"),
            "dashboard": dashboard(db, company.id),
            "cashflow": cashflow_report,
            "cashflow_totals": cashflow_totals,
            "cashflow_explanation": cashflow_explanation,
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
    return_tab: str = Form("classificacao"),
    db: Session = Depends(get_db),
):
    context = require_context(request, db)
    if isinstance(context, RedirectResponse):
        return context
    _user, company = context
    clean_name = normalize_account_name(name)
    existing = db.scalar(select(FinancialAccount).where(FinancialAccount.company_id == company.id, FinancialAccount.name == clean_name))
    if existing:
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
    return RedirectResponse("/?tab=classificacao", status_code=303)


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
            row.account_id = account.id
        db.commit()
    return RedirectResponse("/?tab=extratos", status_code=303)


@app.post("/anticipations")
def create_anticipation(
    request: Request,
    anticipation_date: str = Form(""),
    counterparty: str = Form(...),
    counterparty_type: str = Form("Empresa"),
    title_value: float = Form(0),
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
    db.add(
        Anticipation(
            company_id=company.id,
            anticipation_date=parse_filter_date(anticipation_date),
            counterparty=counterparty.strip(),
            counterparty_type=counterparty_type,
            title_value=title_value,
            title_fee_rate=title_fee_rate,
            interest_rate=interest_rate,
            iof_value=iof_value,
            costs_value=costs_value,
            notes=notes.strip(),
        )
    )
    db.commit()
    return RedirectResponse("/?tab=antecipacoes", status_code=303)


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
        row.account_id = account.id
        db.commit()
    return RedirectResponse("/?tab=extratos", status_code=303)
