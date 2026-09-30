"""JSON API для Telegram Mini App — только чтение, все роуты защищены
проверкой initData + whitelist (см. telegram_auth.py)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Subject, Folder, Category, Document
from telegram_auth import require_telegram_user

router = APIRouter(prefix="/api", dependencies=[Depends(require_telegram_user)])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def doc_to_dict(d: Document) -> dict:
    return {
        "id": d.id, "title": d.title,
        "category": d.category.name, "category_id": d.category_id,
        "series": d.series, "number": d.number, "issued_by": d.issued_by,
        "issue_date": d.issue_date.isoformat() if d.issue_date else None,
        "valid_from": d.valid_from.isoformat() if d.valid_from else None,
        "valid_until": d.valid_until.isoformat() if d.valid_until else None,
        "is_primary": d.is_primary,
        "subject_id": d.subject_id, "subject_name": d.subject.name,
        "folder_id": d.folder_id,
    }


@router.get("/subjects")
def list_subjects(db: Session = Depends(get_db)):
    subjects = db.scalars(select(Subject)).all()
    counts = {
        sid: c for sid, c in db.query(Document.subject_id, func.count(Document.id))
        .group_by(Document.subject_id).all()
    }
    return [
        {"id": s.id, "name": s.name, "doc_count": counts.get(s.id, 0)}
        for s in subjects
    ]


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    return [{"id": c.id, "name": c.name} for c in db.scalars(select(Category)).all()]


@router.get("/documents/{doc_id}")
def document_detail(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    return doc_to_dict(doc)


@router.get("/subjects/{subject_id}")
def subject_detail(subject_id: int, db: Session = Depends(get_db)):
    subject = db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Субъект не найден")
    folders = db.scalars(select(Folder).where(Folder.subject_id == subject_id)).all()
    documents = db.scalars(
        select(Document).where(Document.subject_id == subject_id)
        .order_by(Document.issue_date.desc())
    ).all()
    by_folder: dict[int, list] = {}
    no_folder = []
    for d in documents:
        target = by_folder.setdefault(d.folder_id, []) if d.folder_id else no_folder
        target.append(doc_to_dict(d))
    return {
        "id": subject.id, "name": subject.name,
        "folders": [
            {"id": f.id, "name": f.name, "documents": by_folder.get(f.id, [])}
            for f in folders
        ],
        "documents_no_folder": no_folder,
    }


@router.get("/search")
def search_documents(
    q: Optional[str] = None,
    subject_id: Optional[int] = None,
    category_id: Optional[int] = None,
    primary_only: bool = False,
    db: Session = Depends(get_db),
):
    query = select(Document)
    if subject_id:
        query = query.where(Document.subject_id == subject_id)
    if category_id:
        query = query.where(Document.category_id == category_id)
    if primary_only:
        query = query.where(Document.is_primary.is_(True))
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                Document.title.ilike(like), Document.series.ilike(like),
                Document.number.ilike(like), Document.issued_by.ilike(like),
            )
        )
    query = query.order_by(Document.issue_date.desc())
    return [doc_to_dict(d) for d in db.scalars(query).all()]
