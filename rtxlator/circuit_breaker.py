"""Circuit breaker e rate limiter para providers de tradução.

Evita chamadas repetidas a providers que estão falhando e protege
contra rate limiting de APIs externas.

Uso:
    breaker = CircuitBreaker(provider="google", max_failures=3, cooldown_s=30)
    if breaker.allow():
        try:
            result = translate(...)
            breaker.record_success()
        except Exception:
            breaker.record_failure()
    else:
        # provider está em cooldown, pular
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class ProviderStats:
    """Estatísticas observáveis de um provider."""
    total_calls: int = 0
    total_successes: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    is_open: bool = False
    last_failure_at: float = 0.0
    cooldown_remaining_s: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 1.0
        return self.total_successes / self.total_calls

    @property
    def failure_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_failures / self.total_calls


class CircuitBreaker:
    """Circuit breaker por provider — bloqueia após N falhas consecutivas.

    Estados:
      - CLOSED: provider funcionando, chamadas permitidas
      - OPEN: provider falhando, chamadas bloqueadas por cooldown_s
      - HALF-OPEN: cooldown expirou, próxima chamada é teste

    O breaker reabre automaticamente após cooldown para testar recovery.
    """

    def __init__(
        self,
        provider: str,
        max_failures: int = 3,
        cooldown_s: float = 30.0,
    ):
        self.provider = provider
        self.max_failures = max_failures
        self.cooldown_s = cooldown_s

        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._total_calls = 0
        self._total_successes = 0
        self._total_failures = 0
        self._last_failure_at = 0.0
        self._is_open = False

    def allow(self) -> bool:
        """Retorna True se o provider pode ser chamado agora."""
        with self._lock:
            if not self._is_open:
                return True
            # Verifica se o cooldown expirou (half-open)
            elapsed = time.monotonic() - self._last_failure_at
            if elapsed >= self.cooldown_s:
                return True
            return False

    def record_success(self) -> None:
        """Registra sucesso — fecha o breaker e reseta falhas."""
        with self._lock:
            self._total_calls += 1
            self._total_successes += 1
            self._consecutive_failures = 0
            self._is_open = False

    def record_failure(self) -> None:
        """Registra falha — abre o breaker se atingir max_failures."""
        with self._lock:
            self._total_calls += 1
            self._total_failures += 1
            self._consecutive_failures += 1
            self._last_failure_at = time.monotonic()
            if self._consecutive_failures >= self.max_failures:
                self._is_open = True

    @property
    def stats(self) -> ProviderStats:
        """Snapshot das estatísticas do provider."""
        with self._lock:
            remaining = 0.0
            if self._is_open:
                elapsed = time.monotonic() - self._last_failure_at
                remaining = max(0.0, self.cooldown_s - elapsed)
            return ProviderStats(
                total_calls=self._total_calls,
                total_successes=self._total_successes,
                total_failures=self._total_failures,
                consecutive_failures=self._consecutive_failures,
                is_open=self._is_open,
                last_failure_at=self._last_failure_at,
                cooldown_remaining_s=remaining,
            )


class RateLimiter:
    """Rate limiter simples baseado em token bucket.

    Limita a N chamadas por segundo para evitar bloqueio de IP.
    """

    def __init__(self, max_per_second: float = 3.0):
        self._min_interval = 1.0 / max_per_second
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._total_limited = 0

    def acquire(self) -> bool:
        """Retorna True se a chamada é permitida. Não bloqueia."""
        with self._lock:
            now = time.monotonic()
            if now - self._last_call >= self._min_interval:
                self._last_call = now
                return True
            self._total_limited += 1
            return False

    def acquire_blocking(self, timeout: float = 2.0) -> bool:
        """Espera até a chamada ser permitida ou timeout. Retorna True se conseguiu."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acquire():
                return True
            time.sleep(self._min_interval * 0.5)
        return False

    @property
    def total_limited(self) -> int:
        """Quantidade de chamadas que foram limitadas."""
        with self._lock:
            return self._total_limited
