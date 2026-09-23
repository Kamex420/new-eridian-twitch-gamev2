from ._compat import load_root_module

globals().update(load_root_module("events").__dict__)
