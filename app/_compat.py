import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent


def load_root_module(name):
    """Load a root-level legacy module under a private app package name.

    The production image keeps the original modules at /app while FastAPI is
    started as ``app.main``.  Loading legacy modules under ``app._legacy_*``
    preserves their relative imports without colliding with public wrappers
    such as ``app.db``.
    """
    full_name = f"app._legacy_{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]

    path = ROOT / f"{name}.py"
    if not path.is_file():
        raise FileNotFoundError(f"Legacy module is missing from the image: {path}")

    spec = importlib.util.spec_from_file_location(full_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create an import spec for {path}")

    module = importlib.util.module_from_spec(spec)
    module.__package__ = "app"
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module
