# app/main.py, part 24: wiring
# Installs the feature modules (ask, inbox, extras, overlay, Seedlings, onboarding, ...) into this module.
# Runs inside app.main's namespace, after the parts before it (see main.py). Not a module of its own.

from . import qol, presentation, menu, inbox, extras, keep_levels, shopping_list, force_merge, ask, halloween
game_menu=menu
ask.install(sys.modules[__name__])
halloween.install(sys.modules[__name__])
inbox.install(sys.modules[__name__])
extras.install(sys.modules[__name__])
from . import stream_overlay
stream_overlay.install(sys.modules[__name__])
from . import autonomy
autonomy.install(sys.modules[__name__])
from . import onboarding
onboarding.install(sys.modules[__name__])
from . import community, votes, seasons, trophies, live_events, recap, activity_feed, twitch_lite
community.install(sys.modules[__name__])
twitch_lite.install(sys.modules[__name__])
from . import maintenance, world_merge
maintenance.install(sys.modules[__name__])
world_merge.install(sys.modules[__name__])
presentation.SKILL_NAMES=tuple(SKILL_LABELS.values())
# Every module above is loaded now: create any table a module added since the first create_all (existing tables are left alone).
Base.metadata.create_all(engine)
# Level-up lines stored before they used names ("Relationship 621372225") are rewritten once: "Relationship with blake1215".
from . import readable_names
readable_names.repair(sys.modules[__name__])
readable_names.restore_names(sys.modules[__name__])
