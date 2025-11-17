from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os
from sqlalchemy import inspect, text
from dotenv import load_dotenv

load_dotenv()

# Ambil URL dari .env (kalau mau dinamis)
# DATABASE_URL = os.getenv("DATABASE_URL")


def sync_tables(engine, Base):
    """Sinkronkan kolom model SQLAlchemy dengan tabel MySQL tanpa hapus data."""
    inspector = inspect(engine)
    with engine.connect() as conn:
        for table_name, table in Base.metadata.tables.items():
            if table_name not in inspector.get_table_names():
                print(f"🆕 Membuat tabel baru: {table_name}")
                table.create(engine)
            else:
                existing_cols = [col["name"] for col in inspector.get_columns(table_name)]
                for col in table.columns:
                    if col.name not in existing_cols:
                        # Ambil tipe kolom dari deklarasi model
                        col_type = str(col.type.compile(engine.dialect))
                        nullable = "NULL" if col.nullable else "NOT NULL"
                        alter_stmt = text(
                            f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type} {nullable};"
                        )
                        print(f"🪄 Menambahkan kolom: {table_name}.{col.name}")
                        conn.execute(alter_stmt)
        conn.commit()
# Atau hardcode dulu untuk memastikan koneksi berhasil
DATABASE_URL = "mysql+pymysql://root:123@localhost:3306/edoc_db"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
