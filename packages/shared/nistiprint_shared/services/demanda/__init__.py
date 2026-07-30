"""Production demand management services with lazy public exports."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .collections import DemandaCollectionsService
    from .core import DemandaCoreService
    from .items import DemandaItemsService
    from .status import DemandaStatusService

_EXPORT_MODULES = {
    "DemandaCoreService": ".core",
    "DemandaItemsService": ".items",
    "DemandaCollectionsService": ".collections",
    "DemandaStatusService": ".status",
}

__all__ = [
    "DemandaCoreService",
    "DemandaItemsService",
    "DemandaCollectionsService",
    "DemandaStatusService",
]


def __getattr__(name: str):
    """Load services only when accessed to avoid package import cycles."""
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
