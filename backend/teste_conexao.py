from backend.database import SessionLocal
from sqlalchemy import text

try:
    db = SessionLocal()
    db.execute(text("SELECT 1"))
    print("✅ Conectado ao PostgreSQL com sucesso!")
except Exception as e:
    print("❌ Erro na conexão:", e)
finally:
    db.close()
