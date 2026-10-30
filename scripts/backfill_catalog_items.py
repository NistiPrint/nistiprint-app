"""Populate granular facts through MCP HTTP without resolving historical links."""
import argparse
import json
from pathlib import Path
from catalog_mcp import call


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--after', type=int, default=0)
    parser.add_argument('--batch-size', type=int, default=250)
    parser.add_argument('--checkpoint', type=Path, default=Path('temp/catalog-item-backfill.json'))
    args = parser.parse_args()
    after = max(0, args.after)
    if args.checkpoint.exists():
        after = max(after, json.loads(args.checkpoint.read_text())['next_after'])
    processed = 0
    while True:
        rows = call('execute_sql', {'query':f'SELECT public.gestao_backfill_order_item_facts({after},{max(1,min(args.batch_size,500))}) AS result'})
        result = rows[0]['result']
        processed += result['processed']
        after = result['next_after']
        args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
        args.checkpoint.write_text(json.dumps(result), encoding='utf-8')
        print(json.dumps({'processed_this_run':processed,**result}), flush=True)
        if not result['has_more']:
            return


if __name__ == '__main__':
    main()
