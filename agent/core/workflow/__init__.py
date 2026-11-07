"""Lazy public exports avoid importing the entire graph from standalone tools."""

from importlib import import_module

_EXPORTS = {
    "AgentOutput": ".state",
    "AgentState": ".state",
    "AgentGraphManager": ".graph_manager",
}
__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(_EXPORTS[name], __name__), name)
    globals()[name] = value
    return value
