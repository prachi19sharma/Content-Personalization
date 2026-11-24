"""Brand (workspace) routes.

A brand is one client's shared answers inside a domain. An account may hold
many and works in one at a time; every agent then holds a separate
configuration per brand, so the same agent serves any brand without the user
overwriting the previous one.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.agents.definitions import PRIMARY_DOMAIN
from app.api.deps import CurrentUser, DbSession
from app.schemas.brand import BrandCreate, BrandList, BrandRead, BrandRename
from app.services.profile_service import get_profile_service

router = APIRouter(prefix="/brands", tags=["brands"])


def _read(brand) -> BrandRead:
    return BrandRead(
        id=brand.id,
        domain=brand.domain,
        label=brand.label,
        is_active=brand.is_active,
        is_configured=brand.is_configured,
        profile_data=brand.profile_data or {},
        revision=brand.revision,
        created_at=brand.created_at,
        updated_at=brand.updated_at,
    )


@router.get("", response_model=BrandList)
def list_brands(user: CurrentUser, db: DbSession, domain: str = PRIMARY_DOMAIN) -> BrandList:
    service = get_profile_service()
    brands = service.list_brands(db, user.id, domain)
    active = service.active_brand(db, user.id, domain)
    return BrandList(
        brands=[_read(b) for b in brands],
        active_id=active.id if active else None,
    )


@router.post("", response_model=BrandRead, status_code=status.HTTP_201_CREATED)
def create_brand(payload: BrandCreate, user: CurrentUser, db: DbSession) -> BrandRead:
    """Create a brand and switch to it.

    A new brand starts unconfigured on purpose: the user is then walked through
    the brand step and each agent's own questions, which is the enrollment flow
    they would otherwise have had to fake by overwriting an existing brand.
    """
    brand = get_profile_service().create_brand(
        db,
        user.id,
        payload.domain or PRIMARY_DOMAIN,
        label=payload.label,
        profile_data=payload.profile_data,
        activate=True,
    )
    return _read(brand)


@router.post("/{brand_id}/activate", response_model=BrandRead)
def activate_brand(brand_id: uuid.UUID, user: CurrentUser, db: DbSession) -> BrandRead:
    brand = get_profile_service().activate_brand(db, user.id, brand_id)
    if brand is None:
        # 404 rather than 403: another account's brand should not be
        # distinguishable from one that does not exist.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such brand.")
    return _read(brand)


@router.patch("/{brand_id}", response_model=BrandRead)
def rename_brand(
    brand_id: uuid.UUID, payload: BrandRename, user: CurrentUser, db: DbSession
) -> BrandRead:
    brand = get_profile_service().rename_brand(db, user.id, brand_id, payload.label)
    if brand is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such brand.")
    return _read(brand)


@router.delete("/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_brand(brand_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    try:
        removed = get_profile_service().delete_brand(db, user.id, brand_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such brand.")
