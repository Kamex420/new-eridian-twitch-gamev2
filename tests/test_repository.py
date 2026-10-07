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


def test_the_game_is_split_into_modules_that_app_main_offers():
    """app/game holds one module per topic; app.main imports them in order and offers their names (docs/architecture.md)."""
    import importlib
    from app import game
    files={p.stem for p in (ROOT/'app'/'game').glob('*.py')}-{'__init__'}
    assert set(game.MODULES)==files and len(files)>10
    assert len((ROOT/'app'/'main.py').read_text().splitlines())<60
    events=importlib.import_module('app.game.colony_events')
    assert m.work_counts is events.work_counts and events.work_counts.__module__=='app.game.colony_events'
    assert m.SessionLocal is importlib.import_module('app.game.base').SessionLocal


def test_settings_changed_on_app_main_reach_the_game_modules(monkeypatch):
    """Tests and feature modules change some names on app.main while the game runs; the modules read those through it."""
    monkeypatch.setattr(m,'AUTO_EVENTS_ENABLED',False)
    from app.game import colony_events
    with m.SessionLocal() as db:
        assert colony_events.maybe_start_auto_event(db,m.world(db,'test'))==''
    later=m.now()+m.timedelta(days=3)
    monkeypatch.setattr(m,'now',lambda:later)
    from app.game import players
    with m.SessionLocal() as db:
        assert players.player(db,'test','twitch','zz','Zed')[1].last_seen==later


def test_registrar_reads_function_names_from_the_game_modules():
    from scripts.register_discord_commands import main_functions
    names=main_functions()
    assert {'item_command_menu','work_counts','discord_interactions'}<=names
    assert names>={n for n,v in vars(m).items() if isinstance(v,type(main_functions)) and v.__name__==n
                   and v.__module__.startswith('app.game.')}
