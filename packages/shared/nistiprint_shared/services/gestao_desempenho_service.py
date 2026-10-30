"""Read-only analytical breakdown over canonical order and item facts."""


class GestaoDesempenhoService:
    def __init__(self, db):
        self.db = db

    def report(self, start, end, filters, group_by, limit=100, offset=0, sort='sales', direction='desc'):
        return self.db.rpc('gestao_desempenho', {
            'p_start': start.isoformat(), 'p_end': end.isoformat(), 'p_filters': filters,
            'p_group_by': group_by, 'p_limit': limit, 'p_offset': offset,
            'p_sort': sort, 'p_direction': direction,
        }).execute().data
