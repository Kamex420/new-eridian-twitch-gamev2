from ._compat import load_root_module
for _name in ("db","models","needs","occupations","competencies","settlement","seedlings","events","progression","commands","migrations"):
    load_root_module(_name)
_globals = globals()
with open(__import__('pathlib').Path(__file__).resolve().parent.parent / 'main.py', encoding='utf-8') as _f:
    exec(compile(_f.read(), str(__import__('pathlib').Path(_f.name)), 'exec'), _globals)
from .fun_systems import install as _install_fun_systems
_install_fun_systems(app)
