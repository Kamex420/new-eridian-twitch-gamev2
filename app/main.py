"""HTTP and Discord adapters for the New Eridian game domain.

This module composes persistence, command handling and the ASGI application.
Domain modules under app/ own needs, item identities and queue transactions.
Stable routes and storage identifiers preserve existing clients and saves;
see docs/architecture.md for boundaries and compatibility decisions.
"""

# The code of this module lives in app/main_parts/, one file per topic (NN_name.py, run in file-name order).
# Each part runs inside this module's own namespace, exactly as when everything was one 8,000-line file:
# every name is still app.main.<name>, feature modules still reach it as m.<name>, tests can still monkeypatch it,
# and a later part uses what an earlier part defined. To change something, edit its part; to add a topic, add a
# numbered file. Tracebacks name the part file and its own line numbers.
import pathlib as _pathlib


def _run_parts():
    for _part in sorted((_pathlib.Path(__file__).parent / 'main_parts').glob('[0-9][0-9]_*.py')):
        exec(compile(_part.read_text(encoding='utf-8'), str(_part), 'exec', dont_inherit=True), globals())


_run_parts()
