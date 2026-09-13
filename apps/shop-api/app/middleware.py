from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from starlette.responses import JSONResponse
from starlette.routing import BaseRoute
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.chaos import ChaosController
from app.metrics import HTTP_IN_FLIGHT, HTTP_REQUEST_DURATION, HTTP_REQUESTS

UNMATCHED_ROUTE = "unmatched"


def _flatten(routes: Iterable[BaseRoute]) -> Iterator[BaseRoute]:
    for route in routes:
        included = getattr(route, "original_router", None)
        nested = getattr(included, "routes", None) or getattr(route, "routes", None)
        if nested is None:
            yield route
        else:
            yield from _flatten(nested)


class RouteIndex:
    """Maps a handled endpoint back to its path template.

    Starlette leaves `endpoint` and `path_params` in the scope after routing, but
    not the route itself, and the router tree is rebuilt whenever routes are added,
    so the map is refreshed when the route list changes.
    """

    def __init__(self, routes: Sequence[BaseRoute]) -> None:
        self._routes = routes
        self._templates: dict[Any, str] = {}
        self._built_for = -1

    def template_for(self, scope: Scope) -> str:
        endpoint = scope.get("endpoint")
        if endpoint is None:
            return UNMATCHED_ROUTE
        if self._built_for != len(self._routes):
            self._rebuild()
        return self._templates.get(endpoint, UNMATCHED_ROUTE)

    def _rebuild(self) -> None:
        templates: dict[Any, str] = {}
        for route in _flatten(self._routes):
            endpoint = getattr(route, "endpoint", None)
            template = getattr(route, "path_format", None) or getattr(route, "path", None)
            if endpoint is not None and template:
                templates[endpoint] = str(template)
        self._templates = templates
        self._built_for = len(self._routes)


class MetricsMiddleware:
    def __init__(
        self, app: ASGIApp, routes: Sequence[BaseRoute], controller: ChaosController
    ) -> None:
        self.app = app
        self._index = RouteIndex(routes)
        self._chaos = controller

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method", "GET"))
        status = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        HTTP_IN_FLIGHT.inc()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            HTTP_IN_FLIGHT.dec()
            route = self._index.template_for(scope)
            HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(
                time.perf_counter() - started
            )
            user_id: str | None = None
            if self._chaos.state.high_cardinality:
                params = scope.get("path_params") or {}
                raw = params.get("user_id")
                user_id = str(raw) if raw is not None else None
            HTTP_REQUESTS.inc(method, route, str(status), user_id)


class ChaosMiddleware:
    def __init__(self, app: ASGIApp, controller: ChaosController) -> None:
        self.app = app
        self._chaos = controller
        self._rng = random.Random()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith("/api"):
            await self.app(scope, receive, send)
            return

        state = self._chaos.state
        delay_ms = float(state.latency_ms)
        if state.latency_jitter_ms:
            delay_ms += self._rng.uniform(0.0, float(state.latency_jitter_ms))
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

        if state.error_rate > 0 and self._rng.random() < state.error_rate:
            response = JSONResponse(
                {"detail": "chaos: injected failure", "source": "chaos"}, status_code=500
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
