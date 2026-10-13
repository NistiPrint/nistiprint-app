#!/usr/bin/env bash
set -euo pipefail
cd /opt/nistiprint

echo "→ git fetch + reset"
git fetch --prune origin
TARGET_REF="${DEPLOY_REF:-origin/main}"
if ! TARGET_SHA="$(git rev-parse --verify --quiet "${TARGET_REF}^{commit}")"; then
    echo "ERRO: DEPLOY_REF não identifica um commit disponível: $TARGET_REF" >&2
    exit 1
fi
echo "  promovendo $TARGET_REF ($TARGET_SHA)"
git reset --hard "$TARGET_SHA"       # o servidor é runtime; descarta alterações locais
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

if [ "${SKIP_FRONTEND:-0}" != "1" ]; then
    /opt/nistiprint/.venv/bin/python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values

values = dotenv_values(Path('/opt/nistiprint/.env'))
missing = [name for name in ('VITE_SUPABASE_URL', 'SUPABASE_ANON_KEY') if not values.get(name)]
if missing:
    raise SystemExit('Frontend build blocked; configure in /opt/nistiprint/.env: ' + ', '.join(missing))
PY
fi

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
        NODE_OPTIONS="--max-old-space-size=${NODE_HEAP_MB:-2048}" /opt/nistiprint/.venv/bin/python - <<'PY'
import os
import shutil
import subprocess
from pathlib import Path
from dotenv import dotenv_values

frontend = Path.cwd().resolve()
env_file = Path('/opt/nistiprint/.env')
values = dotenv_values(env_file)
url = values.get('VITE_SUPABASE_URL')
anon_key = values.get('SUPABASE_ANON_KEY')
if not url or not anon_key:
    raise SystemExit('VITE_SUPABASE_URL e SUPABASE_ANON_KEY precisam estar em /opt/nistiprint/.env para compilar o frontend')

build_env = os.environ.copy()
build_env['VITE_SUPABASE_URL'] = url
build_env['VITE_SUPABASE_ANON_KEY'] = anon_key

# Build away from the directory served by Caddy. A successful Vite exit alone
# does not prove that it embedded the Supabase settings in the client bundle.
staged = frontend / '.dist-next'
current = frontend / 'dist'
previous = frontend / '.dist-previous'
subprocess.run(['npm', 'run', 'build', '--', '--outDir', str(staged)],
               cwd=frontend, env=build_env, check=True)

scripts = list((staged / 'assets').glob('*.js'))
missing_artifacts = []
if not (staged / 'index.html').is_file():
    missing_artifacts.append(str(staged / 'index.html'))
if not scripts:
    missing_artifacts.append(str(staged / 'assets/*.js'))
if missing_artifacts:
    raise SystemExit(
        'Frontend build incomplete; missing ' + ', '.join(missing_artifacts) +
        '; current published build preserved'
    )
bundles = [script.read_text(encoding='utf-8') for script in scripts]
missing = []
if not any(url in bundle for bundle in bundles):
    missing.append('VITE_SUPABASE_URL')
if not any(anon_key in bundle for bundle in bundles):
    missing.append('VITE_SUPABASE_ANON_KEY')
if missing:
    raise SystemExit(
        'Frontend build lacks ' + ' and '.join(missing) +
        '; current published build preserved'
    )

if previous.exists():
    shutil.rmtree(previous)
if current.exists():
    current.rename(previous)
try:
    staged.rename(current)
except Exception:
    if previous.exists():
        previous.rename(current)
    raise
print('  frontend build validated and published')
PY
    )
fi

# Só reinicia os serviços depois de dependências e build do frontend estarem
# prontos. Assim, falhas de instalação ou compilação não promovem o backend.
echo "→ restart services (backend)"
# Descoberto dinamicamente, e não por lista fixa: todos os papéis de ingest
# também precisam carregar o código candidato. O template puro não é executável.
mapfile -t SERVICOS < <(
    {
        systemctl list-units --type=service --all --plain --no-legend 'nistiprint-*' 2>/dev/null \
            | awk '{ print $1 }'
        systemctl list-unit-files --type=service --plain --no-legend 'nistiprint-*' 2>/dev/null \
            | awk '$2 == "enabled" { print $1 }'
    } | awk '!/@\.service$/ && NF' | sort -u
)
if [ "${#SERVICOS[@]}" -eq 0 ]; then
    echo "  AVISO: nenhum nistiprint-*.service encontrado; usando lista fixa" >&2
    SERVICOS=(nistiprint-api.service nistiprint-worker.service nistiprint-beat.service)
fi
for svc in "${SERVICOS[@]}"; do
    echo "  reiniciando $svc"
    sudo /bin/systemctl restart "$svc"
done

echo "✓ deploy $(git rev-parse --short HEAD) ok"
echo "  shared: $(git log -1 --format=%h -- packages/shared)"
for svc in "${SERVICOS[@]}"; do
    echo "  $svc: $(systemctl is-active "$svc")"
done
