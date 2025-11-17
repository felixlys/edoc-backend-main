from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from .. import models, schemas, auth, database

router = APIRouter()

@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user

@router.delete("/me", status_code=status.HTTP_200_OK)
def delete_own_account(
    db: Session = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    # Cek apakah user ada
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Hapus user dari database
    db.delete(user)
    db.commit()

    return {"message": f"User '{current_user.email}' has been deleted successfully"}
@router.get("/users")
def list_users(db: Session = Depends(database.get_db)):
    users = db.query(models.User).all()
    return [{"id": u.id, "name": u.name, "email": u.email} for u in users]

@router.get("/debug/users-password")
def debug_list_users_password(db: Session = Depends(database.get_db)):
    users = db.query(models.User).all()
    return [
        {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "password_hash": u.password
        }
        for u in users
    ]