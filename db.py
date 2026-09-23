"""Database ownership; existing DATABASE_URL and session API remain supported."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
DATABASE_URL=os.getenv("DATABASE_URL", "sqlite:///./new_eridian.db")
engine=create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"check_same_thread":False} if DATABASE_URL.startswith("sqlite") else {})
SessionLocal=sessionmaker(bind=engine, expire_on_commit=False)
Base=declarative_base()
