"""Time-Travel Rewind Router (Section 8.6 & Section 16).

Endpoint for branching and re-executing causal agent spans.

Owner: Abhishek (formerly Rushikesh)
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import RewindRequest, RewindResponse
from app.services.rewind_engine import execute_rewind

logger = logging.getLogger("fathom.routers.rewind")

router = APIRouter(prefix="/api/v1/runs", tags=["Time-Travel Rewind"])


@router.post(
    "/{run_id}/rewind",
    response_model=RewindResponse,
    status_code=status.HTTP_200_OK,
    summary="Rewind a span and re-execute downstream branches",
)
async def rewind_run_span(
    run_id: UUID,
    payload: RewindRequest,
    db: AsyncSession = Depends(get_db),
):
    """Trigger time-travel rewind on an agent span.

    - Validates target span belongs to the run.
    - Validates run is finished (rejects running executions with HTTP 409).
    - Preserves all original history untouched (never deletes or overwrites).
    - Branches a new causal execution group (`rewind_group_id`).
    - Re-executes eligible downstream steps while gating non-idempotent tool calls.
    - Auto-evaluates new spans through the 3-phase evaluation pipeline.
    """
    if not isinstance(payload.mutated_input, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="mutated_input must be a valid JSON dictionary",
        )

    try:
        response = await execute_rewind(run_id=run_id, request=payload, db=db)
        return response
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        if "in progress" in msg.lower() or "running" in msg.lower():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
        if "does not belong" in msg.lower():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
    except Exception as e:
        logger.exception("Unexpected error during rewind: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Rewind failed: {e}",
        )
