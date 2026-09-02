# Agente local NistiPrint

## Preparar ambiente

Execute `setup_agent.bat`. O script cria `.venv` e instala as dependências,
incluindo o ícone da bandeja (`pystray` e `Pillow`).

## Executar para diagnóstico

Execute `run_agent.bat`. As mensagens aparecem no console e também ficam em:

```text
%LOCALAPPDATA%\NistiPrint\agent.log
```

## Executar silenciosamente

Para o uso normal, execute `start_agent_quiet.bat`. Ele usa o executável
empacotado, quando disponível, ou `pythonw.exe`, sem abrir console.

Não use `run_agent.bat` no atalho de inicialização do Windows; esse arquivo é
somente para diagnóstico.

## Gerar executável

Execute `build_agent.bat`. O resultado será:

```text
dist\NistiPrintAgent.exe
```

Esse executável não abre janela de console e fica disponível na bandeja do
Windows. O menu da bandeja permite verificar o agente e encerrá-lo.

O ícone usado pela bandeja e pelo executável é `icon.ico`. Para trocar a marca,
substitua esse arquivo e execute `build_agent.bat` novamente. O arquivo deve
preferencialmente conter tamanhos 16, 32, 48 e 256 pixels.

## Origens permitidas

O agente escuta só em loopback e autoriza por **allowlist de Origin**. Todas as
rotas, menos `/health`, exigem que o navegador informe uma origem que esteja na
lista; requisição sem `Origin` (curl, script) é recusada.

Configure `NISTIPRINT_AGENT_ORIGINS` com as URLs do app, separadas por vírgula:

```powershell
setx NISTIPRINT_AGENT_ORIGINS "https://app.nistiprint.com.br,http://localhost:5173"
```

**Isto precisa ser configurado em produção.** O default cobre apenas o
desenvolvimento local (`localhost:5173`); sem a variável, o navegador bloqueia
as chamadas do app publicado e a seção de artes locais aparece vazia.

Não há token: um segredo gerado por máquina não tem como bater com um valor
único embutido no build do frontend, e um valor único embutido no build seria um
segredo publicado para qualquer visitante — variáveis `VITE_` vão para o JS
servido.

Para testar antes de gerar o executável:

```powershell
.venv\Scripts\python.exe agent.py
```