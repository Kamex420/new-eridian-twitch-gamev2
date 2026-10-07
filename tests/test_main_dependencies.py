"""Every system's dependencies on the shared app.main interface are recorded (scripts/main_dependencies.py), so they
only change on purpose, and the systems converted to explicit imports keep working on their own."""
import os
import subprocess
import sys
from pathlib import Path
import pytest
from test_colony import m
from scripts import main_dependencies as deps

ROOT = Path(__file__).resolve().parents[1]
# Systems that import what they need instead of reading app.main (docs/architecture.md, "Dependencies on app.main").
EXPLICIT = ('halloween', 'readable_names')


def test_the_record_matches_the_code():
    now, was = deps.current(set(vars(m))), deps.recorded()
    added = {f: sorted(set(now.get(f, [])) - set(was.get(f, []))) for f in now}
    added = {f: n for f, n in added.items() if n}
    removed = {f: sorted(set(was.get(f, [])) - set(now.get(f, []))) for f in was}
    removed = {f: n for f, n in removed.items() if n}
    assert not added, ('These now read app.main: ' + str(added) + '. Import them from the module that defines them '
                       '(docs/architecture.md); if one really has to come through app.main, run '
                       'python -m scripts.main_dependencies --write and say why in the commit.')
    assert not removed, ('These no longer read app.main: ' + str(removed) + '. Good: run '
                         'python -m scripts.main_dependencies --write so the record shrinks too.')


@pytest.mark.parametrize('name', EXPLICIT)
def test_a_converted_system_reads_nothing_from_app_main(name):
    assert f'app/{name}.py' not in deps.current(set(vars(m)))


@pytest.mark.parametrize('name', EXPLICIT)
def test_a_converted_system_still_imports_on_its_own(name, tmp_path):
    """The game loads these systems while it starts, so they import game modules inside their functions; a top-level
    import from app.game would make importing them first loop back into the half-loaded game."""
    env = os.environ | {'DATABASE_URL': 'sqlite:///' + str(tmp_path / 'g.db'), 'AUTO_EVENTS_ENABLED': 'false',
                        'PYTHONPATH': os.pathsep.join([str(ROOT)] + sys.path)}
    code = f'import app.{name}; import app.main; assert app.main.{name} is app.{name}'
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-1500:]
