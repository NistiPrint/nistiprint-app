"""Remove definitivamente os arquivos legados de arte do Supabase Storage.

Execute antes da migration 20260831140000_remover_artes_e_impressao_nuvem.sql.
O bucket precisa ser informado explicitamente para evitar apagar arquivos de
outros recursos.
"""

import argparse
import os
from nistiprint_shared.database.supabase_db_service import supabase_db


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--confirm', action='store_true')
    args = parser.parse_args()
    if not args.confirm:
        raise SystemExit('Use --confirm para confirmar a exclusão definitiva.')
    rows = supabase_db.table('product_artworks').select('filename').execute().data or []
    paths = [row['filename'] for row in rows if row.get('filename')]
    storage = supabase_db.client.storage.from_(args.bucket)
    for start in range(0, len(paths), 1000):
        storage.remove(paths[start:start + 1000])
    print(f'{len(paths)} arquivos removidos do bucket {args.bucket}.')


if __name__ == '__main__':
    main()