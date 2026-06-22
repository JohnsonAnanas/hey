# run_collector.ps1 — lance le collecteur EN BOUCLE (redemarre s'il tombe). Toujours actif.
# Lancer detache (survit a Claude / a la fermeture du terminal) :
#   Start-Process powershell -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File "<chemin>\run_collector.ps1"' -WindowStyle Hidden
# Arret : fermer le process powershell correspondant (Get-Process powershell) ou le python collector.py.
$ErrorActionPreference = "Continue"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $dir ".venv\Scripts\python.exe"
$script = Join-Path $dir "collector.py"
$logDir = Join-Path $dir "data\collected"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "launcher.log"
while ($true) {
  "$(Get-Date -Format o) launch collector" | Out-File -Append -Encoding utf8 $log
  & $py $script --interval 1200 --pages 10 --min-liq 100000 --min-vol 20000
  "$(Get-Date -Format o) collector sorti (code=$LASTEXITCODE) -> redemarrage dans 30s" | Out-File -Append -Encoding utf8 $log
  Start-Sleep -Seconds 30
}
