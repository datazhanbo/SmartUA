"""Shared test fixtures: in-memory SQLite, singleton reset, mock connector."""
import os

os.environ["DATABASE_URL"] = "sqlite://"  # in-memory, before any app import

from datetime import date, timedelta
from typing import Iterator
import pytest

from app.db.base import Base, engine, SessionLocal
import app.models.data  # noqa: F401 — register FactMediaDaily etc.
from app.models import agent_runtime as _agent_runtime_models  # noqa: F401

from app.services.agent_runtime.session import get_session_store
from app.services.agent_runtime.memory import get_memory
from app.services.agent_runtime.autonomy import (
    Anomaly, AutonomyAlert, get_autonomy_store, AnomalyDetector, AutonomyEngine,
)
from app.services.agent_runtime.strategy import get_strategy
from app.services.connectors import ConnectorFactory
from app.services.connectors.mock_media import MockMediaConnector, reset_sim_engine, get_sim_engine
from app.config import settings

# Create all tables once at module load
Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset all singletons and DB before each test."""
    get_session_store().clear()
    get_memory().clear()
    get_autonomy_store().clear()
    get_strategy().reset()
    reset_sim_engine(seed=42)
    yield


@pytest.fixture
def db_session() -> Iterator:
    """Provide a clean DB session, rolled back after test."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()