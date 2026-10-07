"""Which names each part of the game reads from the shared app.main interface.

Feature modules in app/ receive app.main as `m` and read `m.<name>`; the game modules in app/game read `main.<name>`.
tests/contracts/main_dependencies.json records exactly those names per file, and tests/test_main_dependencies.py fails
when the code and the record differ, so a new dependency on app.main is always a deliberate choice. The aim is for
the record to shrink: systems import what they need from the module that defines it (docs/architecture.md).

    python -m scripts.main_dependencies          show the current map and how far each file is from explicit imports
    python -m scripts.main_dependencies --write  update the record after a deliberate change
"""
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / 'tests' / 'contracts' / 'main_dependencies.json'
SKIP = {'main.py', 'runtime.py', '__init__.py'}


def _names(path, alias):
    """Attribute names read from `alias` (m or main) in one file, from its syntax tree."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == alias}


def current(main_names):
    """{file: sorted names} for every file that reads app.main. Only names app.main really offers count, so a local
    variable that happens to be called m (a regex match, say) is not mistaken for it."""
    found = {}
    files = [(p, 'm') for p in sorted((ROOT / 'app').glob('*.py')) if p.name not in SKIP]
    files += [(p, 'main') for p in sorted((ROOT / 'app' / 'game').glob('*.py')) if p.name not in SKIP]
    for path, alias in files:
        names = sorted(n for n in _names(path, alias) if n in main_names)
        # self.m / c.m (an object holding app.main) count too
        tree = ast.parse(path.read_text(encoding='utf-8'))
        names = sorted(set(names) | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Attribute)
                                     and n.value.attr == 'm' and n.attr in main_names})
        if names:
            found[str(path.relative_to(ROOT))] = names
    return found


def recorded():
    return json.loads(RECORD.read_text(encoding='utf-8'))


def main(argv):
    import os
    os.environ.setdefault('AUTO_EVENTS_ENABLED', 'false')
    from app import main as m
    now = current(set(vars(m)))
    if '--write' in argv:
        RECORD.write_text(json.dumps(now, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        print(f'Recorded {sum(map(len, now.values()))} names in {len(now)} files.')
        return
    for path, names in sorted(now.items(), key=lambda kv: -len(kv[1])):
        print(f'{len(names):4}  {path}')
    print(f'{sum(map(len, now.values()))} names in {len(now)} files.')


if __name__ == '__main__':
    main(sys.argv[1:])
