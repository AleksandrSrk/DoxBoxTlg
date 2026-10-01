from contextlib import asynccontextmanager
from datetime import date
import mimetypes
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from database import SessionLocal, init_db, parse_drive_file_id
from download_tokens import verify_download_token
from drive import get_file_metadata, stream_file_chunks
from models import Subject, Folder, Category, Document
from api import router as api_router

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def transliterate(text: str) -> str:
    """Кириллица → латиница, для запасного ASCII-имени файла."""
    out = []
    for ch in text:
        low = ch.lower()
        t = _TRANSLIT.get(low)
        if t is None:
            out.append(ch)
        else:
            out.append(t.capitalize() if ch.isupper() and t else t)
    return "".join(out)


def build_download_filename(doc: Document, original_name: str, mimetype: str) -> str:
    """Имя документа + субъекта вместо того, что как попало называлось
    в Drive (обычно это мусорное имя от сканера)."""
    base = f"{doc.title} {doc.subject.name}".strip()
    ext = original_name.rsplit(".", 1)[-1] if "." in original_name else ""
    if not ext and mimetype:
        guessed = mimetypes.guess_extension(mimetype)
        ext = guessed.lstrip(".") if guessed else ""
    return f"{base}.{ext}" if ext else base


def content_disposition(filename: str) -> str:
    """HTTP-заголовки не умеют напрямую нести не-latin1 символы (кириллицу) —
    кодируем по RFC 5987 (так получит реальное русское имя любой клиент,
    который это умеет), plus запасной вариант для тех, кто не умеет —
    транслитерация в латиницу, а не просто "document.pdf"."""
    from urllib.parse import quote
    ascii_name = transliterate(filename)
    ascii_name = ascii_name.encode("ascii", errors="ignore").decode("ascii").strip()
    base = ascii_name.rsplit(".", 1)[0] if "." in ascii_name else ascii_name
    if not any(c.isalnum() for c in base):
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        ascii_name = f"document.{ext}" if ext else "document"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"

DEFAULT_CATEGORIES = ["Паспорт", "Загран", "Полис ОМС", "СНИЛС", "ИНН", "СОР", "СОБ"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        existing = {c.name for c in db.scalars(select(Category))}
        for name in DEFAULT_CATEGORIES:
            if name not in existing:
                db.add(Category(name=name))
        db.commit()
    finally:
        db.close()
    yield


app = FastAPI(title="doxBot admin", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
app.include_router(api_router)


@app.middleware("http")
async def no_cache_miniapp(request: Request, call_next):
    """Telegram иногда агрессивно кеширует статику мини-аппа — запрещаем
    это явно, чтобы после каждого деплоя прилетала гарантированно свежая
    версия, а не вчерашняя закешированная."""
    response = await call_next(request)
    if request.url.path.startswith("/static/miniapp/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/admin")
def subjects_page(request: Request, db: Session = Depends(get_db)):
    subjects = db.scalars(select(Subject)).all()
    doc_counts = {
        subject_id: count
        for subject_id, count in db.query(Document.subject_id, func.count(Document.id))
        .group_by(Document.subject_id).all()
    }
    return templates.TemplateResponse(request, "subjects.html", {
        "subjects": subjects, "doc_counts": doc_counts,
    })


@app.get("/admin/subjects/{subject_id}")
def subject_detail_page(subject_id: int, request: Request, db: Session = Depends(get_db)):
    subject = db.get(Subject, subject_id)
    if not subject:
        raise HTTPException(404, "Субъект не найден")
    folders = db.scalars(select(Folder).where(Folder.subject_id == subject_id)).all()
    documents = db.scalars(
        select(Document).where(Document.subject_id == subject_id)
        .order_by(Document.issue_date.desc())
    ).all()
    docs_by_folder: dict[int, list] = {}
    docs_no_folder = []
    for d in documents:
        (docs_by_folder.setdefault(d.folder_id, []) if d.folder_id else docs_no_folder).append(d)
    return templates.TemplateResponse(request, "subject_detail.html", {
        "subject": subject, "folders": folders,
        "docs_by_folder": docs_by_folder, "docs_no_folder": docs_no_folder,
    })


@app.post("/admin/subjects")
def create_subject(
    name: str = Form(...),
    birth_date: str = Form(""),
    db: Session = Depends(get_db),
):
    db.add(Subject(
        name=name.strip(),
        birth_date=date.fromisoformat(birth_date) if birth_date else None,
    ))
    db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.post("/admin/subjects/{subject_id}/rename")
def rename_subject(
    subject_id: int,
    name: str = Form(...),
    birth_date: str = Form(""),
    db: Session = Depends(get_db),
):
    subject = db.get(Subject, subject_id)
    if subject:
        subject.name = name.strip()
        subject.birth_date = date.fromisoformat(birth_date) if birth_date else None
        db.commit()
    return RedirectResponse(f"/admin/subjects/{subject_id}", status_code=303)


@app.post("/admin/subjects/{subject_id}/delete")
def delete_subject(subject_id: int, db: Session = Depends(get_db)):
    # не даём удалить субъекта, если на него ещё ссылаются документы —
    # иначе SQLite молча оставит висячие ссылки без предупреждения
    subject = db.get(Subject, subject_id)
    docs = db.query(Document).filter(Document.subject_id == subject_id).all()
    if subject and not docs:
        for folder in list(subject.folders):
            db.delete(folder)
        db.delete(subject)
        db.commit()
        return RedirectResponse("/admin", status_code=303)
    if docs:
        names = ", ".join(d.title for d in docs[:5])
        if len(docs) > 5:
            names += f" и ещё {len(docs) - 5}"
        error = f"Нельзя удалить: используется в документах — {names}"
        return RedirectResponse(
            f"/admin/subjects/{subject_id}?{urlencode({'error': error})}",
            status_code=303,
        )
    return RedirectResponse(f"/admin/subjects/{subject_id}", status_code=303)


@app.post("/admin/subjects/{subject_id}/folders")
def create_folder(subject_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    db.add(Folder(subject_id=subject_id, name=name.strip()))
    db.commit()
    return RedirectResponse(f"/admin/subjects/{subject_id}", status_code=303)


@app.post("/admin/folders/{folder_id}/delete")
def delete_folder(folder_id: int, db: Session = Depends(get_db)):
    folder = db.get(Folder, folder_id)
    if folder:
        subject_id = folder.subject_id
        # документы не теряем — просто выпадают из папки в "без папки"
        db.query(Document).filter(Document.folder_id == folder_id).update(
            {"folder_id": None}
        )
        db.delete(folder)
        db.commit()
        return RedirectResponse(f"/admin/subjects/{subject_id}", status_code=303)
    return RedirectResponse("/admin", status_code=303)


# ---------- Категории ----------

@app.get("/admin/categories")
def categories_page(request: Request, db: Session = Depends(get_db)):
    categories = db.scalars(select(Category)).all()
    return templates.TemplateResponse(request, "categories.html", {
        "categories": categories,
    })


@app.post("/admin/categories")
def create_category(name: str = Form(...), db: Session = Depends(get_db)):
    db.add(Category(name=name.strip()))
    db.commit()
    return RedirectResponse("/admin/categories", status_code=303)


@app.post("/admin/categories/{category_id}/rename")
def rename_category(category_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    category = db.get(Category, category_id)
    if category:
        category.name = name.strip()
        db.commit()
    return RedirectResponse("/admin/categories", status_code=303)


@app.post("/admin/categories/{category_id}/delete")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    category = db.get(Category, category_id)
    docs = db.query(Document).filter(Document.category_id == category_id).all()
    if category and not docs:
        db.delete(category)
        db.commit()
        return RedirectResponse("/admin/categories", status_code=303)
    if docs:
        names = ", ".join(d.title for d in docs[:5])
        if len(docs) > 5:
            names += f" и ещё {len(docs) - 5}"
        error = f"Нельзя удалить: используется в документах — {names}"
        return RedirectResponse(
            f"/admin/categories?{urlencode({'error': error})}", status_code=303
        )
    return RedirectResponse("/admin/categories", status_code=303)


# ---------- Документы ----------

@app.get("/admin/documents")
def documents_page(
    request: Request,
    subject_id: Optional[str] = None,
    category_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    # селект с пустым значением шлёт "" в query, а не отсутствие параметра —
    # поэтому принимаем как строку и сами решаем, парсить её или нет
    subject_id_int = int(subject_id) if subject_id else None
    category_id_int = int(category_id) if category_id else None

    query = select(Document).order_by(Document.issue_date.desc())
    if subject_id_int:
        query = query.where(Document.subject_id == subject_id_int)
    if category_id_int:
        query = query.where(Document.category_id == category_id_int)
    documents = db.scalars(query).all()
    return templates.TemplateResponse(request, "documents_list.html", {
        "documents": documents,
        "subjects": db.scalars(select(Subject)).all(),
        "categories": db.scalars(select(Category)).all(),
        "selected_subject": subject_id_int, "selected_category": category_id_int,
    })


@app.get("/admin/documents/new")
def new_document_form(
    request: Request,
    subject_id: Optional[int] = None,
    folder_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse(request, "document_form.html", {
        "doc": None,
        "preselect_subject_id": subject_id,
        "preselect_folder_id": folder_id,
        "subjects": db.scalars(select(Subject)).all(),
        "categories": db.scalars(select(Category)).all(),
        "folders": db.scalars(select(Folder)).all(),
    })


@app.get("/admin/documents/{doc_id}/edit")
def edit_document_form(doc_id: int, request: Request, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    return templates.TemplateResponse(request, "document_form.html", {
        "doc": doc,
        "preselect_subject_id": None,
        "preselect_folder_id": None,
        "subjects": db.scalars(select(Subject)).all(),
        "categories": db.scalars(select(Category)).all(),
        "folders": db.scalars(select(Folder)).all(),
    })


def _parsed_fields(
    subject_id, category_id, folder_id, title, series, number, issued_by, extra_number,
    issue_date, valid_from, valid_until, notify_before_expiry, notify_period,
    is_primary, drive_link,
):
    """Общий разбор полей формы для создания и правки документа."""
    return dict(
        subject_id=subject_id,
        category_id=category_id,
        folder_id=int(folder_id) if folder_id else None,
        title=title.strip(),
        series=series.strip() or None,
        number=number.strip() or None,
        issued_by=issued_by.strip() or None,
        extra_number=extra_number.strip() or None,
        issue_date=date.fromisoformat(issue_date) if issue_date else None,
        valid_from=date.fromisoformat(valid_from) if valid_from else None,
        valid_until=date.fromisoformat(valid_until) if valid_until else None,
        notify_before_expiry=notify_before_expiry,
        notify_period=notify_period or None,
        is_primary=is_primary,
        drive_link=drive_link.strip(),
        drive_file_id=parse_drive_file_id(drive_link),
    )


@app.post("/admin/documents")
def create_document(
    subject_id: int = Form(...),
    category_id: int = Form(...),
    folder_id: str = Form(""),
    title: str = Form(...),
    series: str = Form(""),
    number: str = Form(""),
    issued_by: str = Form(""),
    extra_number: str = Form(""),
    issue_date: str = Form(""),
    valid_from: str = Form(""),
    valid_until: str = Form(""),
    notify_before_expiry: bool = Form(False),
    notify_period: str = Form(""),
    is_primary: bool = Form(False),
    drive_link: str = Form(...),
    db: Session = Depends(get_db),
):
    fields = _parsed_fields(
        subject_id, category_id, folder_id, title, series, number, issued_by, extra_number,
        issue_date, valid_from, valid_until, notify_before_expiry, notify_period,
        is_primary, drive_link,
    )
    db.add(Document(**fields))
    db.commit()
    return RedirectResponse(f"/admin/subjects/{fields['subject_id']}", status_code=303)


@app.post("/admin/documents/{doc_id}")
def update_document(
    doc_id: int,
    subject_id: int = Form(...),
    category_id: int = Form(...),
    folder_id: str = Form(""),
    title: str = Form(...),
    series: str = Form(""),
    number: str = Form(""),
    issued_by: str = Form(""),
    extra_number: str = Form(""),
    issue_date: str = Form(""),
    valid_from: str = Form(""),
    valid_until: str = Form(""),
    notify_before_expiry: bool = Form(False),
    notify_period: str = Form(""),
    is_primary: bool = Form(False),
    drive_link: str = Form(...),
    db: Session = Depends(get_db),
):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    fields = _parsed_fields(
        subject_id, category_id, folder_id, title, series, number, issued_by, extra_number,
        issue_date, valid_from, valid_until, notify_before_expiry, notify_period,
        is_primary, drive_link,
    )
    for key, value in fields.items():
        setattr(doc, key, value)
    db.commit()
    return RedirectResponse(f"/admin/subjects/{doc.subject_id}", status_code=303)


@app.post("/admin/documents/{doc_id}/delete")
def delete_document(doc_id: int, request: Request, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if doc:
        db.delete(doc)
        db.commit()
    # удаляют и со страницы субъекта, и из общего списка — возвращаем туда, откуда пришли
    return RedirectResponse(
        request.headers.get("referer", "/admin/documents"), status_code=303
    )


@app.get("/files/{doc_id}")
def download_file(
    doc_id: int, exp: int, token: str, db: Session = Depends(get_db)
):
    """Отдаёт файл из Google Drive по подписанной ссылке (без initData —
    её не умеет слать ни Telegram.WebApp.downloadFile, ни sendDocument)."""
    if not verify_download_token(doc_id, exp, token):
        raise HTTPException(403, "Ссылка недействительна или истекла")

    doc = db.get(Document, doc_id)
    if not doc or not doc.drive_file_id:
        raise HTTPException(404, "Файл не найден")

    meta = get_file_metadata(doc.drive_file_id)
    filename = build_download_filename(doc, meta.get("name", ""), meta.get("mimeType", ""))

    headers = {
        "Content-Disposition": content_disposition(filename),
        "Access-Control-Allow-Origin": "https://web.telegram.org",
    }
    if meta.get("size"):
        headers["Content-Length"] = str(meta["size"])

    return StreamingResponse(
        stream_file_chunks(doc.drive_file_id),
        media_type=meta.get("mimeType", "application/octet-stream"),
        headers=headers,
    )


# ---------- Карточка документа ----------

EDITABLE_DOC_FIELDS = {
    "series", "number", "issued_by", "extra_number",
    "issue_date", "valid_from", "valid_until",
}
_DATE_FIELDS = {"issue_date", "valid_from", "valid_until"}


@app.get("/admin/documents/{doc_id}")
def document_detail_page(doc_id: int, request: Request, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    return templates.TemplateResponse(request, "document_detail.html", {"doc": doc})


@app.post("/admin/documents/{doc_id}/field")
def update_document_field(
    doc_id: int, field: str = Form(...), value: str = Form(""),
    db: Session = Depends(get_db),
):
    if field not in EDITABLE_DOC_FIELDS:
        raise HTTPException(400, "Это поле нельзя редактировать так — только через полную форму")
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Документ не найден")
    if field in _DATE_FIELDS:
        setattr(doc, field, date.fromisoformat(value) if value else None)
    else:
        setattr(doc, field, value.strip() or None)
    db.commit()
    return RedirectResponse(f"/admin/documents/{doc_id}", status_code=303)


@app.get("/admin/documents/{doc_id}/download")
def admin_download_document(doc_id: int, db: Session = Depends(get_db)):
    """В админке отдельный токен не нужен — весь /admin и так под Basic Auth."""
    doc = db.get(Document, doc_id)
    if not doc or not doc.drive_file_id:
        raise HTTPException(404, "Файл не найден или ссылка на Drive не задана")
    meta = get_file_metadata(doc.drive_file_id)
    filename = build_download_filename(doc, meta.get("name", ""), meta.get("mimeType", ""))
    headers = {"Content-Disposition": content_disposition(filename)}
    if meta.get("size"):
        headers["Content-Length"] = str(meta["size"])
    return StreamingResponse(
        stream_file_chunks(doc.drive_file_id),
        media_type=meta.get("mimeType", "application/octet-stream"),
        headers=headers,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
