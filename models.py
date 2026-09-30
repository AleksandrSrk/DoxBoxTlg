from datetime import datetime, date
from sqlalchemy import String, Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Subject(Base):
    """Субъект: человек (Я, Жена, дети) или объект (Квартира, Kodiaq)."""
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    folders: Mapped[list["Folder"]] = relationship(back_populates="subject")
    documents: Mapped[list["Document"]] = relationship(back_populates="subject")


class Folder(Base):
    """Папка внутри субъекта, группирует связанные документы."""
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    subject: Mapped["Subject"] = relationship(back_populates="folders")
    documents: Mapped[list["Document"]] = relationship(back_populates="folder")


class Category(Base):
    """Сквозная категория-ярлык (Паспорт, СОР, СНИЛС...)."""
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    documents: Mapped[list["Document"]] = relationship(back_populates="category")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id"), nullable=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"))

    title: Mapped[str] = mapped_column(String(300))
    series: Mapped[str | None] = mapped_column(String(50), nullable=True)
    number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    issued_by: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # дата самого документа — по ней сортировка "самый свежий"
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    notify_before_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    # 'week' | 'month' | '2months' — один вариант, не мультивыбор
    notify_period: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # у одного субъекта в одной категории может быть несколько основных
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    drive_link: Mapped[str] = mapped_column(Text)
    drive_file_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    subject: Mapped["Subject"] = relationship(back_populates="documents")
    folder: Mapped["Folder | None"] = relationship(back_populates="documents")
    category: Mapped["Category"] = relationship(back_populates="documents")
