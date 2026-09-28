# Publicar o agente local para download

O agente e o portal têm endereços diferentes:

- `http://localhost:8181/health` responde **no computador do cliente** e mostra a versão instalada.
- `https://app.nistiprint.neolabs.com.br/api/v2/local-agent/releases/latest.json` responde **no servidor** e indica a versão disponível.
- `https://app.nistiprint.neolabs.com.br/api/v2/local-agent/releases/NistiPrintAgent-1.1.0.exe` entrega o instalável dessa versão.

A página **Configurações → Agente local** consulta o manifesto e oferece o botão de download para qualquer usuário autenticado. As rotas de release são públicas para que o agente consiga consultá-las sem sessão do navegador.

## Antes de enviar o EXE: publicar o código da API

Enviar apenas `latest.json` e o EXE ao VPS não cria a rota HTTP. A rota está em
`apps/api/routes/local_agent_releases.py` e precisa ser registrada em
`apps/api/main.py`. Inclua esses arquivos no commit da funcionalidade, faça push
para `main` e execute o deploy. O `deploy.sh` usa `git reset --hard origin/main`:
uma edição feita somente no servidor é descartada no próximo deploy.

Depois do deploy, confirme no VPS que o arquivo da rota existe:

```bash
test -f /opt/nistiprint/apps/api/routes/local_agent_releases.py && echo 'rota presente'
```

Se `rota presente` não aparecer, o código ainda não chegou ao VPS. O
`apps/api/main.py` deste repositório pode conter outras alterações em andamento;
revise o diff antes de criar um commit para não publicar mudanças não relacionadas.

## 1. Preparar o servidor (uma vez)

No VPS Ubuntu, como usuário com acesso administrativo, crie um diretório **fora do checkout Git**. O deploy usa `git reset --hard`, então o release não deve depender de arquivos no repositório.

```bash
sudo install -d -o nistiprint -g nistiprint -m 755 /opt/nistiprint-agent-releases
sudo -u nistiprint nano /opt/nistiprint/.env
```

Acrescente uma linha ao `.env`:

```dotenv
NISTIPRINT_AGENT_RELEASE_DIR=/opt/nistiprint-agent-releases
```

A unidade `nistiprint-api.service` lê esse arquivo via `EnvironmentFile`. Após o código da rota chegar ao servidor, reinicie apenas a API:

```bash
sudo systemctl restart nistiprint-api.service
```

Antes de publicar a primeira versão, `latest.json` retornará 404. Isso é esperado: ainda não há arquivo no diretório.

## 2. Gerar uma nova versão no Windows

Na máquina de desenvolvimento, a partir de `apps\local_agent`:

```powershell
.\setup_agent.bat
```

Atualize `VERSION` em `version.py`, por exemplo, de `1.1.0` para `1.2.0`. Depois execute:

Se o agente de desenvolvimento estiver rodando diretamente de `dist`, encerre-o pela bandeja antes do build para liberar o arquivo.

```powershell
.\build_agent.bat
.\publish_release.ps1 -ReleaseDirectory C:\releases\nistiprint-agent -BaseUrl https://app.nistiprint.neolabs.com.br
```

O resultado é `C:\releases\nistiprint-agent\NistiPrintAgent-1.2.0.exe` e `latest.json`. O manifesto contém a versão, a URL do EXE e o SHA-256 calculado do arquivo copiado. Gere cada release com uma versão nova; não substitua o EXE de uma versão antiga.

## 3. Enviar os arquivos para o VPS

Exemplo com OpenSSH no PowerShell, usando a conta `nistiprint` que possui o diretório. Troque `vps.exemplo.com` pelo host SSH real:

```powershell
scp C:\releases\nistiprint-agent\NistiPrintAgent-1.2.0.exe nistiprint@vps.exemplo.com:/opt/nistiprint-agent-releases/
scp C:\releases\nistiprint-agent\latest.json nistiprint@vps.exemplo.com:/opt/nistiprint-agent-releases/latest.json.tmp
ssh nistiprint@vps.exemplo.com "mv /opt/nistiprint-agent-releases/latest.json.tmp /opt/nistiprint-agent-releases/latest.json"
```

Envie **o EXE primeiro e o manifesto por último**. Se sua conta SSH não for `nistiprint`, envie para sua pasta pessoal e mova os arquivos no servidor com a conta autorizada. Mantenha os EXEs antigos no diretório para que downloads já iniciados terminem.

O `latest.json` é publicado por último para que o portal nunca anuncie um EXE ainda ausente. O renomeio no VPS evita que uma consulta receba um manifesto parcialmente transferido.

## 4. Verificar a publicação

```bash
curl -fsS https://app.nistiprint.neolabs.com.br/api/v2/local-agent/releases/latest.json
curl -I https://app.nistiprint.neolabs.com.br/api/v2/local-agent/releases/NistiPrintAgent-1.2.0.exe
```

O primeiro comando deve mostrar `version`, `url` e `sha256`; o segundo deve retornar `200`. Abra **Configurações → Agente local** no portal e baixe o EXE. No Windows, execute-o e consulte `http://localhost:8181/health`; o campo `version` deve mostrar a versão publicada.

Se o manifesto retornar 404, confira `NISTIPRINT_AGENT_RELEASE_DIR`, as permissões de leitura da API e a presença de `latest.json`. Se o portal mostrar a versão, mas o download falhar, confira o nome e a permissão do EXE. O agente registra falhas de atualização em `%LOCALAPPDATA%\NistiPrint\agent.log`.

Para separar um erro da API de um erro no proxy, execute **no VPS**:

```bash
curl -i http://127.0.0.1:8080/api/v2/local-agent/releases/latest.json
```

Se a API local retornar 200 e o domínio público retornar 404, confira a Custom
Location `/api` no nginx-proxy-manager. Se ambos retornarem 404, confira primeiro
o código publicado, depois a variável `NISTIPRINT_AGENT_RELEASE_DIR` no `.env`
e a presença do arquivo no diretório configurado. Reinicie
`nistiprint-api.service` após alterar o `.env`.

Uma instalação antiga, feita por simples cópia do EXE, exige a troca manual inicial pelo primeiro EXE que contém o atualizador. Depois disso, o cliente poderá confirmar as próximas atualizações no portal ou na bandeja do Windows.
