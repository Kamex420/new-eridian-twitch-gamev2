"""Database ownership; existing DATABASE_URL and session API remain supported."""
import os
from contextvars import ContextVar
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
DATABASE_URL=os.getenv("DATABASE_URL", "sqlite:///./new_eridian.db")
def normalize_url(value):
    # Railway URLs commonly omit a driver. This project installs psycopg v3.
    if value.startswith(('postgres://','postgresql://')):
        return 'postgresql+psycopg://'+value.split('://',1)[1]
    return value

DATABASE_URL=normalize_url(DATABASE_URL)
connect_args={"check_same_thread":False,"timeout":30} if DATABASE_URL.startswith("sqlite") else {}
if DATABASE_URL.startswith('postgresql+psycopg:'):
    connect_args={'connect_timeout':10,'options':'-c lock_timeout=10000 -c statement_timeout=30000'}
engine=create_engine(DATABASE_URL,pool_pre_ping=True,connect_args=connect_args)
_sessions=sessionmaker(bind=engine,expire_on_commit=False)
connection_context=ContextVar('game_transaction',default=None)

def SessionLocal():
    connection=connection_context.get()
    if connection is not None:
        return Session(bind=connection,expire_on_commit=False,join_transaction_mode='rollback_only')
    return _sessions()
Base=declarative_base()
