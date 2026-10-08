"""Seedling looks and personality: make your Seedling yours.

Players choose, on Discord (/customize, or /menu → You → My Seedling → Looks & personality):

  skin tone      twelve tones, from porcelain to deep, plus four Avesta colours (moss, sky, lavender, coral)
  hair           style (short, long, curly, bun, spiky, mohawk, pigtails, braid, bald) and colour
  headwear       its job hat, or no hat so its hair shows
  outfit         a fixed colour, or "mood" to let the shirt follow its mood (the default)
  accessory      glasses, scarf, bow tie, backpack, flower, headphones or none
  attitude       cheerful, grumpy, shy, bold, dreamy, sarcastic, curious, chill, dramatic or wise:
                 how it talks in its speech bubbles and in the stream caption
  catchphrase    one of a curated set it says now and then on stream (curated so nothing unkind reaches the stream)

Everything is cosmetic: it changes how the Seedling looks on the stream map and how it talks, never how
well it works. Anything not chosen keeps the Seedling's original random look.
"""
import random
from sqlalchemy import Column, String, select
from .db import Base

SKIN = {'porcelain': ('Porcelain', '#f6d7c3'), 'fair': ('Fair', '#f1c9a5'), 'beige': ('Warm beige', '#e0ac7e'), 'golden': ('Golden', '#d69b62'),
        'tan': ('Tan', '#c68a5a'), 'olive': ('Olive', '#b08a5a'), 'bronze': ('Bronze', '#a86b43'), 'brown': ('Brown', '#8d5a3b'),
        'deep': ('Deep', '#5e3b26'), 'ebony': ('Ebony', '#46291b'),
        'moss': ('Avesta moss', '#8fbf7a'), 'sky': ('Avesta sky', '#9cc9e8'), 'lavender': ('Avesta lavender', '#c3a8e8'), 'coral': ('Avesta coral', '#f29b8b')}
HAIR = {'short': 'Short', 'long': 'Long', 'curly': 'Curly', 'bun': 'Bun', 'spiky': 'Spiky', 'mohawk': 'Mohawk', 'pigtails': 'Pigtails',
        'braid': 'Braid', 'bald': 'Bald'}
HAIR_COLOUR = {'black': ('Black', '#2b1d14'), 'dark_brown': ('Dark brown', '#5a3a22'), 'auburn': ('Auburn', '#7a2a1a'), 'ginger': ('Ginger', '#c0622f'),
               'blonde': ('Blonde', '#e2c27a'), 'silver': ('Silver', '#c9c9d6'), 'white': ('White', '#f4f4f4'), 'pink': ('Pink', '#ff8fc7'),
               'teal': ('Teal', '#3fc1b0'), 'purple': ('Purple', '#8a5ad6'), 'blue': ('Blue', '#4f7fe0'), 'green': ('Green', '#5fae4a')}
OUTFIT = {'mood': ('Follows its mood', ''), 'red': ('Red', '#e0564f'), 'orange': ('Orange', '#f28b3c'), 'yellow': ('Yellow', '#f2c230'),
          'green': ('Green', '#6fbf5a'), 'teal': ('Teal', '#3fb8b0'), 'blue': ('Blue', '#4f8fe0'), 'navy': ('Navy', '#2d3f8a'),
          'purple': ('Purple', '#8a5ad6'), 'pink': ('Pink', '#ff8fc7'), 'white': ('White', '#eef1f4'), 'black': ('Black', '#2b2f45'),
          'brown': ('Brown', '#8a5a3a')}
ACCESSORY = {'none': 'None', 'glasses': 'Glasses', 'sunglasses': 'Sunglasses', 'scarf': 'Scarf', 'bowtie': 'Bow tie',
             'backpack': 'Backpack', 'flower': 'Flower', 'headphones': 'Headphones'}
# attitude -> (label, what it is like, how it starts a line, how it ends one)
ATTITUDE = {
    'cheerful': ('Cheerful', 'always looks on the bright side', ['Yay! ', 'Ooh! ', ''], [' 😄', '!', ' Best day ever!']),
    'grumpy': ('Grumpy', 'complains, but always shows up', ['Hmph. ', 'Ugh. ', 'Fine. '], ['', ' Whatever.', ' Not that anyone asked.']),
    'shy': ('Shy', 'quiet, kind and a little nervous', ['Um… ', 'Oh, h-hi… ', ''], ['…', ' …sorry.', '']),
    'bold': ('Bold', 'loud, brave and first in line', ['Watch this! ', 'Out of my way! ', ''], ['!', ' Easy!', ' Who’s next?']),
    'dreamy': ('Dreamy', 'always a little lost in thought', ['*gazes at the sky* ', 'Hmm… ', ''], [' …like the stars.', '…', '']),
    'sarcastic': ('Sarcastic', 'dry humour for every occasion', ['Oh great. ', 'Wow. ', 'Sure. '], [' Thrilling.', ' Love that for me.', '']),
    'curious': ('Curious', 'asks about everything', ['Ooh, what’s this? ', 'Wait— ', ''], [' I wonder why?', ' Fascinating!', '']),
    'chill': ('Chill', 'takes it easy, all the time', ['Eh. ', 'No rush. ', ''], [' 😎', ' All good.', '']),
    'dramatic': ('Dramatic', 'everything is a big deal', ['Behold! ', 'At last! ', 'Alas! '], [' Truly legendary!', '!!', ' The drama!']),
    'wise': ('Wise', 'calm, thoughtful and full of sayings', ['Remember: ', 'As they say: ', ''], [' Patience grows crops.', '', ' So it goes.']),
}
CATCHPHRASES = {'lets_go': 'Let’s go!', 'for_eridian': 'For New Eridian!', 'rocky': 'Rocky would approve.', 'ore': 'Another day, another ore.',
                'ducks': 'Ducks deliver, and so do I.', 'comfy': 'Stay comfy, friends.', 'science': 'Science!', 'plans': 'Big plans today.',
                'vibing': 'Just vibing.', 'one_more': 'One more craft…', 'beautiful': 'Avesta is beautiful today.',
                'lumber': 'Who moved my Lumber?', 'siro': 'Siro? Never heard of it.', 'soft_bed': 'Hard work, soft bed.', 'snacks': 'Snacks first.',
                'teamwork': 'Teamwork makes the dream work.', 'sparkle': 'Stay sparkly!', 'hello': 'Hello, chat!'}
HEADWEAR = {'job': 'Job hat (farmers wear straw hats, miners helmets…)', 'none': 'No hat: show my hair'}
FIELDS = {'skin': SKIN, 'hair': HAIR, 'hair_colour': HAIR_COLOUR, 'outfit': OUTFIT, 'accessory': ACCESSORY, 'headwear': HEADWEAR,
          'attitude': ATTITUDE, 'catchphrase': CATCHPHRASES}
TITLES = {'skin': 'Skin tone', 'hair': 'Hair style', 'hair_colour': 'Hair colour', 'outfit': 'Outfit colour', 'accessory': 'Accessory',
          'headwear': 'Headwear', 'attitude': 'Attitude', 'catchphrase': 'Catchphrase'}


class Looks(Base):
    __tablename__ = 'seedling_looks_v1'
    channel_id = Column(String(64), primary_key=True)
    canonical_uid = Column(String(96), primary_key=True)
    skin = Column(String(16), nullable=False, default='')
    hair = Column(String(16), nullable=False, default='')
    hair_colour = Column(String(16), nullable=False, default='')
    outfit = Column(String(16), nullable=False, default='')
    accessory = Column(String(16), nullable=False, default='')
    headwear = Column(String(16), nullable=False, default='')
    attitude = Column(String(16), nullable=False, default='')
    catchphrase = Column(String(16), nullable=False, default='')


def label(field, key):
    value = FIELDS[field].get(key)
    if value is None:
        return ''
    return value if isinstance(value, str) else value[0]


def choices(field):
    """(label, key) for a Discord option or dropdown (at most 25)."""
    rows = []
    for key, value in FIELDS[field].items():
        text = value if isinstance(value, str) else value[0]
        if field == 'attitude':
            text = f'{value[0]}: {value[1]}'
        rows.append((text[:100], key))
    return (rows + [('↺ Back to its original look', 'random')])[:25]


def row(db, p, create=False):
    found = db.get(Looks, (p.channel_id, p.twitch_uid))
    if found is None and create:
        found = Looks(channel_id=p.channel_id, canonical_uid=p.twitch_uid)
        db.add(found)
        db.flush()
    return found


def _match(field, value):
    text = str(value or '').strip().casefold().replace(' ', '_').replace('-', '_')
    if not text:
        return None
    if text in FIELDS[field]:
        return text
    for key in FIELDS[field]:
        if label(field, key).casefold().replace(' ', '_') == text or text in label(field, key).casefold():
            return key
    return False


def change(db, p, **values):
    """Set any of the fields. Returns (changed [(title, label)], problems [text])."""
    found = row(db, p, create=True)
    changed, problems = [], []
    for field, value in values.items():
        if field not in FIELDS or value in (None, ''):
            continue
        if str(value).strip().casefold() in {'random', 'reset', 'default'}:
            setattr(found, field, '')
            changed.append((TITLES[field], 'back to its original look'))
            continue
        key = _match(field, value)
        if not key:
            problems.append(f"{TITLES[field]}: \"{value}\" is not an option ({', '.join(label(field, k) for k in list(FIELDS[field])[:8])}…)")
            continue
        setattr(found, field, key)
        changed.append((TITLES[field], label(field, key)))
    return changed, problems


def describe(found, name='Your Seedling'):
    if found is None:
        return []
    parts = [(TITLES[f], label(f, getattr(found, f))) for f in FIELDS if getattr(found, f)]
    return [f'{title}: **{value}**' for title, value in parts]


def view_text(db, p, provider='discord', changed=(), problems=()):
    found = row(db, p)
    lines = []
    if changed:
        lines.append('🎨 **Updated:** ' + ' · '.join(f'{t} → {v}' for t, v in changed))
    if problems:
        lines += ['⚠️ ' + x for x in problems]
    if lines:
        lines.append('')
    lines += [f'🎨 **LOOKS & PERSONALITY — {p.display_name.upper()}**',
              'How your Seedling looks on the stream map and how it talks in its speech bubbles. Purely cosmetic.', '']
    shown = describe(found)
    lines += shown if shown else ['Nothing chosen yet: your Seedling has its original random look.']
    if found is not None and found.attitude:
        a = ATTITUDE[found.attitude]
        lines += ['', f'💬 {a[0]}: {a[1]}. It sounds like: *"{voice("I brought in some Lumber.", found.attitude, "", random.Random(1))}"*']
    lines += ['', 'Change any of it with /customize, or /menu → You → My Seedling → Looks & personality. "random" puts one back.']
    return '\n'.join(lines)


# ---------------------------------------------------------------- the stream

def for_players(db, keys):
    """{(channel, uid): Looks} for the overlay."""
    if not keys:
        return {}
    rows = db.execute(select(Looks).where(Looks.canonical_uid.in_([u for _, u in keys]))).scalars()
    return {(r.channel_id, r.canonical_uid): r for r in rows if (r.channel_id, r.canonical_uid) in keys}


def overlay(found):
    """What the map needs to draw it: colours as hex values, styles as keys."""
    if found is None:
        return {}
    out = {}
    if found.skin in SKIN:
        out['skin'] = SKIN[found.skin][1]
    if found.hair in HAIR:
        out['hair'] = found.hair
    if found.hair_colour in HAIR_COLOUR:
        out['hair_colour'] = HAIR_COLOUR[found.hair_colour][1]
    if found.outfit in OUTFIT and OUTFIT[found.outfit][1]:
        out['outfit'] = OUTFIT[found.outfit][1]
    if found.accessory in ACCESSORY and found.accessory != 'none':
        out['accessory'] = found.accessory
    if found.headwear == 'none':
        out['nohat'] = 1          # its job hat comes off; a season hat it chose to wear stays on
    return out


def voice(line, attitude, catchphrase, r):
    """A line in the Seedling's own voice: an opening and an ending in its attitude. Words are never changed."""
    if not line or attitude not in ATTITUDE:
        return line
    _, _, starts, ends = ATTITUDE[attitude]
    start, end = r.choice(starts), r.choice(ends)
    body = line.rstrip()
    if end and not end.startswith(' ') and body[-1:] in '.!?…':
        body = body[:-1]                      # "…!" rather than "….!"
    text = f'{start}{body}{end}'
    return text if len(text) <= 150 else line


def flavour(lines, found, bucket):
    """Speech-bubble lines with attitude, plus the catchphrase now and then."""
    if found is None or (not found.attitude and not found.catchphrase):
        return lines
    r = random.Random(f'{found.canonical_uid}:{bucket}')
    lines = list(lines)[:5 if found.catchphrase in CATCHPHRASES else 6]      # room for the catchphrase in the six lines
    voiced = [i for i in range(1, len(lines)) if r.random() < 0.7] or ([1] if len(lines) > 1 else [0])   # always at least one line in its voice
    out = [voice(x, found.attitude, found.catchphrase, r) if i in voiced else x for i, x in enumerate(lines)]
    if found.catchphrase in CATCHPHRASES:
        out.insert(1 + r.randrange(max(1, len(out))), CATCHPHRASES[found.catchphrase])
    return list(dict.fromkeys(out))[:6]
