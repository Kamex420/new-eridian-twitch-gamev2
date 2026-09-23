from ._compat import load_root_module

# Load dependencies first so the legacy module's relative imports resolve to
# the public app.* wrappers, then execute the legacy FastAPI application.
for _name in (
    "db", "models", "needs", "occupations", "competencies", "settlement",
    "seedlings", "events", "progression", "commands", "migrations",
):
    load_root_module(_name)

_root_main = load_root_module("main")
globals().update(_root_main.__dict__)

from .fun_systems import install as _install_fun_systems
from .seasonal import install as _install_seasonal

_install_fun_systems(app)
_install_seasonal(app)
