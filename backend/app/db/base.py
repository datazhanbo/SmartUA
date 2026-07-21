from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
    echo=False  # 关闭SQL日志
)

# SQLite 并发优化：启用 WAL 日志模式 +  busy_timeout，
# 使 Agent 运行时存储（自有 SessionLocal）与请求事务可安全并发读写同一库文件。
if "sqlite" in settings.database_url:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, conn_record):
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
        finally:
            cur.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
