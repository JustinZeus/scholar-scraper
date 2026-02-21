"""enforce request delay floor at two seconds

Revision ID: 20260221_0015
Revises: 20260221_0014
Create Date: 2026-02-21 18:10:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260221_0015"
down_revision: str | Sequence[str] | None = "20260221_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_NAME = "user_settings"
CHECK_NAME_MIN_1 = "request_delay_seconds_min_1"
CHECK_NAME_MIN_2 = "request_delay_seconds_min_2"
LEGACY_CHECK_NAME_MIN_1 = "ck_user_settings_request_delay_seconds_min_1"
LEGACY_CHECK_NAME_MIN_2 = "ck_user_settings_request_delay_seconds_min_2"


def _check_constraints() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {
        str(item.get("name"))
        for item in inspector.get_check_constraints(TABLE_NAME)
        if item.get("name")
    }


def _drop_check_if_exists(name: str) -> None:
    if name not in _check_constraints():
        return
    op.drop_constraint(
        name,
        TABLE_NAME,
        type_="check",
    )


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE user_settings SET request_delay_seconds = 2 "
            "WHERE request_delay_seconds < 2"
        )
    )

    _drop_check_if_exists(CHECK_NAME_MIN_1)
    _drop_check_if_exists(LEGACY_CHECK_NAME_MIN_1)

    existing = _check_constraints()
    if CHECK_NAME_MIN_2 not in existing and LEGACY_CHECK_NAME_MIN_2 not in existing:
        op.create_check_constraint(
            CHECK_NAME_MIN_2,
            TABLE_NAME,
            "request_delay_seconds >= 2",
        )


def downgrade() -> None:
    _drop_check_if_exists(CHECK_NAME_MIN_2)
    _drop_check_if_exists(LEGACY_CHECK_NAME_MIN_2)

    existing = _check_constraints()
    if CHECK_NAME_MIN_1 not in existing and LEGACY_CHECK_NAME_MIN_1 not in existing:
        op.create_check_constraint(
            CHECK_NAME_MIN_1,
            TABLE_NAME,
            "request_delay_seconds >= 1",
        )
