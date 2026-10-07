"""Regression checks for source ownership and the production image boundary."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from test_colony import m

ROOT=Path(__file__).resolve().parents[1]


def test_models_have_one_canonical_module_identity():
    from app import models,db
    assert m.Player is models.Player
    assert m.Base is db.Base
    assert m.Player.__module__=='app.models'
    assert not any(name.startswith('app._legacy_') for name in sys.modules)


def test_registrar_catalog_does_not_initialize_a_database(tmp_path):
    database=tmp_path/'registrar.db'
    result=subprocess.run([sys.executable,'-m','scripts.register_discord_commands','--dry-run'],cwd=ROOT,
        env=os.environ|{'DATABASE_URL':'sqlite:///'+str(database)},capture_output=True,text=True,check=True)
    import json
    commands=json.loads(result.stdout)
    assert {'mine','queue'}<={row['name'] for row in commands}
    assert not database.exists()


def test_app_imports_from_only_container_source_inputs(tmp_path):
    # Matches Docker COPY inputs: no root implementation files or test imports.
    shutil.copytree(ROOT/'app',tmp_path/'app',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT/'scripts',tmp_path/'scripts',ignore=shutil.ignore_patterns('__pycache__'))
    code="from app.main import app; from app.task_queue import TaskQueue; paths={r.path for r in app.routes}; assert {'/health','/api/v1/queue','/api/v1/mining','/api/v1/fun/daily'}<=paths; assert TaskQueue.__table__.name=='task_queues_v1'"
    subprocess.run([sys.executable,'-c',code],cwd=tmp_path,
        env=os.environ|{'DATABASE_URL':'sqlite:///'+str(tmp_path/'game.db'),'PYTHONPATH':str(tmp_path)},capture_output=True,text=True,check=True)


def test_main_runs_its_topic_parts_inside_one_namespace():
    """app/main.py is split into app/main_parts/NN_topic.py; the parts share app.main's namespace (docs/architecture.md)."""
    import re
    parts=sorted((ROOT/'app'/'main_parts').glob('*.py'))
    assert len(parts)>10 and all(re.fullmatch(r'\d\d_[a-z_]+\.py',p.name) for p in parts)
    assert len((ROOT/'app'/'main.py').read_text().splitlines())<40
    assert m.work_counts.__module__=='app.main' and m.work_counts.__globals__ is vars(m)
    assert m.work_counts.__code__.co_filename.endswith('07_colony_events.py')     # tracebacks name the part


def test_registrar_reads_functions_from_the_parts():
    from scripts.register_discord_commands import main_functions
    names=main_functions()
    assert {'item_command_menu','work_counts','discord_interactions'}<=names
    assert names>={n for n,v in vars(m).items() if callable(v) and getattr(v,'__module__','')=='app.main' and getattr(v,'__name__','')==n
                   and not isinstance(v,type)}
