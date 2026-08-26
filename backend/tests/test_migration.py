"""Alembic migration tests: verify upgrade, stamp, and data preservation."""
import os
import tempfile
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

# Migration tests use real file-based SQLite databases (alembic needs a file).
# They do not import from conftest.py to avoid the in-memory override.

_KNOWN_TABLES = 35  # Baseline (33) + agent_actions + agent_jobs (agent_impact_jobs 收敛进 agent_jobs)
_HEAD_REVISION = "6c0b1d9e4a3f"  # phase4.4 durable jobs


@pytest.fixture
def tmp_db():
    """Yield a temporary SQLite database path, cleaned up after test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)


def _run_alembic_on(db_path: str, command: str) -> None:
    """Run an alembic command against a SQLite database at db_path."""
    import shlex
    import subprocess
    import sys

    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *shlex.split(command)],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),  # backend/
        env=env,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic {command} failed:\n{result.stdout}\n{result.stderr}")
    return result


def test_empty_db_upgrade_head(tmp_db):
    """A completely empty database should be upgradeable to head."""
    _run_alembic_on(tmp_db, "upgrade head")

    engine = create_engine(f"sqlite:///{tmp_db}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "alembic_version" in tables, "alembic_version table missing"
    assert len(tables) == _KNOWN_TABLES + 1, f"Expected {_KNOWN_TABLES + 1} tables, got {len(tables)}"

    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert row == _HEAD_REVISION, f"Expected head revision {_HEAD_REVISION}, got {row}"
    engine.dispose()


def test_alembic_check_no_diff(tmp_db):
    """alembic check should report no new operations after upgrade head."""
    _run_alembic_on(tmp_db, "upgrade head")
    _run_alembic_on(tmp_db, "check")


def test_alembic_current_shows_head(tmp_db):
    """alembic current should show the head revision."""
    _run_alembic_on(tmp_db, "upgrade head")
    result = _run_alembic_on(tmp_db, "current")
    assert _HEAD_REVISION in result.stdout, f"Expected {_HEAD_REVISION} in current, got: {result.stdout}"


def test_existing_db_stamp_and_upgrade(tmp_db):
    """Simulate an existing DB with create_all then stamp + upgrade."""
    # 1. Create tables via create_all (simulating a pre-migration DB)
    from app.config import settings as app_settings
    from app.db.base import Base

    engine = create_engine(f"sqlite:///{tmp_db}")
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    assert "alembic_version" not in inspector.get_table_names()
    engine.dispose()

    # 2. Stamp to head
    _run_alembic_on(tmp_db, f"stamp {_HEAD_REVISION}")

    engine = create_engine(f"sqlite:///{tmp_db}")
    inspector = inspect(engine)
    assert "alembic_version" in inspector.get_table_names()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert row == _HEAD_REVISION, f"Expected head revision, got {row}"
    engine.dispose()


def test_existing_db_data_preserved(tmp_db):
    """Create tables, insert data, stamp, verify data survives."""
    from app.models.sys import App, User
    from app.db.base import Base

    engine = create_engine(f"sqlite:///{tmp_db}")
    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine)
    db = Session()
    app = App(id=1, app_name="test-app", app_key="test-key", status="active")
    db.add(app)
    db.commit()
    db.close()
    engine.dispose()

    _run_alembic_on(tmp_db, f"stamp {_HEAD_REVISION}")

    engine = create_engine(f"sqlite:///{tmp_db}")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT app_name FROM apps WHERE id=1")).scalar()
    assert row == "test-app", f"Expected 'test-app', got {row}"
    engine.dispose()


def test_schema_match_all_expected_tables(tmp_db):
    """Verify that upgrade head creates all expected model tables."""
    _run_alembic_on(tmp_db, "upgrade head")

    from app.db.base import Base
    from app.models import agent_runtime as _arm  # noqa: F401
    import app.models.campaign  # noqa: F401
    import app.models.data  # noqa: F401
    import app.models.intent  # noqa: F401
    import app.models.sys  # noqa: F401

    expected = set(Base.metadata.tables.keys())
    expected.add("alembic_version")

    engine = create_engine(f"sqlite:///{tmp_db}")
    inspector = inspect(engine)
    actual = set(inspector.get_table_names())

    missing = expected - actual
    extra = actual - expected
    errors = []
    if missing:
        errors.append(f"Missing tables: {sorted(missing)}")
    if extra:
        errors.append(f"Extra tables: {sorted(extra)}")
    if errors:
        pytest.fail("; ".join(errors))
    engine.dispose()