"""Temporary shared-password login endpoint for early development access."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.access_security import (
    SHARED_PASSWORD_MIN_LENGTH,
    AccessConfigurationError,
    issue_access_token,
    verify_configured_password,
)

router = APIRouter(prefix="/api/access", tags=["access"])


class DevelopmentAccessLoginRequest(BaseModel):
    password: str = Field(min_length=SHARED_PASSWORD_MIN_LENGTH, max_length=1024)


class DevelopmentAccessLoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


@router.post("/login", response_model=DevelopmentAccessLoginResponse)
async def login(
    payload: DevelopmentAccessLoginRequest,
) -> DevelopmentAccessLoginResponse:
    """Exchange the shared development password for a short-lived Bearer token."""
    try:
        password_matches = verify_configured_password(payload.password)
    except AccessConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application access is not configured",
        ) from exc

    if not password_matches:
        # Add a small bounded delay to make rapid online guessing less attractive
        # without introducing persistent rate-limit state at this development stage.
        await asyncio.sleep(0.2)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        access_token, expires_in = issue_access_token()
    except AccessConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application access is not configured",
        ) from exc

    return DevelopmentAccessLoginResponse(
        access_token=access_token,
        expires_in=expires_in,
    )
