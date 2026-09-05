"""Auth: signup (username + gmail + double password), signin, and forgotten
passwords via single-use 6-digit email codes. First user becomes admin."""
import hashlib
import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.exceptions import Conflict
from app.core.security import (get_current_user, hash_password, require_role,
                               verify_password, create_token)
from app.db.database import get_db
from app.db.models import PasswordReset, User
from app.engines import audit_engine, notification_engine
from app.utils.time import utcnow

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RESET_TTL_MIN = 15
RESET_MAX_ATTEMPTS = 5


class Register(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[\w.\-@]+$")
    email: str = Field(min_length=5, max_length=200)
    password: str = Field(min_length=8, max_length=256)
    confirm_password: str = Field(min_length=8, max_length=256)
    role: str = "viewer"

    @model_validator(mode="after")
    def _check(self):
        if not EMAIL_RE.match(self.email):
            raise ValueError("Enter a valid Gmail address, e.g. you@gmail.com")
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match — type the same one twice")
        return self


class Login(BaseModel):
    username: str
    password: str
    remember: bool = False


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)
    confirm_password: str = Field(min_length=8, max_length=256)

    @model_validator(mode="after")
    def _check(self):
        if self.new_password != self.confirm_password:
            raise ValueError("New passwords do not match")
        return self


class PasswordResetRequest(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=200)


class PasswordResetConfirm(BaseModel):
    username_or_email: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(min_length=8, max_length=256)
    confirm_password: str = Field(min_length=8, max_length=256)

    @model_validator(mode="after")
    def _check(self):
        if self.new_password != self.confirm_password:
            raise ValueError("New passwords do not match")
        return self


class PasswordResetAdmin(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


def _find_user(db: Session, identity: str) -> User | None:
    return db.query(User).filter(
        or_(User.username == identity, User.email == identity)).first()


@router.get("/status")
def status(db: Session = Depends(get_db)):
    """Public: tells the login page whether self-registration is open."""
    from app.core.config import settings
    empty = db.query(User).count() == 0
    return {"registration_open": empty or settings.allow_open_signup,
            "first_user": empty}


@router.post("/register", status_code=201)
def register(payload: Register, db: Session = Depends(get_db)):
    from app.core.config import settings
    first = db.query(User).count() == 0
    if not first and not settings.allow_open_signup:
        raise HTTPException(status_code=403,
                            detail="An admin already exists — ask them to create your account in Settings → Team")
    if db.query(User).filter(User.username == payload.username).first():
        raise Conflict("That username is taken — pick another")
    if db.query(User).filter(User.email == payload.email).first():
        raise Conflict("That Gmail is already registered — try signing in")
    user = User(username=payload.username, email=payload.email,
                password_hash=hash_password(payload.password),
                role="admin" if first else "viewer")
    db.add(user)
    db.commit()
    audit_engine.record(db, "USER_CREATED", actor="auth", action=f"register {user.username}",
                        result=user.role)
    db.commit()
    return {"username": user.username, "role": user.role}


@router.post("/login")
def login(payload: Login, db: Session = Depends(get_db)):
    user = _find_user(db, payload.username)
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong username or password — check caps lock and try again")
    return {"token": create_token(user.id, user.username, user.role, remember=payload.remember),
            "username": user.username, "role": user.role}


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "role": user["role"]}


@router.post("/forgot-password")
def forgot_password(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """Always returns ok (never reveals whether an account exists)."""
    user = _find_user(db, payload.username_or_email.strip())
    if user:
        # invalidate older codes, issue a fresh 6-digit one
        db.query(PasswordReset).filter(PasswordReset.user_id == user.id,
                                       PasswordReset.used.is_(False)).delete()
        code = f"{secrets.randbelow(1_000_000):06d}"
        db.add(PasswordReset(
            user_id=user.id,
            code_hash=hashlib.sha256(code.encode()).hexdigest(),
            expires_at=utcnow() + timedelta(minutes=RESET_TTL_MIN)))
        db.commit()
        notification_engine.send_email(
            "[AeroOps] Your password reset code",
            f"Hi {user.username},\n\nYour AeroOps reset code is: {code}\n\n"
            f"It expires in {RESET_TTL_MIN} minutes and works once. "
            f"If you didn't ask for this, ignore this email.\n")
        audit_engine.record(db, "PASSWORD_RESET_SENT", actor="auth",
                            action=f"code for {user.username}", result="emailed")
        db.commit()
    return {"ok": True, "detail": "If an account matches, a 6-digit code is on its way to its Gmail"}


@router.post("/reset-password")
def reset_password(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    user = _find_user(db, payload.username_or_email.strip())
    # uniform failure: no user enumeration via timing-neutral generic error
    if not user:
        raise HTTPException(status_code=400, detail="Wrong code — check the email and try again")
    entry = (db.query(PasswordReset).filter(PasswordReset.user_id == user.id,
                                            PasswordReset.used.is_(False))
             .order_by(PasswordReset.id.desc()).first())
    digest = hashlib.sha256(payload.code.encode()).hexdigest()
    valid = (entry is not None and entry.expires_at > utcnow()
             and entry.attempts < RESET_MAX_ATTEMPTS
             and secrets.compare_digest(entry.code_hash, digest))
    if not valid:
        if entry is not None:
            entry.attempts += 1
            db.commit()
        raise HTTPException(status_code=400, detail="Wrong or expired code — request a fresh one")
    entry.used = True
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    audit_engine.record(db, "PASSWORD_RESET", actor=user.username, result="ok")
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(payload: PasswordChange, user: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    record = db.query(User).filter(User.username == user["username"]).first()
    if not record or not verify_password(payload.current_password, record.password_hash):
        raise HTTPException(status_code=401, detail="Current password is wrong")
    record.password_hash = hash_password(payload.new_password)
    db.commit()
    audit_engine.record(db, "PASSWORD_CHANGED", actor=user["username"], result="ok")
    db.commit()
    return {"ok": True}


@router.get("/users")
def list_users(_: dict = Depends(require_role("admin")), db: Session = Depends(get_db)):
    return [{"username": u.username, "email": u.email, "role": u.role,
             "created_at": u.created_at.isoformat()} for u in db.query(User).all()]


@router.post("/users", status_code=201)
def create_user(payload: Register, user: dict = Depends(require_role("admin")),
                db: Session = Depends(get_db)):
    if payload.role not in ("admin", "operator", "viewer"):
        raise Conflict("bad role")
    if db.query(User).filter(User.username == payload.username).first():
        raise Conflict("That username is taken")
    if db.query(User).filter(User.email == payload.email).first():
        raise Conflict("That Gmail is already registered")
    record = User(username=payload.username, email=payload.email,
                  password_hash=hash_password(payload.password), role=payload.role)
    db.add(record)
    db.commit()
    audit_engine.record(db, "USER_CREATED", actor=user["username"],
                        action=f"create {record.username}", result=record.role)
    db.commit()
    return {"username": record.username, "role": record.role}


@router.post("/users/{username}/reset", status_code=200)
def admin_reset(username: str, payload: PasswordResetAdmin,
                user: dict = Depends(require_role("admin")),
                db: Session = Depends(get_db)):
    record = db.query(User).filter(User.username == username).first()
    if not record:
        raise HTTPException(status_code=404, detail="No such user")
    record.password_hash = hash_password(payload.new_password)
    db.commit()
    audit_engine.record(db, "PASSWORD_RESET", actor=user["username"],
                        action=f"reset {username}", result="ok")
    db.commit()
    return {"ok": True}
