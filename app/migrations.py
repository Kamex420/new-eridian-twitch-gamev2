
"""Additive, repeatable migration; never resets a save or renames legacy columns."""
from sqlalchemy import inspect, text as sql_text
from .db import engine, Base
from .models import SimulationVersion
def migrate_schema():
    """Add new fields without replacing or clearing existing player/world rows."""
    additions={
        "players":{
            "cooking_xp":"INTEGER NOT NULL DEFAULT 0",
            "medicine_xp":"INTEGER NOT NULL DEFAULT 0",
            "emergency_xp":"INTEGER NOT NULL DEFAULT 0",
            "environmental_xp":"INTEGER NOT NULL DEFAULT 0",
            "fabrication_xp":"INTEGER NOT NULL DEFAULT 0",
            "infrastructure_xp":"INTEGER NOT NULL DEFAULT 0",
            "commerce_xp":"INTEGER NOT NULL DEFAULT 0",
        },
        "world_v4":{
            "event_support_successes":"INTEGER NOT NULL DEFAULT 0",
            "event_instance":"VARCHAR(32)",
            "event_started_at":"TIMESTAMP",
            "event_started_by":"VARCHAR(128)",
            "event_active_players":"INTEGER NOT NULL DEFAULT 1",
            "activity_since_event":"INTEGER NOT NULL DEFAULT 0",
            "activity_window_started_at":"TIMESTAMP",
        },
    }
    with engine.begin() as conn:
        db_inspector=inspect(conn)
        added=set()
        for table,columns in additions.items():
            existing={c["name"] for c in db_inspector.get_columns(table)}
            for column,definition in columns.items():
                if column not in existing:
                    conn.execute(sql_text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
                    added.add((table,column))
        # Preserve historical Industry XP in both new specializations once.
        if ("players","fabrication_xp") in added:
            conn.execute(sql_text("UPDATE players SET fabrication_xp=industry_xp WHERE industry_xp>0"))
        if ("players","infrastructure_xp") in added:
            conn.execute(sql_text("UPDATE players SET infrastructure_xp=industry_xp WHERE industry_xp>0"))
        # Rename existing player-facing equipment without changing its stable
        # internal recipe key or deleting anyone's crafted item.
        conn.execute(sql_text("UPDATE quality_gear_v53 SET item_name='Field Hoe' WHERE item_key='cultivator'"))

    with engine.begin() as conn:
        if not conn.execute(sql_text("SELECT version FROM simulation_schema_versions WHERE version=7")).first():
            conn.execute(SimulationVersion.__table__.insert().values(version=7))
    add_indexes()


# Indexes for queries that run constantly (the overlay's 24-hour leaders, activity counts, the journal) and for the
# hourly cleanup. CREATE INDEX IF NOT EXISTS works on SQLite and Postgres and leaves an existing index alone.
INDEXES = {
    "ix_action_logs_channel_created": ("action_logs_v5", "channel_id, created_at"),
    "ix_journal_owner_created": ("journal_v54", "channel_id, canonical_uid, created_at"),
    "ix_command_receipts_created": ("discord_command_receipts_v1", "created_at"),
    "ix_link_codes_expires": ("link_codes_v4", "expires_at"),
}


def add_indexes():
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        for name, (table, columns) in INDEXES.items():
            if table in tables:
                conn.execute(sql_text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})"))
