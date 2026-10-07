"""Hourly cleanup of rows nothing reads any more, so the database (and the queries that scan it) stop growing.

  action log          older than ACTION_LOG_DAYS (default 14); the game only looks back 24 hours
  Discord receipts    older than 2 days; Discord retries an interaction within minutes
  link codes          expired for more than a day
  journal entries     older than JOURNAL_DAYS (default 90), always keeping each citizen's newest 20

Rows go in small batches, each its own short transaction, outside the world lock: nobody reads these rows, so
gameplay never waits on the cleanup.
"""
import asyncio
import logging
import os
from datetime import timedelta
from sqlalchemy import text
from . import runtime

BATCH = 2000
MAX_BATCHES = 25          # per table per pass; a backlog is worked off over a few hours
JOURNAL_KEEP = 20
log = logging.getLogger(__name__)


def days(name, default):
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _batched(m, statement, params):
    removed = 0
    for _ in range(MAX_BATCHES):
        with runtime.engine.begin() as conn:
            count = conn.execute(text(statement), params).rowcount or 0
        removed += count
        if count < BATCH:
            break
    return removed


def prune(m):
    """Delete old rows; returns how many went from each table."""
    now = runtime.now()
    done = {}
    done['action_logs'] = _batched(m, 'DELETE FROM action_logs_v5 WHERE id IN (SELECT id FROM action_logs_v5 WHERE created_at < :cutoff '
                                      f'ORDER BY id LIMIT {BATCH})', {'cutoff': now - timedelta(days=days('ACTION_LOG_DAYS', 14))})
    done['command_receipts'] = _batched(m, 'DELETE FROM discord_command_receipts_v1 WHERE interaction_id IN (SELECT interaction_id FROM '
                                           f'discord_command_receipts_v1 WHERE created_at < :cutoff LIMIT {BATCH})',
                                        {'cutoff': now - timedelta(days=2)})
    done['link_codes'] = _batched(m, f'DELETE FROM link_codes_v4 WHERE id IN (SELECT id FROM link_codes_v4 WHERE expires_at < :cutoff LIMIT {BATCH})',
                                  {'cutoff': now - timedelta(days=1)})
    done['journal'] = _batched(m, 'DELETE FROM journal_v54 WHERE id IN (SELECT id FROM (SELECT id, created_at, ROW_NUMBER() OVER ('
                                  'PARTITION BY channel_id, canonical_uid ORDER BY created_at DESC, id DESC) AS newest FROM journal_v54) ranked '
                                  f'WHERE newest > {JOURNAL_KEEP} AND created_at < :cutoff LIMIT {BATCH})',
                               {'cutoff': now - timedelta(days=days('JOURNAL_DAYS', 90))})
    if any(done.values()):
        log.info('Cleanup removed old rows: %s', done)
    return done


def install(m):
    from .game.base import app
    from discord.ext import tasks

    @tasks.loop(hours=1, reconnect=True)
    async def timer():
        try:
            await asyncio.to_thread(prune, m)
        except Exception:
            log.exception('Cleanup pass failed; it runs again next hour')

    async def start():
        app.state.maintenance_worker = timer.start()

    async def stop():
        timer.stop()
    app.add_event_handler('startup', start)
    app.add_event_handler('shutdown', stop)
