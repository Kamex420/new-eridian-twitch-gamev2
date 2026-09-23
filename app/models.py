from ._compat import load_root_module

globals().update(load_root_module("models").__dict__)
