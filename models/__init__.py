# Proxy to nistiprint_shared models
try:
    from nistiprint_shared.models import *
except ImportError:
    # Fallback for local development if not installed as package
    try:
        from nistiprint_shared.nistiprint_shared.models import *
    except ImportError:
        pass
