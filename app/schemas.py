from pydantic import BaseModel, EmailStr, HttpUrl
from typing import List, Optional
from datetime import datetime
from enum import Enum

# ================= STATUS ENUM =================
class StatusEnum(str, Enum):
    waiting = "Menunggu Persetujuan"
    approved = "Disetujui"
    rejected = "Ditolak"
    revise = "Revisi"


# ================= USER SCHEMAS =================
class UserBase(BaseModel):
    email: EmailStr
    name: str
    phone_number: Optional[str] = None       # ✅ Tambahan nomor telepon
    avatar: Optional[str] = None             # ✅ URL/path foto profil


class UserCreate(UserBase):
    password: str


class UserOut(UserBase):
    id: int
    created_at: Optional[datetime] = None

    class Config:
        orm_mode = True


# ================= APPROVER SCHEMAS =================
class ApproverOut(BaseModel):
    user_id: int
    seq_index: int
    status: StatusEnum
    waktu: Optional[datetime]
    catatan: Optional[str]

    class Config:
        orm_mode = True


# ================= RECIPIENT SCHEMAS =================
class RecipientOut(BaseModel):
    user_id: int

    class Config:
        orm_mode = True


# ================= FILE SCHEMAS =================
class FileOut(BaseModel):
    id: int
    filename: str
    path: str

    class Config:
        orm_mode = True


# ================= DOCUMENT SCHEMAS =================
class DocumentCreate(BaseModel):
    no_surat: str
    title: str
    content: Optional[str] = None
    approvers: List[int]  # daftar user_id approver
    recipients: List[int]


class DocumentOut(BaseModel):
    id: int
    no_surat: str
    title: str
    status: StatusEnum
    created_at: datetime
    approvers: List[ApproverOut]
    recipients: Optional[List[RecipientOut]] = []
    files: Optional[List[FileOut]] = []

    class Config:
        orm_mode = True
