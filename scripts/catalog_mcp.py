"""Supabase MCP HTTP transport for reviewed catalog SQL and schema evidence.

No database credentials are read. The endpoint is the configured local MCP proxy.
"""
import argparse
import json
import os
from pathlib import Path
import re
from urllib.request import Request, urlopen


def call(name, arguments):
    endpoint = os.environ.get('SUPABASE_MCP_URL', 'http://127.0.0.1:18000/mcp?features=docs%2Cdatabase%2Cdebugging%2Cdevelopment')
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                       'params': {'name': name, 'arguments': arguments}}).encode()
    request = Request(endpoint, data=body, headers={
        'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
    with urlopen(request, timeout=60) as response:
        envelope = json.load(response)
    if envelope.get('error'):
        raise RuntimeError(envelope['error'])
    result = envelope['result']
    if result.get('isError'):
        raise RuntimeError(result.get('content'))
    texts = [json.loads(c['text']) for c in result.get('content', []) if c.get('type') == 'text']
    value = texts[0] if len(texts) == 1 else texts
    if isinstance(value, dict) and isinstance(value.get('result'), str):
        match = re.search(r'\n<untrusted-data-[^>]+>\s*(.*?)\s*</untrusted-data-', value['result'], re.S)
        if match:
            return json.loads(match[1])
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', choices=['execute_sql', 'apply_migration', 'get_advisors'])
    parser.add_argument('--file', type=Path)
    parser.add_argument('--query')
    parser.add_argument('--name')
    parser.add_argument('--type', choices=['security', 'performance'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    sql = args.file.read_text(encoding='utf-8') if args.file else args.query
    if args.tool == 'apply_migration':
        if not sql or not args.name:
            parser.error('apply_migration requires --file/--query and --name')
        arguments = {'name': args.name, 'query': sql}
    elif args.tool == 'execute_sql':
        if not sql:
            parser.error('execute_sql requires --file or --query')
        arguments = {'query': sql}
    else:
        arguments = {'type': args.type or 'security'}
    result = call(args.tool, arguments)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered, encoding='utf-8')
        print(json.dumps({'saved':str(args.output)}))
    else:
        print(rendered)
