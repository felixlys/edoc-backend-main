from sqlalchemy import Column, Integer, String, Text, Enum, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy import Boolean
from datetime import datetime
from .database import Base
import enum

class StatusEnum(str, enum.Enum):
    waiting = "Menunggu Persetujuan"
    approved = "Disetujui"
    rejected = "Ditolak"
    revise = "Revisi"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    phone_number = Column(String(30), nullable=True)
    avatar = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # ✅ Kolom untuk sistem OTP & verifikasi
    otp_code = Column(String(6), nullable=True)           # Kode OTP 6 digit
    otp_expiry = Column(DateTime, nullable=True)          # Tanggal kedaluwarsa
    otp_purpose = Column(String(50), nullable=True)       # Tujuan OTP: "login", "update_profile", dll

    # ✅ Kolom sementara untuk update profil
    pending_name = Column(String(255), nullable=True)
    pending_phone = Column(String(30), nullable=True)
    reset_token = Column(String(128), nullable=True)
    reset_token_expiry = Column(DateTime, nullable=True)
    # ✅ Relasi ke dokumen
    created_docs = relationship("Document", back_populates="creator")
    
    
class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    no_surat = Column(String(50), unique=True)
    title = Column(String(512))
    content = Column(Text)
    creator_id = Column(Integer, ForeignKey("users.id"))
    current_index = Column(Integer, default=0)
    status = Column(Enum(StatusEnum), default=StatusEnum.waiting)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    creator = relationship("User", back_populates="created_docs")
    approvers = relationship("Approver", back_populates="document", cascade="all, delete")
    recipients = relationship("Recipient", back_populates="document", cascade="all, delete")
    files = relationship("File", back_populates="document", cascade="all, delete")

class Approver(Base):
    __tablename__ = "approvers"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    seq_index = Column(Integer)
    status = Column(Enum(StatusEnum), default=StatusEnum.waiting)
    waktu = Column(DateTime)
    catatan = Column(Text)
    is_read = Column(Boolean, default=False)
    document = relationship("Document", back_populates="approvers")
    user = relationship("User")
    has_read = Column(Boolean, default=False)

class Recipient(Base):
    __tablename__ = "recipients"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    document = relationship("Document", back_populates="recipients")
    is_deleted = Column(Boolean, default=False)
    user = relationship("User")
    is_read = Column(Boolean, default=False)


class File(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    filename = Column(String(512))
    path = Column(String(1024))
    is_deleted = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="files")
