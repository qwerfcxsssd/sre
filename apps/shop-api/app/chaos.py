import threading
import time
from dataclasses import asdict, dataclass, replace
from typing import Any

_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ChaosState:
    latency_ms: int = 0
    latency_jitter_ms: int = 0
    error_rate: float = 0.0
    cpu_burn: bool = False
    mem_leak_mb_per_min: int = 0
    drop_postgres: bool = False
    drop_redis: bool = False
    fail_readiness: bool = False
    high_cardinality: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ChaosController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = ChaosState()
        self._cpu_stop = threading.Event()
        self._cpu_thread: threading.Thread | None = None
        self._leak_stop = threading.Event()
        self._leak_thread: threading.Thread | None = None
        self._leaked: list[bytearray] = []

    @property
    def state(self) -> ChaosState:
        with self._lock:
            return self._state

    def apply(self, patch: dict[str, Any]) -> ChaosState:
        with self._lock:
            self._state = replace(self._state, **patch)
            state = self._state
        self._sync_workers(state)
        return state

    def reset(self) -> ChaosState:
        with self._lock:
            self._state = ChaosState()
            state = self._state
        self._sync_workers(state)
        with self._lock:
            self._leaked.clear()
        return state

    def leaked_mb(self) -> int:
        with self._lock:
            return len(self._leaked)

    def shutdown(self) -> None:
        self._cpu_stop.set()
        self._leak_stop.set()

    def _sync_workers(self, state: ChaosState) -> None:
        if state.cpu_burn and self._cpu_thread is None:
            self._cpu_stop = threading.Event()
            self._cpu_thread = threading.Thread(
                target=self._burn_cpu, args=(self._cpu_stop,), name="chaos-cpu", daemon=True
            )
            self._cpu_thread.start()
        elif not state.cpu_burn and self._cpu_thread is not None:
            self._cpu_stop.set()
            self._cpu_thread = None

        if self._leak_thread is not None:
            self._leak_stop.set()
            self._leak_thread = None
        if state.mem_leak_mb_per_min > 0:
            self._leak_stop = threading.Event()
            self._leak_thread = threading.Thread(
                target=self._leak_memory,
                args=(state.mem_leak_mb_per_min, self._leak_stop),
                name="chaos-mem",
                daemon=True,
            )
            self._leak_thread.start()

    @staticmethod
    def _burn_cpu(stop: threading.Event) -> None:
        value = 0
        while not stop.is_set():
            for _ in range(2_000_000):
                value = (value * 31 + 7) % 1_000_003
            time.sleep(0)

    def _leak_memory(self, mb_per_min: int, stop: threading.Event) -> None:
        interval = 60.0 / float(mb_per_min)
        while not stop.wait(interval):
            chunk = bytearray(_CHUNK_BYTES)
            chunk[::4096] = b"\x01" * len(chunk[::4096])
            with self._lock:
                self._leaked.append(chunk)


chaos = ChaosController()
