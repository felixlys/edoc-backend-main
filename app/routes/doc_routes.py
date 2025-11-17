from typing import List, Optional
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from sqlalchemy.orm import Session
import os, shutil
from datetime import datetime
from uuid import uuid4
from sqlalchemy.orm import Session
from .ws_manager import manager
from .. import schemas
from pydantic import BaseModel
from .. import models, database, auth, pdf_stamp

router = APIRouter()
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def add_approvers(db: Session, document_id: int, user_ids: List[int]):
    for i, user_id in enumerate(user_ids):
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"Approver user_id {user_id} not found")

        db.add(models.Approver(
            document_id=document_id,
            user_id=user_id,
            seq_index=i,
            status=models.StatusEnum.waiting
        ))


def add_recipients(db: Session, document_id: int, user_ids: List[int]):
    for user_id in user_ids:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"Recipient user_id {user_id} not found")

        db.add(models.Recipient(document_id=document_id, user_id=user_id))


# ---------------------------------------------------------------------------
# Create Document
# ---------------------------------------------------------------------------
class DocumentCreate(BaseModel):
    no_surat: str
    title: str
    content: str


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_document(
    request: DocumentCreate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    if db.query(models.Document).filter(models.Document.no_surat == request.no_surat).first():
        raise HTTPException(status_code=400, detail="Document with this no_surat already exists")

    doc = models.Document(
        no_surat=request.no_surat,
        title=request.title,
        content=request.content,
        status=models.StatusEnum.waiting,
        creator_id=current_user.id
    )

    db.add(doc)
    db.commit()
    db.refresh(doc)

    # 🔥 BROADCAST DOKUMEN BARU
    await manager.broadcast({
        "event": "document_created",
        "document_id": doc.id,
        "title": doc.title,
        "creator_id": current_user.id
    })

    return {"message": "Document created successfully", "doc_id": doc.id}



# ---------------------------------------------------------------------------
# Upload File
# ---------------------------------------------------------------------------
@router.post("/{document_id}/upload")
def upload_file(
    document_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    filename = f"{uuid4()}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    new_file = models.File(
        document_id=document_id,
        filename=file.filename,
        path=filepath
    )

    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    return {"message": "File uploaded successfully", "file_id": new_file.id}


# ---------------------------------------------------------------------------
# Assign Approver & Recipient
# ---------------------------------------------------------------------------
class AssignParticipants(BaseModel):
    approver_ids: Optional[List[int]] = None
    recipient_ids: Optional[List[int]] = None


@router.post("/{document_id}/assign")
async def assign_participants(
    document_id: int,
    request: AssignParticipants,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if request.approver_ids:
        add_approvers(db, document_id, request.approver_ids)

    if request.recipient_ids:
        add_recipients(db, document_id, request.recipient_ids)

    db.commit()

    # 🔥 BROADCAST KE SEMUA USER YANG TERKAIT
    await manager.broadcast({
        "event": "document_assigned",
        "document_id": document_id,
        "approver_ids": request.approver_ids,
        "recipient_ids": request.recipient_ids
    })

    return {"message": "Participants assigned successfully"}



# ---------------------------------------------------------------------------
# GET DETAIL DOKUMEN (untuk frontend DocumentDetail & Edit)
# ---------------------------------------------------------------------------
@router.get("/{doc_id}")
def get_document_detail(
    doc_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "id": doc.id,
        "no_surat": doc.no_surat,
        "title": doc.title,
        "content": doc.content,
        "status": doc.status,
        "is_creator": doc.creator_id == current_user.id,
        "approvers": [
            {
                "user_id": a.user_id,
                "name": a.user.name,
                "status": a.status,
                "catatan": a.catatan,
                "seq_index": a.seq_index,
            }
            for a in doc.approvers
        ],
        "recipients": [
            {"user_id": r.user_id, "name": r.user.name}
            for r in doc.recipients
        ],
        "files": [
            {"id": f.id, "filename": f.filename, "path": f.path}
            for f in doc.files
        ]
    }


# ---------------------------------------------------------------------------
# APPROVE DOCUMENT
# ---------------------------------------------------------------------------
@router.post("/{doc_id}/approve")
async def approve_document(
    doc_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    approver = db.query(models.Approver).filter(
        models.Approver.document_id == doc_id,
        models.Approver.user_id == current_user.id
    ).first()

    if not approver:
        raise HTTPException(status_code=403, detail="You are not an approver")

    if approver.status != models.StatusEnum.waiting:
        raise HTTPException(status_code=400, detail="Already acted")

    # cek urutan
    previous = db.query(models.Approver).filter(
        models.Approver.document_id == doc_id,
        models.Approver.seq_index < approver.seq_index
    ).all()

    for p in previous:
        if p.status != models.StatusEnum.approved:
            raise HTTPException(
                status_code=400,
                detail=f"Waiting approval from {p.user.name}"
            )

    # approve
    approver.status = models.StatusEnum.approved
    approver.waktu = datetime.utcnow()
    db.commit()

    # cek final approve
    if all(a.status == models.StatusEnum.approved for a in doc.approvers):
        doc.status = models.StatusEnum.approved
        db.commit()

        # stamping
        if doc.files:
            src = doc.files[0].path
            out_dir = "approved_docs"
            os.makedirs(out_dir, exist_ok=True)

            out = os.path.join(out_dir, f"stamped_{os.path.basename(src)}")

            pdf_stamp.add_stamp_to_pdf(src, out, {
                "no_surat": doc.no_surat,
                "creator_name": doc.creator.name,
                "timestamps": {"creator": doc.created_at.strftime("%Y-%m-%d %H:%M:%S")},
                "approvers": [
                    {
                        "name": a.user.name,
                        "waktu": a.waktu.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    for a in doc.approvers if a.status == models.StatusEnum.approved
                ],
                "rejected": None
            })

            new_file = models.File(
                document_id=doc.id,
                filename=os.path.basename(out),
                path=out
            )
            db.add(new_file)
            db.commit()

    # 🔥🔥 TAMBAHAN: BROADCAST REALTIME (TIDAK MENGUBAH LOGIKA)
    await manager.broadcast({
        "event": "approval_status_changed",
        "document_id": doc_id,
        "user_id": current_user.id,
        "status": "approved"
    })

    return {"message": "Document approved successfully"}



# ---------------------------------------------------------------------------
# REJECT DOCUMENT (✅ FIX: JSON body)
# ---------------------------------------------------------------------------
class RejectRequest(BaseModel):
    reason: str


@router.post("/{doc_id}/reject")
def reject_document(
    doc_id: int,
    request: RejectRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    reason = request.reason

    doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    approver = db.query(models.Approver).filter(
        models.Approver.document_id == doc_id,
        models.Approver.user_id == current_user.id
    ).first()

    if not approver:
        raise HTTPException(status_code=403, detail="You are not an approver")

    if approver.status != models.StatusEnum.waiting:
        raise HTTPException(status_code=400, detail="Already acted")

    approver.status = models.StatusEnum.rejected
    approver.catatan = reason
    approver.waktu = datetime.utcnow()
    doc.status = models.StatusEnum.rejected

    db.commit()

    # stamping reject
    if doc.files:
        src = doc.files[0].path
        out_dir = "approved_docs"
        os.makedirs(out_dir, exist_ok=True)

        out = os.path.join(out_dir, f"rejected_{os.path.basename(src)}")

        pdf_stamp.add_stamp_to_pdf(src, out, {
            "no_surat": doc.no_surat,
            "creator_name": doc.creator.name,
            "timestamps": {"creator": doc.created_at.strftime("%Y-%m-%d %H:%M:%S")},
            "approvers": [],
            "rejected": {
                "name": current_user.name,
                "waktu": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            }
        })

        new_file = models.File(
            document_id=doc.id,
            filename=os.path.basename(out),
            path=out
        )
        db.add(new_file)
        db.commit()

    return {"message": "Document rejected successfully"}


# ---------------------------------------------------------------------------
# REVISE DOCUMENT (✅ FIX: JSON body)
# ---------------------------------------------------------------------------
class ReviseRequest(BaseModel):
    note: str


@router.post("/{doc_id}/revise")
def revise_document(
    doc_id: int,
    request: ReviseRequest,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    note = request.note

    doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    approver = db.query(models.Approver).filter(
        models.Approver.document_id == doc_id,
        models.Approver.user_id == current_user.id
    ).first()
    if not approver:
        raise HTTPException(status_code=403, detail="You are not an approver")

    if approver.status != models.StatusEnum.waiting:
        raise HTTPException(status_code=400, detail="Already acted")

    approver.status = models.StatusEnum.revise
    approver.catatan = note
    approver.waktu = datetime.utcnow()
    doc.status = models.StatusEnum.revise

    db.commit()
    return {"message": "Document sent back for revision"}


# ---------------------------------------------------------------------------
# Upload File Revisi (Creator Only)  ✅ DIPAKAI FRONTEND
# ---------------------------------------------------------------------------
@router.put("/{doc_id}/revise/upload")
def upload_revised_file(
    doc_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only creator can upload revised file")

    if doc.status != models.StatusEnum.revise:
        raise HTTPException(status_code=400, detail="Document is not in revision state")

    # upload
    filename = f"{uuid4()}_{file.filename}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # simpan sebagai file baru
    new_file = models.File(
        document_id=doc.id,
        filename=file.filename,
        path=filepath
    )
    db.add(new_file)
    db.commit()

    return {"message": "Revised file uploaded successfully"}


# ---------------------------------------------------------------------------
# Edit Metadata Dokumen
# ---------------------------------------------------------------------------
class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    no_surat: Optional[str] = None


@router.put("/{doc_id}/edit")
def edit_document(
    doc_id: int,
    request: DocumentUpdate,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only creator can edit")

    if doc.status != models.StatusEnum.revise:
        raise HTTPException(status_code=400, detail="Document not in revision state")

    # Update metadata
    if request.title:
        doc.title = request.title
    if request.content:
        doc.content = request.content
    if request.no_surat:
        doc.no_surat = request.no_surat

    # Reset approvers untuk review ulang
    for approver in doc.approvers:
        approver.status = models.StatusEnum.waiting
        approver.catatan = None
        approver.waktu = None

    # Kembali ke status menunggu approval
    doc.status = models.StatusEnum.waiting

    db.commit()
    db.refresh(doc)

    return {"message": "Document revised and resubmitted to first approver successfully"}

@router.get("/{doc_id}/reasons")
def get_document_reasons(
    doc_id: int,
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    """
    Mengambil catatan / alasan dari approvers untuk dokumen tertentu.
    """
    doc = db.query(models.Document).filter(models.Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    reasons = []
    for a in doc.approvers:
        if a.catatan:
            reasons.append({
                "user_id": a.user_id,
                "name": a.user.name,
                "status": a.status,
                "catatan": a.catatan,
                "waktu": a.waktu.strftime("%Y-%m-%d %H:%M:%S") if a.waktu else None
            })

    return {"doc_id": doc.id, "reasons": reasons}

