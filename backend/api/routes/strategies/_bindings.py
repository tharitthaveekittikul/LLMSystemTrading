"""Account <-> strategy binding management: bind, toggle, unbind, list."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.routes.strategies._crud import BindingResponse, BindRequest, _get_or_404
from db.models import Account, AccountStrategy
from db.postgres import get_db
from services.scheduler import add_binding_jobs, remove_binding_jobs

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/{strategy_id}/bind",
    response_model=BindingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bind_account(
    strategy_id: int, body: BindRequest, db: AsyncSession = Depends(get_db)
):
    strategy = await _get_or_404(db, strategy_id)
    account = await db.get(Account, body.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    binding = AccountStrategy(
        account_id=body.account_id,
        strategy_id=strategy_id,
        is_active=body.is_active,
    )
    db.add(binding)
    try:
        await db.commit()
        await db.refresh(binding)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Account already bound to this strategy")
    if binding.is_active and account.is_active and strategy.is_active:
        binding.strategy = strategy
        binding.account = account
        add_binding_jobs(binding)
    logger.info(
        "Binding created | id=%s account_id=%s strategy_id=%s is_active=%s",
        binding.id, binding.account_id, binding.strategy_id, binding.is_active,
    )
    return BindingResponse(
        id=binding.id,
        account_id=binding.account_id,
        strategy_id=binding.strategy_id,
        is_active=binding.is_active,
        account_name=account.name,
        login=account.login,
        is_live=account.is_live,
    )


@router.patch("/{strategy_id}/bind/{account_id}", response_model=BindingResponse)
async def toggle_binding(
    strategy_id: int,
    account_id: int,
    body: BindRequest,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AccountStrategy)
        .where(
            AccountStrategy.strategy_id == strategy_id,
            AccountStrategy.account_id == account_id,
        )
        .options(
            selectinload(AccountStrategy.strategy),
            selectinload(AccountStrategy.account),
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")
    old_active = binding.is_active
    binding.is_active = body.is_active
    await db.commit()
    await db.refresh(binding)
    symbols = json.loads(binding.strategy.symbols or "[]")
    if not old_active and body.is_active:
        if binding.account.is_active and binding.strategy.is_active:
            add_binding_jobs(binding)
    elif old_active and not body.is_active:
        remove_binding_jobs(binding.id, binding.account_id, binding.strategy_id, symbols)
    logger.info(
        "Binding toggled | id=%s account_id=%s strategy_id=%s is_active=%s",
        binding.id, account_id, strategy_id, binding.is_active,
    )
    return BindingResponse(
        id=binding.id,
        account_id=binding.account_id,
        strategy_id=binding.strategy_id,
        is_active=binding.is_active,
        account_name=binding.account.name,
        login=binding.account.login,
        is_live=binding.account.is_live,
    )


@router.delete(
    "/{strategy_id}/bind/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unbind_account(
    strategy_id: int, account_id: int, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(AccountStrategy)
        .where(
            AccountStrategy.strategy_id == strategy_id,
            AccountStrategy.account_id == account_id,
        )
        .options(selectinload(AccountStrategy.strategy))
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise HTTPException(status_code=404, detail="Binding not found")
    symbols = json.loads(binding.strategy.symbols or "[]")
    remove_binding_jobs(binding.id, account_id, strategy_id, symbols)
    await db.delete(binding)
    await db.commit()
    logger.info(
        "Binding removed | account_id=%s strategy_id=%s", account_id, strategy_id
    )


@router.get("/{strategy_id}/bindings", response_model=list[BindingResponse])
async def list_bindings(strategy_id: int, db: AsyncSession = Depends(get_db)):
    await _get_or_404(db, strategy_id)
    result = await db.execute(
        select(AccountStrategy)
        .where(AccountStrategy.strategy_id == strategy_id)
        .options(selectinload(AccountStrategy.account))
    )
    bindings = result.scalars().all()
    return [
        BindingResponse(
            id=b.id,
            account_id=b.account_id,
            strategy_id=b.strategy_id,
            is_active=b.is_active,
            account_name=b.account.name,
            login=b.account.login,
            is_live=b.account.is_live,
        )
        for b in bindings
    ]


