import os
import re
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from models import Base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./doxbot.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def parse_drive_file_id(link: str) -> str | None:
    """Достаёт file_id из ссылки Google Drive любого распространённого формата."""
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", link) or re.search(r"[?&]id=([a-zA-Z0-9_-]+)", link)
    return match.group(1) if match else None


def init_db():
    """Создаёт обычные таблицы + виртуальную FTS5-таблицу с триггерами
    синхронизации, если их ещё нет."""
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        conn.exec_driver_sql("""
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                title, series, number, issued_by,
                content='documents', content_rowid='id'
            )
        """)
        conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, title, series, number, issued_by)
                VALUES (new.id, new.title, new.series, new.number, new.issued_by);
            END
        """)
        conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, title, series, number, issued_by)
                VALUES ('delete', old.id, old.title, old.series, old.number, old.issued_by);
            END
        """)
        conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, title, series, number, issued_by)
                VALUES ('delete', old.id, old.title, old.series, old.number, old.issued_by);
                INSERT INTO documents_fts(rowid, title, series, number, issued_by)
                VALUES (new.id, new.title, new.series, new.number, new.issued_by);
            END
        """)
        conn.commit()
