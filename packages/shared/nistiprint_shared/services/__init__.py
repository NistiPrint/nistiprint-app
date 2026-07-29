"""Shared services package with lazy submodule loading."""
import importlib


def __getattr__(name):
    """Load a requested service without initializing every integration."""
    compatibility = {
        "supabase_storage_service": ("supabase_storage_service", "supabase_storage_service"),
        "conta_bling_service": ("conta_bling_service", "conta_bling_service"),
        "BlingClient": ("bling.bling_client", "BlingClient"),
    }
    if name in compatibility:
        module_name, attribute = compatibility[name]
        value = getattr(importlib.import_module(f".{module_name}", package=__package__), attribute)
        globals()[name] = value
        return value
    try:
        module = importlib.import_module(f".{name}", package=__package__)
    except ModuleNotFoundError as exc:
        if exc.name == f"{__package__}.{name}":
            raise AttributeError(name) from exc
        raise
    globals()[name] = module
    return module
