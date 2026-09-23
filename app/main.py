
"""Expose one application module so wrappers and handlers share live globals."""
import sys
from ._compat import load_root_module

for _name in (
    "db", "models", "needs", "occupations", "competencies", "settlement",
    "seedlings", "events", "progression", "commands", "migrations",
):
    load_root_module(_name)

_root_main = load_root_module("main")
from .fun_systems import install as _install_fun_systems
from .seasonal import install as _install_seasonal
_install_fun_systems(_root_main.app)
_install_seasonal(_root_main.app)
sys.modules[__name__] = _root_main
