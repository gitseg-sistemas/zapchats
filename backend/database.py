from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy import create_engine
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")  # ou monte com user/pass/host

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Sua base declarativa já deve estar aí
from sqlalchemy.ext.declarative import declarative_base
Base = declarative_base()

# ✅ Função que faltava:
def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
