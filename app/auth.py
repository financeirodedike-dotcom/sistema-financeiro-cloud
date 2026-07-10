import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Membership, User


SESSION_COOKIE = "financeiro_session"
SECRET_KEY = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao")
PBKDF2_ITERATIONS = 210_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_session_token(user_id: int) -> str:
    payload = f"{user_id}:{int(datetime.utcnow().timestamp())}"
    signature = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode("utf-8")).decode("ascii")


def read_session_token(token: str | None) -> int | None:
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        user_id, created_at, signature = raw.rsplit(":", 2)
        payload = f"{user_id}:{created_at}"
        expected = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        return int(user_id)
    except (ValueError, TypeError):
        return None


def current_user(request: Request, db: Session) -> User | None:
    user_id = read_session_token(request.cookies.get(SESSION_COOKIE))
    if not user_id:
        return None
    return db.get(User, user_id)


def current_company(user: User, db: Session) -> Company | None:
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.id))
    return membership.company if membership else None

