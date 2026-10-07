"""The few values that change on app.main while the game runs, read at call time.

Tests swap the clock (monkeypatch.setattr(m, 'now', ...)) and some settings, a world merge changes the main world,
and votes.install wraps project_contribute. A system that imported one of these directly would keep the old one, so
systems that otherwise import what they need read these here instead. Add an accessor when a converted system needs
another one; docs/architecture.md lists them all.
"""


def _main():
    from . import main
    return main


def now():
    """The game clock: app.main.now(), which tests may replace."""
    return _main().now()
