"""Config-driven routing with retry + circuit breaker, generic over
capability (LLM generation, LLM verification, embeddings, parsing).

This is the one place retry/backoff/circuit-breaker policy lives — providers
themselves should be thin SDK wrappers with no resilience logic of their own.
"""

import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.providers.base import ProviderError, ProviderUnavailableError

logger = logging.getLogger(__name__)

T = TypeVar("T")  # provider type
R = TypeVar("R")  # call() return type — independent of T, e.g. LLMResponse from an LLMProvider


@dataclass
class CircuitBreakerState:
    failure_count: int = 0
    opened_at: float | None = None


class CircuitBreaker:
    def __init__(self, failure_threshold: int, cooldown_seconds: int):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = CircuitBreakerState()

    def before_call(self, provider_name: str) -> None:
        if self._state.opened_at is None:
            return
        elapsed = time.monotonic() - self._state.opened_at
        if elapsed < self.cooldown_seconds:
            raise ProviderUnavailableError(
                f"{provider_name}: circuit open, {self.cooldown_seconds - elapsed:.0f}s "
                "left in cooldown"
            )
        # Cooldown elapsed — allow a trial call; reset on success/failure below.
        self._state = CircuitBreakerState()

    def record_success(self) -> None:
        self._state = CircuitBreakerState()

    def record_failure(self, provider_name: str) -> None:
        self._state.failure_count += 1
        if self._state.failure_count >= self.failure_threshold:
            self._state.opened_at = time.monotonic()
            logger.warning(
                "provider %s: circuit breaker opened after %d consecutive failures",
                provider_name,
                self._state.failure_count,
            )


class ProviderRouter(Generic[T]):
    """Wraps a single provider with retry + circuit breaker. One of these
    sits behind each entry in a FallbackChain (below) — each provider gets
    its own retry/circuit-breaker state so one provider's outage doesn't
    poison the others' breakers.
    """

    def __init__(
        self,
        provider: T,
        *,
        retry_attempts: int = 3,
        backoff_seconds: int = 2,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown_seconds: int = 60,
    ):
        self.provider = provider
        self._retry_attempts = retry_attempts
        self._backoff_seconds = backoff_seconds
        self._breaker = CircuitBreaker(
            failure_threshold=circuit_breaker_threshold,
            cooldown_seconds=circuit_breaker_cooldown_seconds,
        )

    async def call(self, fn: Callable[[T], Awaitable[R]]) -> R:
        provider_name = getattr(self.provider, "name", type(self.provider).__name__)
        self._breaker.before_call(provider_name)

        @retry(
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(multiplier=self._backoff_seconds, min=1),
            retry=retry_if_exception_type(ProviderError),
            reraise=True,
        )
        async def _attempt() -> R:
            return await fn(self.provider)

        try:
            result = await _attempt()
        except ProviderError:
            self._breaker.record_failure(provider_name)
            raise
        else:
            self._breaker.record_success()
            return result


class FallbackChain(Generic[T]):
    """Tries providers in priority order, moving to the next one when a
    provider's retries are exhausted or its circuit is open.

    Per 04_PROVIDER_STRATEGY.md ("Generation: Anthropic Claude -> OpenAI
    GPT -> self-hosted open-weight") — the ordering in
    config/providers.yaml's `priority` list is the fallback order, not a
    load-balancing set. `exclude` lets a caller rule out specific
    providers for one call without touching config — e.g. verification
    must not silently fall through to the same provider that did the
    generation for the claim being checked.
    """

    def __init__(self, routers: list[tuple[str, ProviderRouter[T]]]):
        if not routers:
            raise ValueError("FallbackChain needs at least one provider")
        self._routers = routers

    @property
    def provider_names(self) -> list[str]:
        """Names in priority order, limited to what's actually configured."""
        return [name for name, _ in self._routers]

    async def call(
        self, fn: Callable[[T], Awaitable[R]], *, exclude: set[str] | None = None
    ) -> R:
        exclude = exclude or set()
        last_exc: ProviderError | None = None
        attempted = 0
        for name, router in self._routers:
            if name in exclude:
                continue
            attempted += 1
            try:
                return await router.call(fn)
            except ProviderError as exc:
                logger.warning("provider %s failed, trying next in chain: %s", name, exc)
                last_exc = exc
                continue

        if attempted == 0:
            raise ProviderUnavailableError(
                f"all providers excluded from chain: {sorted(exclude)}"
            )
        raise ProviderUnavailableError("all providers in fallback chain exhausted") from last_exc
