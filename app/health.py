"""Liveness check.

Not module-specific, so it's its own small app-level router - owned by
``app`` itself - rather than living inside a business module. Mounted the
same way as every module router: ``app.include_router(...)`` in
``app/main.py``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response body for ``GET /health``."""

    status: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness check."""
    # debug, not info: this gets polled frequently (load balancers,
    # docker healthchecks) and would drown out everything else at INFO.
    logger.debug("Health check OK")
    return HealthResponse(status="ok")
