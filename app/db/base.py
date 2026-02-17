from datetime import datetime, timezone

from sqlalchemy import MetaData, event
from sqlalchemy.orm import DeclarativeBase


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@event.listens_for(Base, "before_update", propagate=True)
def _set_updated_at_before_update(_mapper, _connection, target) -> None:
    # Keep audit timestamps current for ORM-managed updates.
    if hasattr(target, "updated_at"):
        target.updated_at = datetime.now(timezone.utc)


metadata = Base.metadata
