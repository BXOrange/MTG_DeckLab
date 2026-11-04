"""Own the catalogue tests' shared named-card connection for this session."""

import pytest

from tests.support.card_cache import close_card_cache


@pytest.fixture(scope="session", autouse=True)
def _catalogue_card_cache():
    yield
    close_card_cache()
