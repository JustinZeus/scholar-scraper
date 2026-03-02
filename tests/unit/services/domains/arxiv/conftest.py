from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def patch_session_factory(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    """Patch get_session_factory in arxiv modules to use the test's DB engine.

    Without this, the implementation creates its own engine via get_session_factory()
    which may not share transaction visibility with the test's db_session fixture.
    """
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr("app.services.arxiv.rate_limit.get_session_factory", lambda: factory)
    monkeypatch.setattr("app.services.arxiv.cache.get_session_factory", lambda: factory)
    return factory
