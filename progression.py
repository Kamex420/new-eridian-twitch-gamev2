"""Request-local notices plus persistent last milestone for status views."""
from contextvars import ContextVar
from .settlement import seedling
notices=ContextVar("progress_notices",default=None)

def announce(db,p,message,current):
    row=seedling(db,p);row.last_progress=message;row.last_progress_at=current
    from .models import JournalEntry
    db.add(JournalEntry(channel_id=p.channel_id,canonical_uid=p.twitch_uid,entry=message))
    pending=notices.get()
    if pending is not None:pending.append(message)
