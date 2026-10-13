"""Claims and delivers durable inventory invalidations to authorized SSE users."""

import os
import uuid
from typing import Any

from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.notification_service import notification_service


class EstoqueOutboxService:
    def __init__(self, db=supabase_db, notifications=notification_service):
        self.db = db
        self.notifications = notifications

    def _all(self, table: str, columns: str, configure=None) -> list[dict[str, Any]]:
        rows = []
        start = 0
        while True:
            query = self.db.table(table).select(columns)
            if configure:
                query = configure(query)
            page = self.db.execute_with_retry(query.range(start, start + 499)).data or []
            rows.extend(page)
            if len(page) < 500:
                return rows
            start += 500

    def authorized_user_ids(self) -> list[str]:
        resources = self.db.execute_with_retry(
            self.db.table('recursos').select('id').eq('nome', 'estoque').limit(1)
        ).data or []
        resource_ids = [row['id'] for row in resources]
        readable_sectors = set()
        if resource_ids:
            permissions = self._all(
                'permissoes_setor', 'setor_id',
                lambda q: q.in_('recurso_id', resource_ids).eq('pode_ler', True),
            )
            readable_sectors = {row['setor_id'] for row in permissions}

        users = self._all(
            'usuarios', 'id,setor_id,is_admin', lambda q: q.eq('ativo', True)
        )
        return sorted({
            str(row['id']) for row in users
            if row.get('is_admin') or row.get('setor_id') in readable_sectors
        })

    def process_batch(self, *, limit: int = 50, worker_id: str | None = None) -> dict[str, int]:
        worker_id = worker_id or f"estoque-outbox:{os.getpid()}:{uuid.uuid4()}"
        response = self.db.rpc('claim_estoque_eventos_outbox', {
            'p_worker_id': worker_id,
            'p_limit': max(1, min(int(limit), 200)),
            'p_lease_seconds': 60,
        }).execute()
        events = response.data or []
        stats = {'claimed': len(events), 'delivered': 0, 'failed': 0}
        user_ids = self.authorized_user_ids() if events else []
        for row in events:
            event_id = row['id']
            token = row['lease_token']
            try:
                payload = {
                    'type': 'stock.updated',
                    'event_id': event_id,
                    **(row.get('payload') or {}),
                }
                for user_id in user_ids:
                    if self.notifications.publish_user_event(user_id, payload) is False:
                        raise RuntimeError(f'Falha ao publicar evento SSE para usuário {user_id}.')
                done = self.db.rpc('finish_estoque_evento_outbox', {
                    'p_event_id': event_id,
                    'p_lease_token': token,
                    'p_error': None,
                }).execute()
                if done.data is False:
                    raise RuntimeError('Lease da outbox expirou antes da confirmação.')
                stats['delivered'] += 1
            except Exception as exc:
                try:
                    self.db.rpc('finish_estoque_evento_outbox', {
                        'p_event_id': event_id,
                        'p_lease_token': token,
                        'p_error': str(exc)[:4000],
                    }).execute()
                finally:
                    stats['failed'] += 1
        return stats


estoque_outbox_service = EstoqueOutboxService()
