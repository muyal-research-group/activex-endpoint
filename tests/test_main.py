import pytest

from axo_endpoint.main import _raise_keyboard_interrupt


def test_raise_keyboard_interrupt_converts_sigterm_to_keyboard_interrupt():
    with pytest.raises(KeyboardInterrupt):
        _raise_keyboard_interrupt(None, None)
