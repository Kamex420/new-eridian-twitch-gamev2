"""HTTP and Discord adapters for the New Eridian game domain.

This module composes persistence, command handling and the ASGI application.
Domain modules under app/ own needs, item identities and queue transactions.
Stable routes and storage identifiers preserve existing clients and saves;
see docs/architecture.md for boundaries and compatibility decisions.
"""

# The game itself lives in app/game/, one module per topic (MODULES in app/game/__init__.py lists them in load
# order). This module imports them in that order and offers every name they define as app.main.<name>, so the
# feature modules (which call m.<name>), the routes and the tests work exactly as before. To change something, edit
# the module that defines it; docs/architecture.md says which module holds what.
import importlib as _importlib


def publish(namespace):
    """Offer a game module's names as app.main.<name>. The first module to define a name keeps it, so a name a later
    module imported, or one a feature module replaced on app.main (votes.install), is never overwritten."""
    mine = globals()
    for key, value in namespace.items():
        if key != 'main' and not (key.startswith('__') and key.endswith('__')) and key not in mine:
            mine[key] = value


def __getattr__(name):
    """While the game modules are still loading, a name not yet offered is looked up in the modules loaded so far
    (code that runs at import time, such as the feature modules' install(), may already use app.main.<name>)."""
    import sys
    for module_name in globals().get('_MODULES', ()):
        module = sys.modules.get(f'{__package__}.game.{module_name}')
        if module is not None and name in vars(module):
            return vars(module)[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


from .game import MODULES as _MODULES  # noqa: E402

for _name in _MODULES:
    publish(vars(_importlib.import_module('.game.' + _name, __package__)))
