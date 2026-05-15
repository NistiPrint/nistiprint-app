# Tasks package
# Importa todas as tasks para registro no Celery

from . import eventos_tasks
from . import consolidation_tasks
from . import auto_consolidation_tasks
from . import pedidos_fetch_tasks
# personalizados_tasks está no shared package: nistiprint_shared.services.personalizados_tasks

__all__ = ['eventos_tasks', 'consolidation_tasks', 'auto_consolidation_tasks', 'pedidos_fetch_tasks']
