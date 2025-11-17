from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Body
from sqlalchemy.orm import Session, aliased, joinedload
from sqlalchemy import and_, exists, not_
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from .. import models, database, auth
from .ws_manager import manager
from fastapi.responses import FileResponse
from pydantic import BaseModel
import asyncio
import os, shutil
from typing import List

# ============================================
# WIB TIMEZONE HELPER
# ============================================
WIB = timezone(timedelta(hours=7))

def to_wib(dt: datetime):
    if dt is None:
        return None
    if dt.tzinfo is None:  # anggap UTC kalau tanpa tzinfo
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(WIB).strftime("%Y-%m-%d %H:%M:%S")


# ============================================
# ROUTER & DIR
# ============================================
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter(
    prefix="/documents",
    tags=["Documents Dashboard"]
)


# ============================================================
# DOCUMENT → DICT (Sudah convert waktu ke WIB)
# ============================================================
def doc_to_dict(doc: models.Document, current_user_id: int):

    # ---------- FILES LIST ----------
    files_list = []
    for f in doc.files:
        if f.is_deleted:
            continue

        files_list.append({
            "id": f.id,
            "filename": f.filename,
            "path": f.path,
            "is_stamped": ("stamped_" in f.filename) or ("rejected_" in f.filename),
            "download_url": f"/documents/{doc.id}/file/{f.id}",
        })

    if not files_list:
        files_list = [{"message": "Tidak ada File yang Dilampirkan"}]

    # ---------- LAST STAMPED FILE ----------
    stamped_candidates = [
        f for f in doc.files
        if ("stamped_" in f.filename) or ("rejected_" in f.filename)
    ]
    stamped_file_path = stamped_candidates[-1].path if stamped_candidates else "<Belum Full Approved/Reject>"

    # ---------- RECIPIENT STATUS ----------
    recipient_for_user = next(
        (r for r in doc.recipients if r.user_id == current_user_id),
        None
    )
    is_read = recipient_for_user.is_read if recipient_for_user else False

    # ---------- UNREAD LOGIC ----------
    unread_inbox = recipient_for_user and not recipient_for_user.is_read

    unread_approval = any(
        (hasattr(a, "has_read") and
         a.user_id == current_user_id and
         a.status == models.StatusEnum.waiting and
         not a.has_read)
        for a in doc.approvers
    )

    unread = unread_inbox or unread_approval

    # ---------- RETURN ----------
    return {
        "id": doc.id,
        "no_surat": doc.no_surat,
        "title": doc.title,
        "content": doc.content,
        "status": doc.status.value if hasattr(doc.status, "value") else doc.status,
        "creator": doc.creator.name if doc.creator else None,
        "created_at": to_wib(doc.created_at),

        "approvers": [
            {
                "user": a.user.name,
                "status": a.status.value if hasattr(a.status, "value") else a.status,
                "seq_index": a.seq_index,
                "waktu": to_wib(a.waktu),
            }
            for a in doc.approvers
        ],

        "recipients": [r.user.name for r in doc.recipients],

        "files": files_list,
        "stamped_pdf": stamped_file_path,

        "is_read": is_read,
        "unread": unread,
    }


# ============================================================
# DASHBOARD
# ============================================================
@router.get("/dashboard")
def get_dashboard(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    user_id = current_user.id

    A1 = aliased(models.Approver)
    A2 = aliased(models.Approver)

    approved_by_me = (
        db.query(models.Document)
        .join(models.Approver)
        .options(
            joinedload(models.Document.creator),
            joinedload(models.Document.approvers).joinedload(models.Approver.user),
            joinedload(models.Document.recipients).joinedload(models.Recipient.user),
            joinedload(models.Document.files)
        )
        .filter(
            models.Approver.user_id == user_id,
            models.Approver.status == models.StatusEnum.approved,
            models.Document.is_deleted == False
        ).all()
    )

    my_finalized = (
        db.query(models.Document)
        .options(
            joinedload(models.Document.creator),
            joinedload(models.Document.approvers).joinedload(models.Approver.user),
            joinedload(models.Document.recipients).joinedload(models.Recipient.user),
            joinedload(models.Document.files)
        )
        .filter(
            models.Document.creator_id == user_id,
            models.Document.is_deleted == False,
            models.Document.status.in_([models.StatusEnum.approved, models.StatusEnum.rejected])
        ).all()
    )

    pending_but_waiting = (
        db.query(models.Document)
        .join(A1)
        .options(
            joinedload(models.Document.creator),
            joinedload(models.Document.approvers).joinedload(models.Approver.user),
            joinedload(models.Document.recipients).joinedload(models.Recipient.user),
            joinedload(models.Document.files)
        )
        .filter(
            A1.user_id == user_id,
            A1.status == models.StatusEnum.waiting,
            models.Document.is_deleted == False,
            exists().where(
                and_(
                    A2.document_id == A1.document_id,
                    A2.seq_index < A1.seq_index,
                    A2.status != models.StatusEnum.approved
                )
            )
        ).all()
    )

    ready_to_approve = (
        db.query(models.Document)
        .join(A1)
        .options(
            joinedload(models.Document.creator),
            joinedload(models.Document.approvers).joinedload(models.Approver.user),
            joinedload(models.Document.recipients).joinedload(models.Recipient.user),
            joinedload(models.Document.files)
        )
        .filter(
            A1.user_id == user_id,
            A1.status == models.StatusEnum.waiting,
            models.Document.is_deleted == False,
            not_(
                exists().where(
                    and_(
                        A2.document_id == A1.document_id,
                        A2.seq_index < A1.seq_index,
                        A2.status != models.StatusEnum.approved
                    )
                )
            )
        ).all()
    )

    inbox = (
        db.query(models.Document)
        .join(models.Recipient)
        .options(
            joinedload(models.Document.creator),
            joinedload(models.Document.approvers).joinedload(models.Approver.user),
            joinedload(models.Document.recipients).joinedload(models.Recipient.user),
            joinedload(models.Document.files)
        )
        .filter(
            models.Recipient.user_id == user_id,
            models.Recipient.is_deleted == False,
            models.Document.is_deleted == False
        ).all()
    )

    return {
        "approved_by_me": [doc_to_dict(d, user_id) for d in approved_by_me],
        "my_finalized": [doc_to_dict(d, user_id) for d in my_finalized],
        "pending_but_waiting": [doc_to_dict(d, user_id) for d in pending_but_waiting],
        "ready_to_approve": [doc_to_dict(d, user_id) for d in ready_to_approve],
        "inbox": [doc_to_dict(d, user_id) for d in inbox],
    }


# ============================================================
# DELETE FROM INBOX
# ============================================================
@router.delete("/inbox/{document_id}")
def delete_from_inbox(
    document_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    recipient = db.query(models.Recipient).filter(
        models.Recipient.document_id == document_id,
        models.Recipient.user_id == current_user.id,
        models.Recipient.is_deleted == False
    ).first()

    if not recipient:
        raise HTTPException(status_code=404, detail="Document not found in your inbox")

    recipient.is_deleted = True
    db.commit()
    return {"message": "Document removed from inbox successfully"}


# ============================================================
# DELETE FROM SENT
# ============================================================
@router.delete("/sent/{document_id}")
def delete_from_sent(
    document_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(
        models.Document.id == document_id,
        models.Document.creator_id == current_user.id,
        models.Document.is_deleted == False
    ).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found in your sent items")

    doc.is_deleted = True
    db.commit()
    return {"message": "Document deleted successfully from sent items"}


# ============================================================
# REVISE DOCUMENT
# ============================================================
class DocumentUpdate(BaseModel):
    title: str
    content: str

@router.put("/{document_id}/revise")
def revise_document(
    document_id: int,
    request: DocumentUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(
        models.Document.id == document_id,
        models.Document.creator_id == current_user.id
    ).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found or not yours")

    if doc.status != models.StatusEnum.revise:
        raise HTTPException(status_code=400, detail="Document is not in revise mode")

    doc.title = request.title
    doc.content = request.content
    doc.status = models.StatusEnum.waiting
    doc.current_index = 0
    doc.created_at = datetime.utcnow().replace(tzinfo=timezone.utc)

    for a in doc.approvers:
        a.status = models.StatusEnum.waiting
        a.waktu = None
        a.catatan = None

    db.commit()
    db.refresh(doc)

    return {"message": "Document revised and resubmitted for approval"}


@router.put("/{document_id}/revise/upload")
def revise_upload_file(
    document_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(
        models.Document.id == document_id,
        models.Document.creator_id == current_user.id
    ).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found or not yours")
    if doc.status != models.StatusEnum.revise:
        raise HTTPException(status_code=400, detail="Document is not in revise mode")

    for f in doc.files:
        f.is_deleted = True

    filename = f"{uuid4()}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    new_file = models.File(document_id=doc.id, filename=file.filename, path=filepath)
    db.add(new_file)

    doc.status = models.StatusEnum.waiting
    db.commit()

    return {"message": "Revised file uploaded and document resubmitted for approval"}


# ============================================================
# TRASH FILES
# ============================================================
@router.get("/trash/files")
def get_deleted_files(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    deleted_files = (
        db.query(models.File)
        .join(models.Document)
        .join(models.Recipient)
        .filter(
            models.File.is_deleted == True,
            (
                (models.Recipient.user_id == current_user.id) |
                (models.Document.creator_id == current_user.id)
            )
        )
        .all()
    )

    return [
        {
            "id": f.id,
            "document_id": f.document_id,
            "filename": f.filename,
            "path": f.path,
            "created_at": to_wib(f.created_at)
        }
        for f in deleted_files
    ]


# ============================================================
# WAITING DOCUMENTS
# ============================================================
@router.get("/waiting", response_model=List[dict])
def get_waiting_documents(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    waiting_docs = (
        db.query(models.Document)
        .join(models.Approver)
        .filter(models.Approver.user_id == current_user.id)
        .filter(models.Approver.status == models.StatusEnum.waiting)
        .all()
    )

    result = []
    for doc in waiting_docs:
        result.append({
            "id": doc.id,
            "no_surat": doc.no_surat,
            "title": doc.title,
            "status": "Menunggu Persetujuan",
            "content": doc.content,
            "created_at": to_wib(doc.created_at),
            "approvers": [{"user_id": a.user_id, "name": a.user.name} for a in doc.approvers],
            "recipients": [{"user_id": r.user_id, "name": r.user.name} for r in doc.recipients],
        })

    return result


# ============================================================
# DOWNLOAD STAMPED PDF
# ============================================================
@router.get("/{document_id}/stamped")
def download_stamped_pdf(
    document_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    allowed_users = (
        [doc.creator_id] +
        [a.user_id for a in doc.approvers] +
        [r.user_id for r in doc.recipients]
    )

    if current_user.id not in allowed_users:
        raise HTTPException(status_code=403, detail="You don't have access to this document")

    stamped_files = [f for f in doc.files if "stamped_" in f.filename or "rejected_" in f.filename]
    if not stamped_files:
        raise HTTPException(status_code=404, detail="Stamped PDF not found")

    stamped_file = stamped_files[-1]

    if not os.path.exists(stamped_file.path):
        raise HTTPException(status_code=404, detail="Stamped PDF file not found on server")

    return FileResponse(
        path=stamped_file.path,
        filename=stamped_file.filename,
        media_type="application/pdf"
    )


# ============================================================
# DOWNLOAD FILE
# ============================================================
@router.get("/{document_id}/file/{file_id}")
def download_file(
    document_id: int,
    file_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    file = db.query(models.File).filter(
        models.File.id == file_id,
        models.File.document_id == document_id,
        models.File.is_deleted == False
    ).first()

    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    doc = db.query(models.Document).filter(models.Document.id == document_id).first()

    allowed_users = (
        [doc.creator_id] +
        [a.user_id for a in doc.approvers] +
        [r.user_id for r in doc.recipients]
    )

    if current_user.id not in allowed_users:
        raise HTTPException(status_code=403, detail="Not allowed")

    if not os.path.exists(file.path):
        raise HTTPException(status_code=404, detail="File missing on server")

    return FileResponse(file.path, filename=file.filename)


# ============================================================
# SET DOCUMENT TO REVISE
# ============================================================
class SetReviseStatus(BaseModel):
    reason: str = None

@router.put("/{document_id}/set-revise")
def set_document_revise(
    document_id: int,
    request: SetReviseStatus = Body(...),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(
        models.Document.id == document_id,
        models.Document.creator_id == current_user.id,
        models.Document.is_deleted == False
    ).first()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found or not yours")

    doc.status = models.StatusEnum.revise
    doc.created_at = datetime.utcnow().replace(tzinfo=timezone.utc)

    if request.reason:
        for a in doc.approvers:
            a.catatan = request.reason

    db.commit()
    db.refresh(doc)

    return {"message": "Document status set to REVISE"}


# ============================================================
# MARK READ
# ============================================================
@router.patch("/{document_id}/read")
async def mark_inbox_read(
    document_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    recipient = (
        db.query(models.Recipient)
        .filter(
            models.Recipient.document_id == document_id,
            models.Recipient.user_id == current_user.id
        ).first()
    )

    if not recipient:
        return {"message": "Not a recipient or not found"}

    if not recipient.is_read:
        recipient.is_read = True
        db.commit()

        category = "inbox" if recipient.type == "INBOX" else "waiting"

        asyncio.create_task(manager.broadcast({
            "type": "update_read",
            "document_id": document_id,
            "user_id": current_user.id,
            "category": category
        }))

    return {"message": "Marked as read"}


# ============================================================
# NEW DOC → NOTIF
# ============================================================
@router.post("/{doc_id}/new")
async def create_doc(doc_id: int, db: Session = Depends(database.get_db)):

    recipients = db.query(models.Recipient).filter(
        models.Recipient.document_id == doc_id
    ).all()

    for r in recipients:
        await manager.broadcast({
            "type": "new_inbox",
            "doc_id": doc_id,
            "user_id": r.user_id
        })

    return {"status": "ok"}


@router.post("/{doc_id}/waiting")
async def add_waiting(doc_id: int, db: Session = Depends(database.get_db)):
    approvers = db.query(models.WaitingApproval).filter(
        models.WaitingApproval.document_id == doc_id
    ).all()

    for a in approvers:
        await manager.broadcast({
            "type": "new_waiting",
            "doc_id": doc_id,
            "user_id": a.user_id
        })

    return {"status": "waiting_sent"}


# ============================================================
# GET UNREAD DOCS
# ============================================================
@router.get("/unread")
def get_unread_documents(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):

    inbox_docs = (
        db.query(models.Document)
        .join(models.Recipient)
        .filter(models.Recipient.user_id == current_user.id)
        .filter(models.Recipient.is_read == False)
        .all()
    )

    waiting_docs = (
        db.query(models.Document)
        .join(models.Approver)
        .filter(models.Approver.user_id == current_user.id)
        .filter(models.Approver.status == models.StatusEnum.waiting)
        .filter(
            (models.Approver.has_read == False) |
            (models.Approver.has_read.is_(None))
        )
        .all()
    )

    format_doc = lambda d, type_: {
        "id": d.id,
        "title": d.title,
        "type": type_,
        "created_at": to_wib(d.created_at),
    }

    return {
        "inbox": [format_doc(d, "inbox") for d in inbox_docs],
        "waiting": [format_doc(d, "waiting") for d in waiting_docs],
    }
