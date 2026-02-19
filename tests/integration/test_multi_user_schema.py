import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def _insert_user(db_session: AsyncSession, email: str) -> int:
    result = await db_session.execute(
        text(
            """
            INSERT INTO users (email, password_hash)
            VALUES (:email, :password_hash)
            RETURNING id
            """
        ),
        {"email": email, "password_hash": "argon2id$placeholder"},
    )
    return int(result.scalar_one())


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.schema
@pytest.mark.asyncio
async def test_scholar_id_uniqueness_is_scoped_to_user(db_session: AsyncSession) -> None:
    user_a = await _insert_user(db_session, "owner-a@example.com")
    user_b = await _insert_user(db_session, "owner-b@example.com")
    await db_session.commit()

    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name)
            VALUES (:user_id, :scholar_id, :display_name)
            """
        ),
        {"user_id": user_a, "scholar_id": "abcDEF123456", "display_name": "Alpha"},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name)
            VALUES (:user_id, :scholar_id, :display_name)
            """
        ),
        {"user_id": user_b, "scholar_id": "abcDEF123456", "display_name": "Beta"},
    )
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                """
                INSERT INTO scholar_profiles (user_id, scholar_id, display_name)
                VALUES (:user_id, :scholar_id, :display_name)
                """
            ),
            {"user_id": user_a, "scholar_id": "abcDEF123456", "display_name": "Gamma"},
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.schema
@pytest.mark.asyncio
async def test_user_settings_allow_only_one_row_per_user(db_session: AsyncSession) -> None:
    user_id = await _insert_user(db_session, "settings-owner@example.com")
    await db_session.commit()

    await db_session.execute(
        text(
            """
            INSERT INTO user_settings (user_id, auto_run_enabled, run_interval_minutes, request_delay_seconds)
            VALUES (:user_id, :auto_run_enabled, :run_interval_minutes, :request_delay_seconds)
            """
        ),
        {
            "user_id": user_id,
            "auto_run_enabled": True,
            "run_interval_minutes": 60,
            "request_delay_seconds": 10,
        },
    )
    await db_session.commit()

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                """
                INSERT INTO user_settings (user_id, auto_run_enabled, run_interval_minutes, request_delay_seconds)
                VALUES (:user_id, :auto_run_enabled, :run_interval_minutes, :request_delay_seconds)
                """
            ),
            {
                "user_id": user_id,
                "auto_run_enabled": False,
                "run_interval_minutes": 30,
                "request_delay_seconds": 5,
            },
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.schema
@pytest.mark.asyncio
async def test_crawl_run_requires_owner_user(db_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                """
                INSERT INTO crawl_runs (user_id, trigger_type, status)
                VALUES (:user_id, :trigger_type, :status)
                """
            ),
            {"user_id": None, "trigger_type": "manual", "status": "running"},
        )
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.schema
@pytest.mark.asyncio
async def test_read_state_is_isolated_across_users(db_session: AsyncSession) -> None:
    user_a = await _insert_user(db_session, "reader-a@example.com")
    user_b = await _insert_user(db_session, "reader-b@example.com")

    scholar_a = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name)
            VALUES (:user_id, :scholar_id, :display_name)
            RETURNING id
            """
        ),
        {"user_id": user_a, "scholar_id": "qwerty123456", "display_name": "Reader A"},
    )
    scholar_a_id = int(scholar_a.scalar_one())

    scholar_b = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name)
            VALUES (:user_id, :scholar_id, :display_name)
            RETURNING id
            """
        ),
        {"user_id": user_b, "scholar_id": "zxcvbn654321", "display_name": "Reader B"},
    )
    scholar_b_id = int(scholar_b.scalar_one())

    publication = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, year)
            VALUES (:fingerprint_sha256, :title_raw, :title_normalized, :year)
            RETURNING id
            """
        ),
        {
            "fingerprint_sha256": "f" * 64,
            "title_raw": "A Shared Paper",
            "title_normalized": "a shared paper",
            "year": 2026,
        },
    )
    publication_id = int(publication.scalar_one())

    run_a = await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (user_id, trigger_type, status)
            VALUES (:user_id, :trigger_type, :status)
            RETURNING id
            """
        ),
        {"user_id": user_a, "trigger_type": "manual", "status": "success"},
    )
    run_a_id = int(run_a.scalar_one())

    run_b = await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (user_id, trigger_type, status)
            VALUES (:user_id, :trigger_type, :status)
            RETURNING id
            """
        ),
        {"user_id": user_b, "trigger_type": "manual", "status": "success"},
    )
    run_b_id = int(run_b.scalar_one())

    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, first_seen_run_id)
            VALUES (:scholar_profile_id, :publication_id, :is_read, :first_seen_run_id)
            """
        ),
        {
            "scholar_profile_id": scholar_a_id,
            "publication_id": publication_id,
            "is_read": False,
            "first_seen_run_id": run_a_id,
        },
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, first_seen_run_id)
            VALUES (:scholar_profile_id, :publication_id, :is_read, :first_seen_run_id)
            """
        ),
        {
            "scholar_profile_id": scholar_b_id,
            "publication_id": publication_id,
            "is_read": True,
            "first_seen_run_id": run_b_id,
        },
    )
    await db_session.commit()

    result = await db_session.execute(
        text(
            """
            SELECT sp.user_id, spp.is_read
            FROM scholar_publications spp
            JOIN scholar_profiles sp ON sp.id = spp.scholar_profile_id
            ORDER BY sp.user_id
            """
        )
    )
    rows = result.all()
    assert rows == [(user_a, False), (user_b, True)]


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.schema
@pytest.mark.asyncio
async def test_publication_records_are_shared_across_accounts(db_session: AsyncSession) -> None:
    user_a = await _insert_user(db_session, "shared-a@example.com")
    user_b = await _insert_user(db_session, "shared-b@example.com")

    scholar_a = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name)
            VALUES (:user_id, :scholar_id, :display_name)
            RETURNING id
            """
        ),
        {"user_id": user_a, "scholar_id": "sharedAAA1111", "display_name": "Shared A"},
    )
    scholar_a_id = int(scholar_a.scalar_one())

    scholar_b = await db_session.execute(
        text(
            """
            INSERT INTO scholar_profiles (user_id, scholar_id, display_name)
            VALUES (:user_id, :scholar_id, :display_name)
            RETURNING id
            """
        ),
        {"user_id": user_b, "scholar_id": "sharedBBB2222", "display_name": "Shared B"},
    )
    scholar_b_id = int(scholar_b.scalar_one())

    publication = await db_session.execute(
        text(
            """
            INSERT INTO publications (fingerprint_sha256, title_raw, title_normalized, year)
            VALUES (:fingerprint_sha256, :title_raw, :title_normalized, :year)
            RETURNING id
            """
        ),
        {
            "fingerprint_sha256": "a" * 64,
            "title_raw": "Shared Record",
            "title_normalized": "shared record",
            "year": 2025,
        },
    )
    publication_id = int(publication.scalar_one())

    run_a = await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (user_id, trigger_type, status)
            VALUES (:user_id, :trigger_type, :status)
            RETURNING id
            """
        ),
        {"user_id": user_a, "trigger_type": "manual", "status": "success"},
    )
    run_a_id = int(run_a.scalar_one())

    run_b = await db_session.execute(
        text(
            """
            INSERT INTO crawl_runs (user_id, trigger_type, status)
            VALUES (:user_id, :trigger_type, :status)
            RETURNING id
            """
        ),
        {"user_id": user_b, "trigger_type": "manual", "status": "success"},
    )
    run_b_id = int(run_b.scalar_one())

    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, first_seen_run_id)
            VALUES (:scholar_profile_id, :publication_id, :is_read, :first_seen_run_id)
            """
        ),
        {
            "scholar_profile_id": scholar_a_id,
            "publication_id": publication_id,
            "is_read": False,
            "first_seen_run_id": run_a_id,
        },
    )
    await db_session.execute(
        text(
            """
            INSERT INTO scholar_publications (scholar_profile_id, publication_id, is_read, first_seen_run_id)
            VALUES (:scholar_profile_id, :publication_id, :is_read, :first_seen_run_id)
            """
        ),
        {
            "scholar_profile_id": scholar_b_id,
            "publication_id": publication_id,
            "is_read": False,
            "first_seen_run_id": run_b_id,
        },
    )
    await db_session.commit()

    publication_row_count = await db_session.execute(
        text("SELECT COUNT(*) FROM publications WHERE id = :publication_id"),
        {"publication_id": publication_id},
    )
    assert int(publication_row_count.scalar_one()) == 1

    link_count = await db_session.execute(
        text("SELECT COUNT(*) FROM scholar_publications WHERE publication_id = :publication_id"),
        {"publication_id": publication_id},
    )
    assert int(link_count.scalar_one()) == 2

    owner_count = await db_session.execute(
        text(
            """
            SELECT COUNT(DISTINCT sp.user_id)
            FROM scholar_publications spp
            JOIN scholar_profiles sp ON sp.id = spp.scholar_profile_id
            WHERE spp.publication_id = :publication_id
            """
        ),
        {"publication_id": publication_id},
    )
    assert int(owner_count.scalar_one()) == 2
