from ._compat import load_root_module

globals().update(load_root_module("seedlings").__dict__)
