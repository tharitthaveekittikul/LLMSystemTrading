"""Account CRUD: list, create, get, update, deactivate."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.accounts._helpers import _to_response
from api.routes.accounts._schemas import AccountCreate, AccountResponse, AccountUpdate
from core.security import encrypt
from db.models import Account
from db.postgres import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("", response_model=list[AccountResponse])
async def list_accounts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Account).where(Account.is_active))
    accounts = result.scalars().all()
    return [_to_response(a) for a in accounts]


@router.post("", response_model=AccountResponse, status_code=201)
async def create_account(payload: AccountCreate, db: AsyncSession = Depends(get_db)):
    logger.info("Creating account | broker=%s login=%s is_live=%s", payload.broker, payload.login, payload.is_live)
    account = Account(
        name=payload.name,
        broker=payload.broker,
        login=payload.login,
        password_encrypted=encrypt(payload.password),
        server=payload.server,
        is_live=payload.is_live,
        allowed_symbols=json.dumps(payload.allowed_symbols),
        max_lot_size=payload.max_lot_size,
        risk_pct=payload.risk_pct,
        auto_trade_enabled=payload.auto_trade_enabled,
        mt5_path=payload.mt5_path,
        account_type=payload.account_type,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    logger.info("Account created | id=%s broker=%s login=%s", account.id, account.broker, account.login)
    return _to_response(account)


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")
    return _to_response(account)


@router.patch("/{account_id}", response_model=AccountResponse)
async def update_account(account_id: int, payload: AccountUpdate, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=404, detail="Account not found")

    if payload.name is not None:
        account.name = payload.name
    if payload.broker is not None:
        account.broker = payload.broker
    if payload.server is not None:
        account.server = payload.server
    if payload.is_live is not None:
        account.is_live = payload.is_live
    if payload.max_lot_size is not None:
        account.max_lot_size = payload.max_lot_size
    if payload.risk_pct is not None:
        account.risk_pct = payload.risk_pct
    if payload.auto_trade_enabled is not None:
        account.auto_trade_enabled = payload.auto_trade_enabled
    if payload.password is not None:
        account.password_encrypted = encrypt(payload.password)
    if payload.mt5_path is not None:
        account.mt5_path = payload.mt5_path
    if payload.account_type is not None:
        account.account_type = payload.account_type

    await db.commit()
    await db.refresh(account)
    logger.info("Account updated | id=%s", account_id)
    return _to_response(account)


@router.delete("/{account_id}", status_code=204)
async def deactivate_account(account_id: int, db: AsyncSession = Depends(get_db)):
    account = await db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.is_active = False
    await db.commit()
    logger.info("Account deactivated | id=%s", account_id)


