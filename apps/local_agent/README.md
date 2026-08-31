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

Para testar antes de gerar o executável:

```powershell
.venv\Scripts\python.exe agent.py
```