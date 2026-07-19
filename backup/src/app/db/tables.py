from threading import RLock

from sqlalchemy import MetaData, Table
from sqlalchemy.orm import Session

_metadata = MetaData()
_lock = RLock()


def table(db: Session, name: str) -> Table:
    """Reflect a production table lazily without coupling API startup to the database."""
    existing = _metadata.tables.get(name)
    if existing is not None:
        return existing
    with _lock:
        existing = _metadata.tables.get(name)
        if existing is not None:
            return existing
        return Table(name, _metadata, autoload_with=db.get_bind())
