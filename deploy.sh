#!/usr/bin/env bash
set -euo pipefail
cd /opt/nistiprint

echo "→ git fetch + reset"
git fetch --prune origin
git reset --hard origin/main          # descarta qualquer mudança local
git clean -fd apps/frontend/node_modules/.cache 2>/dev/null || true

echo "→ limpando residuos de instalacoes interrompidas do pip"
# Quando o pip e interrompido, ele deixa o pacote renomeado com '~' no lugar
# do primeiro caractere (ex.: ~istiprint-shared). Sao inertes, mas poluem
# todo pip install seguinte com WARNING de "invalid distribution".
SITE_PACKAGES="$(.venv/bin/python -c 'import site; print(site.getsitepackages()[0])')"
find "$SITE_PACKAGES" -maxdepth 1 -name '~*' -exec rm -rf {} + 2>/dev/null || true

echo "→ pip install"
.venv/bin/pip install -q -r apps/api/requirements.txt
.venv/bin/pip install -q -r apps/worker/requirements.txt
.venv/bin/pip install -q -e packages/shared

echo "→ verificando instalacao editavel do nistiprint-shared"
# Se o pacote for instalado sem -e (copia em site-packages), as edicoes no
# repo passam a ser ignoradas silenciosamente e o deploy "nao pega".
.venv/bin/python - <<'PY'
import sys
import nistiprint_shared.services.marketplace_adapters as m

esperado = '/opt/nistiprint/packages/shared/'
if not m.__file__.startswith(esperado):
    sys.exit(
        f'ERRO: nistiprint_shared carregado de {m.__file__}, '
        f'e nao de {esperado}. A instalacao nao esta editavel; '
        'rode: .venv/bin/pip install -e packages/shared'
    )
print(f'  ok: {m.__file__}')
PY

echo "→ frontend build"
( cd apps/frontend && npm ci --silent && npm run build )

echo "→ restart services"
for svc in nistiprint-api nistiprint-worker nistiprint-beat; do
    sudo /bin/systemctl restart "$svc"
done

echo "✓ deploy $(git rev-parse --short HEAD) ok"
echo "  shared: $(git log -1 --format=%h -- packages/shared) | api: $(systemctl is-active nistiprint-api) | worker: $(systemctl is-active nistiprint-worker)"
