from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.database import Base, engine, sync_tables
from app.routes import auth_routes, doc_routes, user_routes, file_routes, router_ws
from dotenv import load_dotenv
import os

# 🟢 1️⃣ Load environment variables lebih awal
load_dotenv()

# 🟢 2️⃣ Buat tabel & sinkronisasi database
Base.metadata.create_all(bind=engine)
sync_tables(engine, Base)

# 🟢 3️⃣ Inisialisasi FastAPI
app = FastAPI(title="e-Document FastAPI")

# 🟢 4️⃣ Middleware CORS (harus sebelum mount static & router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "*",  # 🔥 sementara: izinkan semua origin
    ],
    allow_credentials=True,
    allow_methods=["*"],   # termasuk DELETE
    allow_headers=["*"],   # termasuk X-MASTER-KEY
)

# 🟢 5️⃣ Include semua router (REST API)
app.include_router(auth_routes.router, prefix="/auth", tags=["auth"])
app.include_router(user_routes.router, prefix="/users", tags=["users"])
app.include_router(doc_routes.router, prefix="/documents", tags=["documents"])
app.include_router(file_routes.router, prefix="/files", tags=["files"])

# 🟢 6️⃣ Include router WebSocket
app.include_router(router_ws.router)

# 🟢 7️⃣ Terakhir: Mount static files (uploads, dll)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# ✅ Sekarang CORS aktif untuk semua endpoint, termasuk:
#    - DELETE /auth/admin/user
#    - PUT /auth/admin/user/password
#    - GET /uploads/admin_actions.log
