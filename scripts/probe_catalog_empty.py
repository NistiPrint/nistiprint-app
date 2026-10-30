"""Inspect only the empty-page shape for the Shopee catalog collector."""
import subprocess
import base64
from pathlib import Path

program = '''
import json,logging
from dotenv import load_dotenv
load_dotenv('/opt/nistiprint/.env');logging.disable(logging.CRITICAL)
from nistiprint_shared.database.supabase_db_service import supabase_db
from nistiprint_shared.services.credential_resolver_service import credential_resolver_service
import types,sys,base64
name='nistiprint_shared.services.platform_drivers.shopee_catalog'
shopee_catalog=types.ModuleType(name);shopee_catalog.__package__='nistiprint_shared.services.platform_drivers';sys.modules[name]=shopee_catalog
exec(compile(base64.b64decode(SOURCE),'<catalog_adapter>','exec'),shopee_catalog.__dict__)
account=supabase_db.table('installed_integrations').select('*').eq('id',6).execute().data[0]
account=credential_resolver_service.hydrate_integration(account)
for status,offset in (('BANNED',0),('DELETED',5)):
 r=shopee_catalog._get(account,'/api/v2/product/get_item_list',{'offset':offset,'page_size':5,'item_status':status})
 print(json.dumps({'status':status,'offset':offset,'ok':r.ok,'error':r.error_type,'response':r.value}),flush=True)
'''
source=Path(__file__).resolve().parents[1]/'packages/shared/nistiprint_shared/services/platform_drivers/shopee_catalog.py'
program='SOURCE='+repr(base64.b64encode(source.read_bytes()).decode())+'\n'+program
raise SystemExit(subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-i',r'C:\Users\LENOVO\.ssh\legobre','root@app.nistiprint.neolabs.com.br','cd /opt/nistiprint && .venv/bin/python -'],input=program.encode()).returncode)
