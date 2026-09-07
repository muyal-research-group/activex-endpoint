import pytest

from axo_vem.domain.choreography.retry_policy import next_delay_seconds


def test_constant_policy_always_returns_base():
    assert next_delay_seconds("constant", 1, base_seconds=2.0) == 2.0
    assert next_delay_seconds("constant", 5, base_seconds=2.0) == 2.0


def test_exponential_backoff_doubles_each_attempt():
    assert next_delay_seconds("exponential_backoff", 1, base_seconds=1.0) == 1.0
    assert next_delay_seconds("exponential_backoff", 2, base_seconds=1.0) == 2.0
    assert next_delay_seconds("exponential_backoff", 3, base_seconds=1.0) == 4.0


def test_exponential_backoff_is_capped_at_max_seconds():
    assert next_delay_seconds("exponential_backoff", 10, base_seconds=1.0, max_seconds=5.0) == 5.0


def test_jitter_stays_within_the_exponential_envelope():
    for attempt in range(1, 5):
        delay = next_delay_seconds("jitter", attempt, base_seconds=1.0, max_seconds=100.0)
        assert 0 <= delay <= 2 ** (attempt - 1)


def test_unknown_policy_raises():
    with pytest.raises(ValueError):
        next_delay_seconds("bogus", 1)
