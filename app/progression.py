"""Request-local notices plus persistent last milestone for status views."""
from contextvars import ContextVar
from .settlement import seedling
notices=ContextVar("progress_notices",default=None)

def announce(db,p,message,current):
    row=seedling(db,p);row.last_progress=message;row.last_progress_at=current
    from .models import JournalEntry
    # The deployed journal schema holds short summaries (220 characters).
    # Keep the complete message in last_progress and the notification outbox;
    # a longer alert must not roll back gameplay or the queue's error state.
    journal_limit=JournalEntry.__table__.c.entry.type.length
    summary=message if len(message)<=journal_limit else message[:journal_limit-1]+'…'
    db.add(JournalEntry(channel_id=p.channel_id,canonical_uid=p.twitch_uid,entry=summary))
    pending=notices.get()
    if pending is not None:pending.append(message)
