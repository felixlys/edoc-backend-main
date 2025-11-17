from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from .. import models, database, auth
import random, string, requests, os
from twilio.rest import Client

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Simpan OTP sementara (disarankan pakai Redis di production)
RESET_CODES = {}

def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


# 🟩 Kirim WhatsApp via Fonnte
def send_whatsapp_otp(phone_number: str, code: str) -> bool:
    token = os.getenv("FONNTE_TOKEN")
    if not token:
        print("⚠️ FONNTE_TOKEN belum diset di environment")
        return False
    url = "https://api.fonnte.com/send"
    payload = {
        "target": phone_number,
        "message": f"Kode reset password Anda adalah *{code}*. Berlaku 10 menit.",
    }
    headers = {"Authorization": token}
    response = requests.post(url, data=payload, headers=headers)
    success = response.status_code == 200
    if not success:
        print("❌ Gagal kirim WhatsApp:", response.text)
    return success


# 🟦 Kirim SMS via Twilio
def send_sms_otp(phone_number: str, code: str) -> bool:
    sid = os.getenv("TWILIO_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM")

    if not all([sid, token, from_number]):
        print("⚠️ TWILIO credentials belum lengkap")
        return False

    try:
        client = Client(sid, token)
        msg = client.messages.create(
            body=f"Kode reset password Anda: {code}. Berlaku 10 menit.",
            from_=from_number,
            to=phone_number
        )
        print("✅ SMS dikirim:", msg.sid)
        return True
    except Exception as e:
        print("❌ Gagal kirim SMS:", str(e))
        return False


@router.post("/forgot-password")
def forgot_password(
    phone_number: str = Form(...),
    db: Session = Depends(database.get_db)
):
    user = db.query(models.User).filter(models.User.phone_number == phone_number).first()
    if not user:
        raise HTTPException(status_code=404, detail="Nomor tidak terdaftar")

    code = generate_otp()
    RESET_CODES[phone_number] = {
        "code": code,
        "expires": datetime.utcnow() + timedelta(minutes=10)
    }

    sent = send_whatsapp_otp(phone_number, code)
    if not sent:
        print("🟨 WhatsApp gagal, kirim via SMS fallback...")
        send_sms_otp(phone_number, code)

    print(f"[DEBUG] OTP dikirim ke {phone_number}: {code}")
    return {"message": "Kode OTP telah dikirim ke WhatsApp/SMS", "expires_in": 600}


@router.post("/reset-password")
def reset_password(
    phone_number: str = Form(...),
    code: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(database.get_db)
):
    if phone_number not in RESET_CODES:
        raise HTTPException(status_code=400, detail="Kode belum diminta")

    entry = RESET_CODES[phone_number]
    if datetime.utcnow() > entry["expires"]:
        raise HTTPException(status_code=400, detail="Kode sudah kedaluwarsa")

    if code != entry["code"]:
        raise HTTPException(status_code=400, detail="Kode salah")

    user = db.query(models.User).filter(models.User.phone_number == phone_number).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    user.password_hash = auth.hash_password(new_password)
    db.commit()
    del RESET_CODES[phone_number]

    return {"message": "Password berhasil diperbarui"}
