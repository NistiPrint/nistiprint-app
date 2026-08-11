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

echo "→ verificando permissoes do venv"
# Rodar pip/git como root no servidor deixa artefatos root-owned no venv, e o
# deploy seguinte (que roda como o usuario da action) morre com um OSError
# cru no meio da instalacao. Detectar antes torna a causa obvia.
ALHEIOS="$(find "$SITE_PACKAGES" ! -user "$(id -un)" 2>/dev/null | head -5)"
if [ -n "$ALHEIOS" ]; then
    echo "ERRO: arquivos do venv nao pertencem a $(id -un):" >&2
    echo "$ALHEIOS" | sed 's/^/  /' >&2
    echo "Corrija com: sudo chown -R $(id -un):$(id -gn) $(pwd)" >&2
    exit 1
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
# Descoberto dinamicamente, e nao por lista fixa: o worker de ingest confiavel
# ficou de fora da lista antiga e seguiu servindo codigo velho da memoria por
# dias, enquanto api/worker/beat reiniciavam e o deploy parecia bem-sucedido.
# Qualquer nistiprint-*.service novo entra aqui sozinho.
mapfile -t SERVICOS < <(
    {
        # list-units traz as INSTANCIAS de template (nistiprint-ingest@orders),
        # que sao o que de fato roda. --all para incluir as paradas no momento.
        systemctl list-units --type=service --all --plain --no-legend 'nistiprint-*' 2>/dev/null \
            | awk '{ print $1 }'
        # list-unit-files pega as habilitadas que nem foram carregadas ainda.
        systemctl list-unit-files --type=service --plain --no-legend 'nistiprint-*' 2>/dev/null \
            | awk '$2 == "enabled" { print $1 }'
    } | awk '!/@\.service$/ && NF' | sort -u
    # O template puro (`nistiprint-ingest@.service`) e descartado de proposito:
    # nao e uma unidade executavel, so o molde das instancias.
)
if [ "${#SERVICOS[@]}" -eq 0 ]; then
    echo "  AVISO: nenhum nistiprint-*.service encontrado; usando lista fixa" >&2
    SERVICOS=(nistiprint-api.service nistiprint-worker.service nistiprint-beat.service)
fi
for svc in "${SERVICOS[@]}"; do
    echo "  reiniciando $svc"
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
echo "  shared: $(git log -1 --format=%h -- packages/shared)"
for svc in "${SERVICOS[@]}"; do
    echo "  $svc: $(systemctl is-active "$svc")"
done
