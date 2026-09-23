from ._compat import load_root_module

globals().update(load_root_module("commands").__dict__)
