param(
    [Parameter(Mandatory=$true)][string]$ReleaseDirectory,
    [Parameter(Mandatory=$true)][string]$BaseUrl,
    [string]$ExecutablePath
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$version = (& "$here\.venv\Scripts\python.exe" -c "from version import VERSION; print(VERSION)").Trim()
$source = if ($ExecutablePath) { $ExecutablePath } else { Join-Path $here 'dist\NistiPrintAgent.exe' }
if (-not (Test-Path -LiteralPath $source)) { throw 'Execute build_agent.bat antes de publicar.' }
if (-not $BaseUrl.StartsWith('https://')) { throw 'BaseUrl deve usar HTTPS.' }
New-Item -ItemType Directory -Path $ReleaseDirectory -Force | Out-Null
$filename = "NistiPrintAgent-$version.exe"
$destination = Join-Path $ReleaseDirectory $filename
Copy-Item -LiteralPath $source -Destination $destination -Force
$digest = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    version = $version
    url = "$($BaseUrl.TrimEnd('/'))/api/v2/local-agent/releases/$filename"
    sha256 = $digest
}
$temporary = Join-Path $ReleaseDirectory 'latest.json.tmp'
[System.IO.File]::WriteAllText($temporary, ($manifest | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
Move-Item -LiteralPath $temporary -Destination (Join-Path $ReleaseDirectory 'latest.json') -Force
Write-Output "Publicado $filename com SHA-256 $digest"
