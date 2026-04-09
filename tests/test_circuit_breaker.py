"""Testes para CircuitBreaker e RateLimiter."""
from __future__ import annotations

import time
import threading

from rtxlator.circuit_breaker import CircuitBreaker, RateLimiter


# ── CircuitBreaker ─────────────────────────────────────────────────────────────

class TestCircuitBreakerClosed:
    """Testa o comportamento do breaker no estado CLOSED (normal)."""

    def test_allows_calls_when_closed(self):
        cb = CircuitBreaker("test", max_failures=3, cooldown_s=10)
        assert cb.allow() is True

    def test_stays_closed_on_success(self):
        cb = CircuitBreaker("test", max_failures=3, cooldown_s=10)
        cb.record_success()
        cb.record_success()
        assert cb.allow() is True
        assert cb.stats.is_open is False

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker("test", max_failures=3, cooldown_s=10)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow() is True
        assert cb.stats.consecutive_failures == 2
        assert cb.stats.is_open is False


class TestCircuitBreakerOpen:
    """Testa o comportamento do breaker no estado OPEN (falhando)."""

    def test_opens_after_max_failures(self):
        cb = CircuitBreaker("test", max_failures=3, cooldown_s=10)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.allow() is False
        assert cb.stats.is_open is True

    def test_blocks_calls_during_cooldown(self):
        cb = CircuitBreaker("test", max_failures=2, cooldown_s=100)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow() is False
        assert cb.allow() is False


class TestCircuitBreakerHalfOpen:
    """Testa o comportamento half-open (cooldown expirado)."""

    def test_allows_after_cooldown(self):
        cb = CircuitBreaker("test", max_failures=2, cooldown_s=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow() is False
        time.sleep(0.06)
        assert cb.allow() is True

    def test_success_after_halfopen_closes_breaker(self):
        cb = CircuitBreaker("test", max_failures=2, cooldown_s=0.05)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        cb.record_success()
        assert cb.stats.is_open is False
        assert cb.stats.consecutive_failures == 0


class TestCircuitBreakerReset:
    """Testa reset de falhas após sucesso."""

    def test_success_resets_consecutive_failures(self):
        cb = CircuitBreaker("test", max_failures=3, cooldown_s=10)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.stats.consecutive_failures == 0
        # Não deveria abrir com mais 2 falhas agora
        cb.record_failure()
        cb.record_failure()
        assert cb.allow() is True


class TestCircuitBreakerStats:
    """Testa as estatísticas do provider."""

    def test_stats_track_totals(self):
        cb = CircuitBreaker("test", max_failures=5, cooldown_s=10)
        cb.record_success()
        cb.record_success()
        cb.record_failure()
        stats = cb.stats
        assert stats.total_calls == 3
        assert stats.total_successes == 2
        assert stats.total_failures == 1
        assert abs(stats.success_rate - 2 / 3) < 0.01

    def test_cooldown_remaining(self):
        cb = CircuitBreaker("test", max_failures=1, cooldown_s=10)
        cb.record_failure()
        stats = cb.stats
        assert stats.cooldown_remaining_s > 8  # deve ter quase 10s restando


class TestCircuitBreakerThreadSafety:
    """Testa segurança em cenário multi-threaded."""

    def test_concurrent_access(self):
        cb = CircuitBreaker("test", max_failures=100, cooldown_s=10)
        errors = []

        def worker():
            try:
                for _ in range(100):
                    cb.allow()
                    cb.record_success()
                    cb.record_failure()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        stats = cb.stats
        assert stats.total_calls == 1600  # 8 threads * 100 * 2 (success + failure)


# ── RateLimiter ────────────────────────────────────────────────────────────────

class TestRateLimiter:
    """Testa o rate limiter baseado em token bucket."""

    def test_first_call_always_allowed(self):
        rl = RateLimiter(max_per_second=1.0)
        assert rl.acquire() is True

    def test_second_call_too_fast_blocked(self):
        rl = RateLimiter(max_per_second=2.0)
        rl.acquire()
        assert rl.acquire() is False

    def test_call_allowed_after_interval(self):
        rl = RateLimiter(max_per_second=20.0)  # 50ms interval
        rl.acquire()
        time.sleep(0.06)
        assert rl.acquire() is True

    def test_tracks_limited_count(self):
        rl = RateLimiter(max_per_second=1.0)
        rl.acquire()
        rl.acquire()  # blocked
        rl.acquire()  # blocked
        assert rl.total_limited == 2

    def test_acquire_blocking_succeeds(self):
        rl = RateLimiter(max_per_second=10.0)  # 100ms interval
        rl.acquire()
        # should wait and succeed within timeout
        assert rl.acquire_blocking(timeout=0.5) is True

    def test_acquire_blocking_timeout(self):
        rl = RateLimiter(max_per_second=0.5)  # 2s interval
        rl.acquire()
        # timeout is shorter than interval, should fail
        assert rl.acquire_blocking(timeout=0.1) is False
