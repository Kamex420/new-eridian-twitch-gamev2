import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent

def load_root_module(name):
    full_name = f"app.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    path = ROOT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(full_name, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "app"
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module
