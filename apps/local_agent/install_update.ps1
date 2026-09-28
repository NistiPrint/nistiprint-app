param(
    [Parameter(Mandatory=$true)][string]$Current,
    [Parameter(Mandatory=$true)][string]$Staged,
    [Parameter(Mandatory=$true)][int]$ProcessId,
    [Parameter(Mandatory=$true)][int]$Port,
    [Parameter(Mandatory=$true)][string]$ExpectedVersion,
    [Parameter(Mandatory=$true)][string]$Log
)

$ErrorActionPreference = 'Stop'
$backup = "$Current.previous"
function Write-UpdateLog([string]$message) {
    Add-Content -LiteralPath $Log -Value "$(Get-Date -Format o) [UPDATE] $message"
}
function Move-WithRetry([string]$source, [string]$destination) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            Move-Item -LiteralPath $source -Destination $destination -ErrorAction Stop
            return
        } catch {
            if ($attempt -eq 29) { throw }
            Start-Sleep -Seconds 1
        }
    }
}

try {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process) { $process.WaitForExit(30000) | Out-Null }
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        throw 'O agente anterior não encerrou em 30 segundos'
    }
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Force }
    Move-WithRetry $Current $backup
    try {
        Move-WithRetry $Staged $Current
        $new = Start-Process -FilePath $Current -PassThru -WindowStyle Hidden
        $healthy = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2
                if ($health.version -eq $ExpectedVersion) { $healthy = $true; break }
            } catch { }
            if ($new.HasExited) { break }
        }
        if (-not $healthy) { throw 'O novo agente não iniciou corretamente' }
        Write-UpdateLog "Atualização para $ExpectedVersion concluída"
    } catch {
        Write-UpdateLog "Instalação falhou: $_. Restaurando versão anterior"
        if ($new -and -not $new.HasExited) { Stop-Process -Id $new.Id -Force }
        if (Test-Path -LiteralPath $Current) { Remove-Item -LiteralPath $Current -Force }
        Move-WithRetry $backup $Current
        Start-Process -FilePath $Current -WindowStyle Hidden | Out-Null
        throw
    }
} catch {
    Write-UpdateLog "Falha na atualização: $_"
    exit 1
}
