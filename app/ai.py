"""Optional Claude API features: Find's fallback answers, Seedling thoughts and diary, and the weekly recap's story.

They are off until the game owner adds ANTHROPIC_API_KEY as a Railway variable. Every caller keeps its no-AI text:
write() returns '' when the key is missing, the feature is switched off, the day's budget is spent, the API is slow
or fails, or the caller holds the game lock (task_queue.atomic: an API call there would hold up every player), and the
caller shows what it showed before. Nothing here ever raises into the game.

Railway variables (only the key is needed):
  ANTHROPIC_API_KEY    turns the features on. Never logged, stored or shown.
  ANTHROPIC_MODEL      the model, default claude-haiku-5-5 (the cheapest).
  AI_FEATURES          which features run, comma separated: find,seedling,recap (default all three).
  AI_DAILY_LIMIT       API calls per UTC day for the whole game (default 300).
  AI_FIND_PER_PLAYER   AI answers in Find per player per UTC day (default 10).

The budget counts calls before they are made, in the caller's session, so a busy minute cannot run past the limit
(a call that fails still counts). The owner's hard limit on money is the monthly spend limit in the Claude Console.
"""
import logging
import os
import re
from datetime import timedelta

from sqlalchemy import Column, DateTime, Integer, String, Text, delete
from sqlalchemy.exc import IntegrityError

from . import runtime
from .db import Base, connection_context

API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'
DEFAULT_MODEL = 'claude-haiku-5-5'
FEATURES = ('find', 'seedling', 'recap')
DEFAULT_DAILY_LIMIT = 300
DEFAULT_FIND_PER_PLAYER = 10
CACHE_MIN_CHARS = 2000       # a system prompt this long is marked for prompt caching (repeat calls read it at a tenth of the price)
KEEP_DAYS = 30               # kept texts (a week's recap story, a Seedling's day) older than this are removed
LIMIT_TEXT = 1500            # the longest text write() returns

log = logging.getLogger(__name__)


class AiUsage(Base):
    """API calls per UTC day: scope 'all' for the whole game, 'find:<player>' for one player's Find answers."""
    __tablename__ = 'ai_usage_v1'
    day = Column(String(10), primary_key=True)
    scope = Column(String(160), primary_key=True)
    count = Column(Integer, nullable=False, default=0)


class AiText(Base):
    """A written text kept so it is written once: 'recap:<week>', 'seedling:<world>:<player>:<day>'."""
    __tablename__ = 'ai_text_v1'
    key = Column(String(200), primary_key=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------- settings

def _key():
    return os.getenv('ANTHROPIC_API_KEY', '').strip()


def model():
    return os.getenv('ANTHROPIC_MODEL', '').strip() or DEFAULT_MODEL


def _number(name, default):
    try:
        return max(0, int(os.getenv(name, '').strip() or default))
    except ValueError:
        return default


def daily_limit():
    return _number('AI_DAILY_LIMIT', DEFAULT_DAILY_LIMIT)


def find_per_player():
    return _number('AI_FIND_PER_PLAYER', DEFAULT_FIND_PER_PLAYER)


def features():
    raw = os.getenv('AI_FEATURES')
    if raw is None or not raw.strip():
        return set(FEATURES)
    return {f.strip().casefold() for f in raw.split(',') if f.strip()} & set(FEATURES)


def enabled(feature):
    """Whether `feature` (find, seedling or recap) may call the API at all (the budget is checked when it does)."""
    return bool(_key()) and feature in features()


def locked():
    """Whether this code runs inside the game lock (task_queue.atomic). An API call there would hold up every player for
    seconds, so write() refuses: callers make their call before or after the lock."""
    return connection_context.get() is not None


def today():
    return runtime.now().strftime('%Y-%m-%d')


# ---------------------------------------------------------------- budget

def used(db, scope='all', day=None):
    row = db.get(AiUsage, (day or today(), scope))
    return row.count if row is not None else 0


def _count(db, day, scope):
    """Add one call to (day, scope). Two requests may create the same row at once (PostgreSQL): the loser adds to the winner's."""
    try:
        with db.begin_nested():
            row = db.get(AiUsage, (day, scope))
            if row is None:
                db.add(AiUsage(day=day, scope=scope, count=1))
            else:
                row.count += 1
    except IntegrityError:
        row = db.get(AiUsage, (day, scope))
        if row is not None:
            row.count += 1


def _spend(db, scope='', per_scope=None):
    """Reserve one call within today's limits; False (and nothing counted) when a limit is reached."""
    day = today()
    if used(db, 'all', day) >= daily_limit():
        return False
    if scope and per_scope is not None and used(db, scope, day) >= per_scope:
        return False
    _count(db, day, 'all')
    if scope:
        _count(db, day, scope)
    db.flush()
    return True


# ---------------------------------------------------------------- the call

def _post(payload, timeout):
    """POST to the Messages API and return the decoded JSON (raises on any failure). Tests replace this."""
    import requests
    response = requests.post(API_URL, json=payload, timeout=timeout,
                             headers={'x-api-key': _key(), 'anthropic-version': API_VERSION, 'content-type': 'application/json'})
    if response.status_code >= 400:
        raise RuntimeError(f'Claude API answered HTTP {response.status_code}')
    return response.json()


def clean(text, limit=LIMIT_TEXT):
    """A model's reply made safe to post: no pings (@everyone, @here, <@id>, <@&role>, <#channel>), no invite links,
    no headings, at most `limit` characters."""
    text = str(text or '').strip()
    text = re.sub(r'<(@[!&]?|#)\d+>', '', text)
    text = re.sub(r'@(everyone|here)\b', r'@​\1', text, flags=re.I)
    text = re.sub(r'(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/\S+', '', text, flags=re.I)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.M)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if len(text) > limit:
        text = text[:limit - 1].rsplit(' ', 1)[0].rstrip(' ,;:') + '…'
    return text


def write(db, feature, system, prompt, max_tokens=300, scope='', per_scope=None, timeout=12):
    """Claude's reply to `prompt` (with the `system` instructions), cleaned; '' whenever it cannot or should not run.

    `scope`/`per_scope` add a second daily limit (one player's Find answers). Uses the caller's session for the
    budget, so the caller commits as usual."""
    if not enabled(feature):
        return ''
    if locked():
        log.warning('AI %s call skipped: it would run inside the game lock', feature)
        return ''
    try:
        if not _spend(db, scope, per_scope):
            return ''
    except Exception:
        log.exception('AI budget check failed; answering without AI')
        return ''
    block = {'type': 'text', 'text': system}
    if len(system) >= CACHE_MIN_CHARS:
        block['cache_control'] = {'type': 'ephemeral'}
    payload = {'model': model(), 'max_tokens': int(max_tokens), 'system': [block],
               'messages': [{'role': 'user', 'content': prompt}]}
    try:
        data = _post(payload, timeout)
        text = ''.join(b.get('text', '') for b in data.get('content') or [] if b.get('type') == 'text')
    except Exception as error:      # slow, refused or malformed: the caller's own text is shown instead
        log.warning('AI %s call failed (%s); answering without AI', feature, type(error).__name__)
        return ''
    return clean(text)


# ---------------------------------------------------------------- kept texts

def kept(db, key):
    """A text written earlier under `key`, or ''."""
    row = db.get(AiText, key)
    return row.text if row is not None else ''


def keep(db, key, text):
    """Keep `text` under `key` (replacing an older one) and drop texts older than KEEP_DAYS. Caller commits."""
    if not text:
        return
    when = runtime.now()
    try:
        with db.begin_nested():
            row = db.get(AiText, key)
            if row is None:
                db.add(AiText(key=key, text=text, created_at=when))
            else:
                row.text, row.created_at = text, when
        db.execute(delete(AiText).where(AiText.created_at < when - timedelta(days=KEEP_DAYS)))
    except IntegrityError:          # another request kept the same text first: theirs stands
        pass
    except Exception:
        log.exception('AI text could not be kept')


def written(db, feature, key, system, prompt, max_tokens=300, timeout=12):
    """The text kept under `key`, writing it once when there is none yet ('' when it cannot be written)."""
    found = kept(db, key)
    if found:
        return found
    text = write(db, feature, system, prompt, max_tokens=max_tokens, timeout=timeout)
    keep(db, key, text)
    return text


# ---------------------------------------------------------------- for the owner

def status_line(db):
    """One line for the owner's screens: on or off, the model and today's calls."""
    if not _key():
        return '🤖 AI features: off. Add ANTHROPIC_API_KEY in Railway to turn them on.'
    try:
        calls = used(db)
    except Exception:
        calls = 0
    on = ', '.join(f for f in FEATURES if f in features()) or 'none'
    return f'🤖 AI features: on ({on}) · {model()} · {calls} of {daily_limit()} calls today'
