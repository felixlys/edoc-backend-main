from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.models import User
from datetime import timedelta, datetime
from .. import schemas, models, auth, database  # ✅ sudah benar (pakai relative import)
import os, shutil, random, string
from typing import Optional
import random, string, uuid
from passlib.context import CryptContext
from ..database import get_db
import requests

router = APIRouter()

FONNTE_TOKEN = "F5Bv76fRZrEzZUBSxPqJ"

def send_whatsapp_message(phone_number: str, message: str):
    """Kirim pesan WhatsApp lewat Fonnte API"""
    url = "https://api.fonnte.com/send"
    payload = {
        "target": phone_number,
        "message": message
    }
    headers = {
        "Authorization": FONNTE_TOKEN
    }
    try:
        r = requests.post(url, data=payload, headers=headers, timeout=10)
        print("✅ WhatsApp sent:", r.text)
    except Exception as e:
        print("❌ Gagal kirim WA:", e)
        
def gen_token(length=48):
    return uuid.uuid4().hex + "".join(random.choices(string.ascii_letters + string.digits, k=max(0, length-32)))

@router.post("/register", response_model=schemas.UserOut)
def register(
  name: str = Form(...),
  email: str = Form(...),
  password: str = Form(...),
  phone_number: str = Form(...),
  avatar: UploadFile = File(None),
  db: Session = Depends(get_db)
):
  existing = db.query(models.User).filter(models.User.email == email).first()
  if existing:
    raise HTTPException(status_code=400, detail="Email already registered")

  hashed_pw = auth.hash_password(password)

  avatar_path = None
  if avatar:
    upload_dir = "uploads/avatars"
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{email}_{avatar.filename}"
    file_path = os.path.join(upload_dir, filename)
    with open(file_path, "wb") as f:
      shutil.copyfileobj(avatar.file, f)
    avatar_path = f"/{file_path}"

  new_user = models.User(
    email=email,
    name=name,
    password_hash=hashed_pw,
    phone_number=phone_number,
    avatar=avatar_path,
  )

  db.add(new_user)
  db.commit()
  db.refresh(new_user)
  return new_user


# ====================================================
# 🟦 UPLOAD / GANTI AVATAR USER
# ====================================================
@router.post("/users/{user_id}/avatar")
def upload_avatar(
    user_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(database.get_db)
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    upload_dir = "uploads/avatars"
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"{user_id}_{file.filename}"
    file_path = os.path.join(upload_dir, filename)

    # 🔄 Hapus foto lama kalau ada
    if user.avatar and os.path.exists(user.avatar.strip("/")):
        try:
            os.remove(user.avatar.strip("/"))
        except Exception:
            pass  # kalau gagal hapus, lanjut aja

    # 💾 Simpan foto baru
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    user.avatar = f"/uploads/avatars/{filename}"  # simpan path untuk frontend
    db.commit()
    db.refresh(user)

    return {
        "message": "Avatar uploaded successfully",
        "avatar": user.avatar
    }


@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(database.get_db)
):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.email},
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "avatar": user.avatar,
        }
    }
# 🟨 REQUEST UPDATE PROFILE (KIRIM OTP)
# ====================================================
# 🟨 REQUEST UPDATE PROFILE (KIRIM OTP)
@router.post("/request-update")
def request_update_profile(
    name: str = Form(...),
    phone_number: str = Form(...),
    current_password: Optional[str] = Form(None),
    new_password: Optional[str] = Form(None),
    avatar: Optional[UploadFile] = File(None),  # 🟢 Tambah ini
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if new_password:
        if not current_password or not auth.verify_password(current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Password lama salah")
        user.password_hash = auth.hash_password(new_password)

    otp = "".join(random.choices(string.digits, k=6))
    expiry = datetime.utcnow() + timedelta(minutes=5)

    user.pending_name = name
    user.pending_phone = phone_number
    user.otp_code = otp
    user.otp_expiry = expiry
    user.otp_purpose = "update_profile"

    # 🟢 Tambah: simpan avatar jika dikirim
    if avatar:
        upload_dir = "uploads/avatars"
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"{user.id}_{avatar.filename}"
        file_path = os.path.join(upload_dir, filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(avatar.file, f)
        user.avatar = f"/uploads/avatars/{filename}"

    db.commit()

    send_whatsapp_message(phone_number, f"Kode OTP Anda: {otp}\n\nJangan bagikan kode ini ke siapa pun.")

    return {"message": f"OTP dikirim ke {phone_number}"}


# ====================================================
# 🟧 VERIFY OTP UNTUK UPDATE PROFIL
# ====================================================
@router.post("/verify-update")
def verify_update_profile(
    phone_number: str = Form(...),
    otp_code: str = Form(...),
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    # 🔹 Ambil user berdasarkan token login
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 🔹 Pastikan OTP pernah dibuat
    if not user.otp_code or not user.otp_expiry:
        raise HTTPException(status_code=400, detail="Tidak ada permintaan OTP aktif")

    # 🔹 Cek apakah OTP sesuai
    if user.otp_code.strip() != otp_code.strip():
        raise HTTPException(status_code=400, detail="Kode OTP salah")

    # 🔹 Cek apakah OTP masih berlaku
    if user.otp_expiry < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Kode OTP sudah kadaluarsa")

    # 🔹 Pastikan nomor telepon cocok
    if user.pending_phone and user.pending_phone != phone_number:
        raise HTTPException(status_code=400, detail="Nomor telepon tidak cocok dengan OTP")

    # 🔹 Update data profil secara aman
    if user.pending_name:
        user.name = user.pending_name
    if user.pending_phone:
        user.phone_number = user.pending_phone

    # 🔹 Bersihkan kolom OTP & pending agar tidak bisa reuse
    user.otp_code = None
    user.otp_expiry = None
    user.pending_name = None
    user.pending_phone = None

    db.commit()
    db.refresh(user)

    return {
        "message": "Profil berhasil diperbarui",
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "phone_number": user.phone_number,
            "avatar": user.avatar
        }
    }
@router.post("/request-login-otp")
def request_login_otp(email: str = Form(...), db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="Email tidak ditemukan")

    otp = "".join(random.choices(string.digits, k=6))
    expiry = datetime.utcnow() + timedelta(minutes=5)

    user.otp_code = otp
    user.otp_expiry = expiry
    user.otp_purpose = "login"

    db.commit()

    send_whatsapp_message(user.phone_number, f"Kode OTP Login Anda: {otp}")

    return {"message": f"OTP dikirim ke WhatsApp {user.phone_number[-4:]}****"}

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
@router.post("/forgot-password")
def forgot_password(
    phone_number: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.phone_number == phone_number).first()
    if not user:
        # jangan berikan info berlebih di prod; untuk dev OK
        raise HTTPException(status_code=404, detail="Nomor tidak ditemukan")

    # rate-limit sederhana: jika OTP sebelumnya masih valid, tolak
    if user.otp_expiry and user.otp_expiry > datetime.utcnow():
        raise HTTPException(status_code=429, detail="OTP sudah dikirim, silakan tunggu beberapa menit")

    # generate OTP + reset token
    otp = "".join(random.choices(string.digits, k=6))
    otp_expiry = datetime.utcnow() + timedelta(minutes=5)

    reset_token = gen_token(48)
    reset_token_expiry = datetime.utcnow() + timedelta(minutes=10)  # token valid 10 menit

    # simpan di user record
    user.otp_code = otp
    user.otp_expiry = otp_expiry
    user.otp_purpose = "forgot_password"
    user.reset_token = reset_token
    user.reset_token_expiry = reset_token_expiry

    db.commit()

    # kirim OTP via Fonnte
    send_whatsapp_message(phone_number, f"🔐 Kode OTP Reset Password Anda: {otp}\n\nJangan bagikan kode ini ke siapa pun.")

    # RETURN reset_token (frontend perlu menyertakannya saat verifikasi)
    return {"message": "OTP dikirim", "reset_token": reset_token, "expires_in": 10 * 60}


# ==============================
# VERIFY FORGOT (butuh otp + reset_token)
# ==============================
@router.post("/verify-forgot")
def verify_forgot_password(
    phone_number: str = Form(...),
    otp_code: str = Form(...),
    reset_token: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.phone_number == phone_number).first()
    if not user:
        raise HTTPException(status_code=404, detail="Nomor tidak ditemukan")

    # validasi reset_token
    if not user.reset_token or user.reset_token != reset_token:
        raise HTTPException(status_code=400, detail="Reset token tidak valid")
    if not user.reset_token_expiry or user.reset_token_expiry < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Reset token sudah kadaluarsa")

    # validasi OTP
    if not user.otp_code or user.otp_purpose != "forgot_password":
        raise HTTPException(status_code=400, detail="Tidak ada OTP aktif untuk reset password")
    if user.otp_code.strip() != otp_code.strip():
        raise HTTPException(status_code=400, detail="Kode OTP salah")
    if user.otp_expiry < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Kode OTP sudah kadaluarsa")

    # jika valid -> bersihkan otp & token agar tidak bisa reuse
    user.otp_code = None
    user.otp_expiry = None
    user.otp_purpose = None
    user.reset_token = None
    user.reset_token_expiry = None

    db.commit()

    return {"message": "OTP valid. Silakan buat password baru.", "status": "verified"}


# ==============================
# RESET PASSWORD (setelah verifikasi)
# ==============================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

@router.post("/reset-password")
def reset_password(
    phone_number: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.phone_number == phone_number).first()
    if not user:
        raise HTTPException(status_code=404, detail="Nomor tidak ditemukan.")

    hashed_pw = pwd_context.hash(new_password)
    user.password_hash = hashed_pw
    db.commit()

    return {"message": "Password berhasil diperbarui untuk nomor tersebut."}

from fastapi import Header, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime
import os

from .. import models, database

MASTER_KEY = os.getenv("MASTER_KEY")


@router.delete("/admin/user")
def admin_delete_user(
    user_id: int,
    hard_delete: bool = False,
    x_master_key: str = Header(None),
    db: Session = Depends(database.get_db)
):
    # 🔒 Verifikasi Master Key
    if x_master_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid Master Key")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 🧹 Bersihkan semua data terkait user ini
    try:
        # Hapus hubungan user sebagai approver & recipient
        db.query(models.Approver).filter(models.Approver.user_id == user_id).delete()
        db.query(models.Recipient).filter(models.Recipient.user_id == user_id).delete()

        # Hapus dokumen yang dibuat user
        documents = db.query(models.Document).filter(models.Document.creator_id == user_id).all()
        for doc in documents:
            # 🔹 Hapus file-file terkait dokumen
            files = db.query(models.File).filter(models.File.document_id == doc.id).all()
            for f in files:
                if hasattr(f, "file_path") and f.file_path:
                    file_path = f.file_path.strip("/")
                    if os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                        except Exception as e:
                            print("⚠️ Gagal hapus file:", e)
                db.delete(f)

            # 🔹 Hapus log dan relasi dokumen lain
            db.query(models.Approver).filter(models.Approver.document_id == doc.id).delete()
            db.query(models.Recipient).filter(models.Recipient.document_id == doc.id).delete()

            # 🔹 Hapus dokumennya sendiri
            db.delete(doc)

        # 🔥 Terakhir, hapus user
        db.delete(user)
        db.commit()

        # 🧾 Catat aksi di log
        log_dir = "uploads"
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "admin_actions.log")
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(
                f"[{datetime.utcnow()}] HARD DELETE USER ID {user_id} ({user.email}) by MASTER_KEY\n"
            )

        return {"message": f"✅ User {user.email} and all related data deleted successfully"}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.options("/admin/user")
async def options_admin_user():
    """CORS preflight handler (biar DELETE aman di browser)"""
    return JSONResponse(
        content={"message": "OK"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "X-MASTER-KEY, Content-Type, Authorization",
        },
    )
@router.put("/admin/user/password")
def admin_change_user_password(
    user_id: int,
    new_password: str,
    x_master_key: str = Header(None),
    db: Session = Depends(database.get_db)
):
    # 🔒 Verifikasi Master Key
    if x_master_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Forbidden: Invalid Master Key")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 🔐 Hash password baru
    hashed_pw = auth.hash_password(new_password)
    user.password_hash = hashed_pw
    db.commit()

    # 🧾 Tulis log
    log_dir = "uploads"
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "admin_actions.log")

    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(
            f"[{datetime.utcnow()}] PASSWORD RESET for USER ID {user_id} ({user.email}) by MASTER_KEY\n"
        )

    return {"message": "Password updated successfully"}
