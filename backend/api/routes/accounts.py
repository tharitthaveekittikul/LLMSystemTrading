from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import decrypt, encrypt
from db.models import Account
from db.postgres import get_db

router = APIRouter()


# ── Request / Response schemas ────────────────────────────────────────────────

class AccountCreate(BaseModel):
    name: str
    broker: str
    login: int
    password: str
    server: str
    is_live: bool = False
    allowed_symbols: list[str] = []
    max_lot_size: float = 0.1


class AccountResponse(BaseModel):
    id: int
    name: str
    broker: str
    login: int
    server: str
    is_live: bool
    is_active: bool
    allowed_symbols: list[str]


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/", response_model=list[AccountResponse])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).where(Account.is_active == True))
    accounts = result.scalars().all()
    return [
        AccountResponse(
            id=a.id,
            name=a.name,
            broker=a.broker,
            login=a.login,
            server=a.server,
            is_live=a.is_live,
            is_active=a.is_active,
            allowed_symbols=_parse_symbols(a.allowed_symbols),
        )
        for a in accounts
    ]


@router.post("/", response_model=AccountResponse, status_code=201)
async def create_account(payload: AccountCreate, db: AsyncSession = Depends(get_db)):
    import json

    account = Account(
        name=payload.name,
        broker=payload.broker,
        login=payload.login,
        password_encrypted=encrypt(payload.password),
        server=payload.server,
        is_live=payload.is_live,
        allowed_symbols=json.dumps(payload.allowed_symbols),
        max_lot_size=payload.max_lot_size,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    return AccountResponse(
        id=account.id,
        name=account.name,
        broker=account.broker,
        login=account.login,
        server=account.server,
        is_live=account.is_live,
        is_active=account.is_active,
        allowed_symbols=payload.allowed_symbols,
    )


@router.delete("/{account_id}", status_code=204)
async def deactivate_account(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.is_active = False
    await db.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_symbols(raw: str) -> list[str]:
    import json

    try:
        return json.loads(raw) if raw else []
    except (ValueError, TypeError):
        return []
