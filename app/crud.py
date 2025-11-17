# app/crud.py
from sqlalchemy.orm import Session
from . import models, schemas
from datetime import datetime
from sqlalchemy import func


# ---------------- USER CRUD ---------------- #
def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()


def create_user(db: Session, email: str, name: str, password_hash: str):
    user = models.User(email=email, name=name, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_all_users(db: Session):
    return db.query(models.User).all()


# ---------------- DOCUMENT CRUD ---------------- #
def generate_no_surat(db: Session):
    """Generate sequential no_surat (auto increment format 0000000001)."""
    last_doc = db.query(models.Document).order_by(models.Document.id.desc()).first()
    if not last_doc or not last_doc.no_surat:
        return "0000000001"
    try:
        return str(int(last_doc.no_surat) + 1).zfill(10)
    except ValueError:
        return f"{last_doc.id+1:010d}"


def create_document(db: Session, title: str, content: str, creator_id: int):
    no_surat = generate_no_surat(db)
    new_doc = models.Document(
        no_surat=no_surat,
        title=title,
        content=content,
        creator_id=creator_id,
        status=models.StatusEnum.waiting,
        created_at=datetime.utcnow(),
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)
    return new_doc


def get_document(db: Session, doc_id: int):
    return db.query(models.Document).filter(models.Document.id == doc_id).first()


def get_documents_by_creator(db: Session, creator_id: int):
    return db.query(models.Document).filter(models.Document.creator_id == creator_id).all()


def get_documents_for_approver(db: Session, user_id: int):
    return (
        db.query(models.Document)
        .join(models.Approver)
        .filter(models.Approver.user_id == user_id)
        .all()
    )


def update_document_status(db: Session, doc_id: int, new_status: models.StatusEnum):
    doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
    if doc:
        doc.status = new_status
        db.commit()
        db.refresh(doc)
    return doc


# ---------------- APPROVER CRUD ---------------- #
def add_approvers(db: Session, doc_id: int, approver_ids: list[int]):
    for i, uid in enumerate(approver_ids):
        db_approver = models.Approver(
            document_id=doc_id, user_id=uid, seq_index=i, status=models.StatusEnum.waiting
        )
        db.add(db_approver)
    db.commit()


def update_approver_status(db: Session, approver_id: int, status: models.StatusEnum, note: str = None):
    approver = db.query(models.Approver).filter(models.Approver.id == approver_id).first()
    if approver:
        approver.status = status
        approver.waktu = datetime.utcnow()
        approver.catatan = note
        db.commit()
        db.refresh(approver)
    return approver


# ---------------- RECIPIENT CRUD ---------------- #
def add_recipients(db: Session, doc_id: int, recipient_ids: list[int]):
    for uid in recipient_ids:
        db_rec = models.Recipient(document_id=doc_id, user_id=uid)
        db.add(db_rec)
    db.commit()


# ---------------- FILE CRUD ---------------- #
def add_file(db: Session, doc_id: int, filename: str, path: str):
    file_rec = models.File(document_id=doc_id, filename=filename, path=path)
    db.add(file_rec)
    db.commit()
    db.refresh(file_rec)
    return file_rec


def get_files_by_document(db: Session, doc_id: int):
    return db.query(models.File).filter(models.File.document_id == doc_id).all()
