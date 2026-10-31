"""Run one bounded read-only replication page using local code in memory."""
import argparse
import base64
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',required=True)
    parser.add_argument('--identity',required=True)
    parser.add_argument('--account',type=int,required=True)
    parser.add_argument('--all-pages',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/'packages/shared/nistiprint_shared/services'
    sources={name:base64.b64encode((root/path).read_bytes()).decode() for name,path in {
        'order_replication':'marketplace_order_replication.py','ml':'platform_drivers/mercadolivre.py',
        'shopee':'platform_drivers/shopee.py'}.items()}
    program='SOURCES='+repr(sources)+'\nACCOUNT='+repr(args.account)+'\nALL_PAGES='+repr(args.all_pages)+'\n'+r'''
import base64,json,logging,types
from dotenv import load_dotenv
load_dotenv('/opt/nistiprint/.env');logging.disable(logging.CRITICAL)
from nistiprint_shared.database.supabase_db_service import supabase_db as db
from nistiprint_shared.services.platform_drivers import mercadolivre,shopee
def load(name,package):
 module=types.ModuleType('pilot_'+name);module.__package__=package
 exec(compile(base64.b64decode(SOURCES[name]),'<reviewed-pilot>','exec'),module.__dict__)
 return module
mercadolivre.get_orders_list=load('ml','nistiprint_shared.services.platform_drivers').get_orders_list
shopee.get_orders_list_page=load('shopee','nistiprint_shared.services.platform_drivers').get_orders_list_page
service=load('order_replication','nistiprint_shared.services').OrderReplication(db)
while True:
 result=service.run_page(ACCOUNT)
 print(json.dumps(result),flush=True)
 if not ALL_PAGES or result.get('status')!='available':break
'''
    command=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',args.identity,args.host,'cd /opt/nistiprint && .venv/bin/python -']
    result=subprocess.run(command,input=program,text=True,check=False)
    if result.returncode:raise SystemExit(result.returncode)


if __name__=='__main__':main()
