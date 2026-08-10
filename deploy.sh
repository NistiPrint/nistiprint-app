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
# purelib e o diretorio real de instalacao do venv; site.getsitepackages()[0]
# pode apontar para o do sistema quando o venv herda site-packages.
SITE_PACKAGES="$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
RESIDUOS="$(find "$SITE_PACKAGES" -maxdepth 1 -name '~*' 2>/dev/null | wc -l)"
if [ "$RESIDUOS" -gt 0 ]; then
    echo "  removendo $RESIDUOS residuo(s) em $SITE_PACKAGES"
    find "$SITE_PACKAGES" -maxdepth 1 -name '~*' -exec rm -rf {} + 2>/dev/null || true
else
    echo "  nenhum residuo em $SITE_PACKAGES"
fi

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

# O backend sobe ANTES do frontend de proposito. O build do frontend e a etapa
# mais fragil do deploy (memoria, rede, lockfile) e ja impediu correcao de
# backend de chegar em producao por dias. Se ele falhar agora, o backend ja
# esta atualizado e o frontend continua servindo o build anterior.
echo "→ restart services (backend)"
for svc in nistiprint-api nistiprint-worker nistiprint-beat; do
    sudo /bin/systemctl restart "$svc"
done

if [ "${SKIP_FRONTEND:-0}" = "1" ]; then
    echo "→ frontend build IGNORADO (SKIP_FRONTEND=1)"
else
    echo "→ frontend build"
    echo "  memoria disponivel: $(free -m | awk '/^Mem:/{print $7"MB"}')"
    (
        cd apps/frontend
        # Sem --silent: quando o build morre, a saida e a unica pista do motivo.
        npm ci --no-audit --no-fund
        # Vite/Rollup estouram o heap padrao do Node em VPS pequena; o teto
        # explicito evita o kill silencioso no meio do bundle.
        NODE_OPTIONS="--max-old-space-size=${NODE_HEAP_MB:-2048}" npm run build
    )
fi

echo "✓ deploy $(git rev-parse --short HEAD) ok"
echo "  shared: $(git log -1 --format=%h -- packages/shared) | api: $(systemctl is-active nistiprint-api) | worker: $(systemctl is-active nistiprint-worker)"
