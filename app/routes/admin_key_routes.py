# routes/admin_key_routes.py  (atau tambah di routes/users.py)
import os
from fastapi import APIRouter, Depends, HTTPException, Header, status, Request
from pydantic import BaseModel, constr
from sqlalchemy.orm import Session
from .. import database, models
from passlib.context import CryptContext
import logging
from datetime import datetime

router = APIRouter(prefix="/admin", tags=["AdminKey"])

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
MASTER_KEY = os.environ.get("MASTER_KEY")  # harus diset di environment

logger = logging.getLogger("admin_key")
# configure logger di main app jika belum ada:
# logging.basicConfig(level=logging.INFO)

def hash_password(password: str) -> str:
    return pwd_ctx.hash(password)

# request model untuk ganti password user lain
class AdminSetPasswordRequest(BaseModel):
    user_id: int
    new_password: constr(min_length=8)

# request model untuk hapus user
class AdminDeleteUserRequest(BaseModel):
    user_id: int
    hard_delete: bool = False  # default soft-delete

# helper untuk cek master key
def verify_master_key(master_key_header: str):
    if not MASTER_KEY:
        raise HTTPException(status_code=500, detail="Server misconfigured (no MASTER_KEY)")
    if not master_key_header or master_key_header != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid master key")

# === Endpoint: set password untuk user tertentu (dengan master key) ===
@router.put("/user/password")
def admin_set_user_password(
    body: AdminSetPasswordRequest,
    request: Request,
    x_master_key: str = Header(None, alias="X-MASTER-KEY"),
    db: Session = Depends(database.get_db)
):
    # verify
    verify_master_key(x_master_key)

    user = db.query(models.User).filter(models.User.id == body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(body.new_password)
    db.add(user)
    db.commit()

    # audit log
    logger.info({
        "action": "admin_set_password",
        "user_id": user.id,
        "executor": "master_key",
        "timestamp": datetime.utcnow().isoformat(),
        "remote_addr": request.client.host if request.client else None
    })

    return {"message": f"Password for user {user.id} updated via master key."}

# === Endpoint: delete user by id (soft or hard) ===
@router.delete("/user")
def admin_delete_user(
    body: AdminDeleteUserRequest,
    request: Request,
    x_master_key: str = Header(None, alias="X-MASTER-KEY"),
    db: Session = Depends(database.get_db)
):
    verify_master_key(x_master_key)

    user = db.query(models.User).filter(models.User.id == body.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.hard_delete:
        db.delete(user)
        message = f"User {body.user_id} permanently deleted."
    else:
        # soft delete: set is_deleted or is_active = False
        if hasattr(user, "is_deleted"):
            user.is_deleted = True
        elif hasattr(user, "is_active"):
            user.is_active = False
        else:
            # fallback to soft by adding custom field? here we do hard delete as fallback
            db.delete(user)
        message = f"User {body.user_id} soft-deleted."

    db.commit()

    logger.info({
        "action": "admin_delete_user",
        "user_id": body.user_id,
        "hard_delete": bool(body.hard_delete),
        "executor": "master_key",
        "timestamp": datetime.utcnow().isoformat(),
        "remote_addr": request.client.host if request.client else None
    })

    return {"message": message}
