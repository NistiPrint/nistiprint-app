# Agente local NistiPrint

## Preparar ambiente

Execute `setup_agent.bat`. O script cria `.venv` e instala as dependências,
incluindo o ícone da bandeja (`pystray` e `Pillow`).

## Executar para diagnóstico

Execute `run_agent.bat`. As mensagens aparecem no console e também ficam em:

```text
%LOCALAPPDATA%\NistiPrint\agent.log
```

## Consultar o agente

Com o agente em execução, abra `http://127.0.0.1:8181/dashboard` no próprio
computador ou use **Ver painel do agente** no ícone da bandeja. O painel mostra
status, versão, estado da atualização, mapeamentos e as 200 linhas mais recentes
do log. Os dados são atualizados a cada 10 segundos; o painel não oferece ações.
Se `NISTIPRINT_AGENT_PORT` estiver configurada, use essa porta no endereço.

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
Windows. O menu da bandeja permite verificar o agente e encerrá-lo. Se uma
instância já estiver aberta, iniciar o executável encerra a anterior e inicia
uma única bandeja com a versão escolhida. O agente também substitui versões
anteriores que ainda não implementam essa troca.

O agente aceita impressão assistida de PDFs e consulta a fila local do Windows.
O padrão permite `https://app.nistiprint.neolabs.com.br` e as origens locais de
desenvolvimento. Para outro domínio, defina `NISTIPRINT_ALLOWED_ORIGINS` com a
origem da aplicação web e reinicie o agente.

O ícone usado pela bandeja e pelo executável é `icon.ico`. Para trocar a marca,
substitua esse arquivo e execute `build_agent.bat` novamente. O arquivo deve
preferencialmente conter tamanhos 16, 32, 48 e 256 pixels.

Para testar antes de gerar o executável:

```powershell
.venv\Scripts\python.exe agent.py
```

## Atualizações nas máquinas dos clientes

O executável informa sua versão e o estado da atualização em `/health`.
Ele consulta a cada hora o manifesto HTTPS em
`https://app.nistiprint.neolabs.com.br/api/v2/local-agent/releases/latest.json`.
Use `NISTIPRINT_AGENT_MANIFEST_URL` para apontar outro ambiente. A aplicação
mostra um aviso de nova versão e a bandeja oferece **Verificar atualizações**
e **Atualizar agente**. A instalação só começa após o clique do operador.

No servidor, configure `NISTIPRINT_AGENT_RELEASE_DIR` com um diretório persistente
e legível pela API. Após gerar o EXE, publique com:

```powershell
.\publish_release.ps1 -ReleaseDirectory C:\releases\nistiprint-agent -BaseUrl https://app.nistiprint.neolabs.com.br
```

Copie o conteúdo desse diretório para o servidor configurado. O script cria
`NistiPrintAgent-<versão>.exe` e `latest.json` com URL e SHA-256. Publique o
executável antes do manifesto. Aumente `VERSION` em `version.py` a cada release.
Mantenha versões anteriores disponíveis enquanto houver clientes nelas.

Para migrar uma instalação antiga feita por cópia do EXE, substitua o arquivo
manualmente uma única vez pela primeira versão com atualizador. A pasta do EXE
precisa permitir gravação pelo usuário que executa o agente. Os dados em
`%LOCALAPPDATA%\NistiPrint` continuam na mesma pasta; a atualização não os move.
Falhas e restaurações ficam registradas em `agent.log`. O arquivo
`NistiPrintAgent.exe.previous` guarda a versão anterior após uma atualização
bem-sucedida.

Se o agente encerrar durante a atualização e o novo EXE mostrar uma mensagem
de segurança sobre processo pai, use a versão `1.1.5` ou superior. O auxiliar
de instalação inicia o novo processo com o ambiente do PyInstaller reiniciado;
releases novas são geradas com PyInstaller 6.22.3 ou superior.
Como o auxiliar que executa a troca vem do EXE antigo, uma máquina que já
apresentou esse erro precisa receber a `1.1.5` manualmente uma vez: encerre o
agente, substitua `NistiPrintAgent.exe` pelo novo arquivo e execute-o. O mapa
de impressoras e o log permanecem em `%LOCALAPPDATA%\NistiPrint`.

O procedimento completo de configuração do servidor, publicação e teste está
em `docs/operacoes/agente-local.md` na raiz do repositório.
