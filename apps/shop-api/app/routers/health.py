from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.deps import ChaosDep, ReadinessDep

router = APIRouter(tags=["ops"], include_in_schema=False)


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(probe: ReadinessDep, controller: ChaosDep) -> JSONResponse:
    if controller.state.fail_readiness:
        return JSONResponse(
            {"status": "not ready", "reason": "chaos: fail_readiness"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    checks = {"postgres": await probe.postgres(), "redis": await probe.redis()}
    ready = all(checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "not ready", "checks": checks},
        status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
