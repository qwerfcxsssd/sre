import structlog
from fastapi import APIRouter

from app.chaos import ChaosState
from app.deps import ChaosDep
from app.schemas import ChaosOut, ChaosPatch

router = APIRouter(prefix="/admin", tags=["chaos"])
log = structlog.get_logger(__name__)


def _render(state: ChaosState, leaked_mb: int) -> ChaosOut:
    return ChaosOut(**state.as_dict(), leaked_mb=leaked_mb)


@router.get("/chaos", response_model=ChaosOut)
async def get_chaos_state(controller: ChaosDep) -> ChaosOut:
    return _render(controller.state, controller.leaked_mb())


@router.post("/chaos", response_model=ChaosOut)
async def set_chaos_state(patch: ChaosPatch, controller: ChaosDep) -> ChaosOut:
    changes = patch.model_dump(exclude_none=True)
    state = controller.apply(changes)
    log.warning("chaos.applied", **changes)
    return _render(state, controller.leaked_mb())


@router.delete("/chaos", response_model=ChaosOut)
async def reset_chaos_state(controller: ChaosDep) -> ChaosOut:
    state = controller.reset()
    log.warning("chaos.reset")
    return _render(state, controller.leaked_mb())
