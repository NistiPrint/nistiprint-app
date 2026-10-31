"""Reprocess confirmed Mercado Livre billing evidence, in transactional pages."""
import argparse
import json
import time
from urllib.error import HTTPError, URLError
from pathlib import Path
from catalog_mcp import call


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--after',type=int,default=0)
    args=parser.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    after=args.after
    with args.output.open('a',encoding='utf-8') as evidence:
        while True:
            for attempt in range(6):
                try:
                    rows=call('execute_sql',{'query':f'select public.gestao_ml_taxa_venda_backfill({int(after)},100) result'})
                    break
                except (HTTPError,URLError) as exc:
                    if isinstance(exc,HTTPError) and exc.code not in {429,500,502,503,504}: raise
                    if attempt==5: raise
                    print(json.dumps({'retry_after_checkpoint':after,'attempt':attempt+1}),flush=True)
                    time.sleep(min(30,2**attempt))
            result=rows[0]['result']
            evidence.write(json.dumps(result,ensure_ascii=False)+'\n');evidence.flush()
            print(json.dumps(result,ensure_ascii=False),flush=True)
            if not result['has_more']:break
            if result['next_after']<=after:raise RuntimeError('Checkpoint stalled')
            after=result['next_after']


if __name__=='__main__':main()
