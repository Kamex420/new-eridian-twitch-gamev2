"""Convert a system in app/ from reading app.main (`m.<name>`) to explicit imports (docs/architecture.md).

    python -m scripts.explicit_imports app/seed_content.py [more files]

Each `m.<name>` becomes the name itself, imported from where it is defined:
- names that change while the game runs (app/runtime.py SWAPPABLE) are read as runtime.<name>;
- game names are imported inside the function that uses them (the game loads these systems while it starts, so a
  top-level import from app.game would loop); a name the function also uses for something else is read through its
  module instead (players.world(...));
- models, sessions, sqlalchemy and leaf modules are imported at the top.
Function signatures keep their `m` parameter, so callers do not change. Run the tests and
python -m scripts.main_dependencies --write afterwards.
"""
import ast
import collections
import os
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_MODULES = {'app.models': '.models', 'app.db': '.db', 'app.settlement': '.settlement'}


IMPORTED = {}   # name -> (app module, real name) for names the game modules import from elsewhere in app/


def game_definitions():
    from app.game import MODULES
    found = {}
    for name in MODULES:
        tree = ast.parse((ROOT / 'app' / 'game' / f'{name}.py').read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 2 and node.module:
                for a in node.names:
                    IMPORTED.setdefault(a.asname or a.name, (node.module, a.name))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.setdefault(node.name, name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                for x in ast.walk(node):
                    if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                        found.setdefault(x.id, name)
    return found


def source_of(main, runtime, defs, name):
    """('runtime'|'game'|'module'|'top', detail)."""
    if name in runtime.SWAPPABLE:
        return 'runtime', None
    obj = getattr(main, name)
    if isinstance(obj, types.ModuleType):
        return 'module', obj.__name__
    module = getattr(obj, '__module__', '') if isinstance(obj, (types.FunctionType, type)) else ''
    if module.startswith('app.game.'):
        return 'game', module.split('.')[-1]
    if module in TOP_MODULES:
        real = obj.__name__
        return 'top', (f'from {TOP_MODULES[module]} import {real}' + (f' as {name}' if real != name else ''))
    if name in defs:
        return 'game', defs[name]
    if module.startswith('app.') or name in IMPORTED:              # from another part of app/: import it lazily
        mod, real = IMPORTED.get(name, (module[4:], getattr(obj, '__name__', name)))
        return 'app', (f'from .{mod} import', real if real == name else f'{real} as {name}')
    if module.startswith('sqlalchemy'):
        return 'top', f'from sqlalchemy import {name}'
    raise SystemExit(f'Do not know where {name} comes from ({module or type(obj).__name__}); convert it by hand.')


def bound_in(fn):
    names = {a.arg for a in ast.walk(fn.args) if isinstance(a, ast.arg)}
    for x in ast.walk(fn):
        if isinstance(x, ast.Name) and isinstance(x.ctx, (ast.Store, ast.Del)):
            names.add(x.id)
        elif isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and x is not fn:
            names.add(x.name)
        elif isinstance(x, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split('.')[0] for a in x.names)
    return names


def convert(path, main, runtime, defs):
    src = path.read_text(encoding='utf-8')
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    module_names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    module_names |= {x.id for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign)) for x in ast.walk(n)
                     if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
    module_names |= {(a.asname or a.name).split('.')[0] for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    self_name = 'app.' + path.stem
    edits, inserts, top = [], [], set()
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        if any(fn in ast.walk(outer) and outer is not fn for outer in ast.walk(tree)
               if isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef))):
            continue                                  # nested: handled with its top-level function
        refs = [x for x in ast.walk(fn) if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
                and x.value.id == 'm' and x.attr in vars(main) and isinstance(x.ctx, ast.Load)]   # m.X = ... stays
        if not refs:
            continue
        local = bound_in(fn) | module_names
        imports = collections.defaultdict(set)
        for x in refs:
            kind, detail = source_of(main, runtime, defs, x.attr)
            if kind == 'runtime':
                if 'runtime' in bound_in(fn):
                    raise SystemExit(f'{path.name}: {fn.name} has its own variable called runtime; rename it first.')
                text = 'runtime.' + x.attr
                top.add('from . import runtime')
            elif kind == 'module' and detail == self_name:
                if lines[x.lineno - 1].encode('utf-8')[x.end_col_offset:x.end_col_offset + 1] == b'.':
                    edits.append((x, None))          # m.seed_content.find_item inside seed_content: find_item
                    continue
                text = 'sys.modules[__name__]'       # the module itself, passed along
                top.add('import sys')
            elif kind == 'module':
                text = detail.split('.')[-1]
                if detail.startswith('app.'):
                    imports['from . import'].add(text)
                else:
                    top.add(f'import {detail}')
            elif kind == 'top':
                text = x.attr
                top.add(detail)
            elif kind == 'app':
                text = x.attr
                imports[detail[0]].add(detail[1])
            elif x.attr in local:                     # the function (or this module) uses the name for something else
                text = f'{detail}.{x.attr}'
                imports['from .game import'].add(detail)
            else:
                text = x.attr
                imports[f'from .game.{detail} import'].add(x.attr)
            edits.append((x, text))
        body0 = fn.body[0]
        if isinstance(body0, ast.Expr) and isinstance(getattr(body0, 'value', None), ast.Constant) and isinstance(body0.value.value, str):
            after = body0.end_lineno                  # after the docstring
            indent = re.match(r'\s*', lines[body0.lineno - 1]).group(0)
            inserts.append((after, None, indent, imports))
        elif body0.lineno == fn.lineno:               # def f(m): return ... on one line
            inserts.append((body0.lineno, body0.col_offset, ' ' * (fn.col_offset + 4), imports))
        else:
            first = min([body0.lineno] + [d.lineno for d in getattr(body0, 'decorator_list', [])])   # above its decorators
            indent = re.match(r'\s*', lines[first - 1]).group(0)
            inserts.append((first - 1, None, indent, imports))
    # attribute edits (right to left per line), then import insertions (bottom up)
    by_line = collections.defaultdict(list)
    for x, text in edits:
        by_line[x.lineno].append((x, text))
    for ln, items in by_line.items():
        raw = lines[ln - 1].encode('utf-8')
        for x, text in sorted(items, key=lambda it: -it[0].col_offset):
            start, end = x.col_offset, x.end_col_offset
            if text is None:                          # drop "m.seed_content." keeping what follows
                tail = raw[end:]
                assert tail.startswith(b'.'), lines[ln - 1]
                raw = raw[:start] + tail[1:]
            else:
                raw = raw[:start] + text.encode('utf-8') + raw[end:]
        lines[ln - 1] = raw.decode('utf-8')
    for ln, col, indent, imports in sorted(inserts, key=lambda i: (-i[0], -(i[1] or 0))):
        block = ''.join(f'{indent}{head} {", ".join(sorted(names))}\n' for head, names in sorted(imports.items()))
        if not block:
            continue
        if col is None:
            lines.insert(ln, block)
        else:                                         # split "def f(m):stmt" into def line + imports + stmt
            raw = lines[ln - 1].encode('utf-8')
            lines[ln - 1] = raw[:col].decode('utf-8').rstrip() + '\n' + block + indent + raw[col:].decode('utf-8')
    text = ''.join(lines)
    if top:
        tree = ast.parse(text)
        have = {ast.unparse(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))}
        new = [t for t in sorted(top) if t not in have]
        last = max((n.end_lineno for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) and n.col_offset == 0), default=0)
        out = text.splitlines(keepends=True)
        out.insert(last, ''.join(t + '\n' for t in new))
        text = ''.join(out)
    ast.parse(text)
    path.write_text(text, encoding='utf-8')
    return len(edits)


if __name__ == '__main__':
    os.environ.setdefault('AUTO_EVENTS_ENABLED', 'false')
    from app import main, runtime
    defs = game_definitions()
    for arg in sys.argv[1:]:
        print(arg, convert(ROOT / arg, main, runtime, defs), 'references converted')
