"""Installs the feature modules (ask, inbox, extras, overlay, Seedlings, onboarding, ...) into this module.
"""
from ..db import Base, engine
from .rules import SKILL_LABELS
from .. import main      # app.main: names from later modules and settings changed at runtime

from .. import qol, presentation, menu, inbox, extras, keep_levels, shopping_list, force_merge, ask, halloween
game_menu=menu
ask.install(main)
halloween.install(main)
inbox.install(main)
extras.install(main)
from .. import stream_overlay
stream_overlay.install(main)
from .. import autonomy
autonomy.install(main)
from .. import onboarding
onboarding.install(main)
from .. import community, votes, seasons, trophies, live_events, recap, activity_feed, twitch_lite
community.install(main)
twitch_lite.install(main)
from .. import maintenance, world_merge
maintenance.install(main)
world_merge.install(main)
presentation.SKILL_NAMES=tuple(SKILL_LABELS.values())
# Every module above is loaded now: create any table a module added since the first create_all (existing tables are left alone).
Base.metadata.create_all(engine)
# Level-up lines stored before they used names ("Relationship 621372225") are rewritten once: "Relationship with blake1215".
from .. import readable_names
readable_names.repair(main)
readable_names.restore_names(main)
