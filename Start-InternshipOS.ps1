param([switch]$Setup,[switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if ($Setup -or -not (Test-Path -LiteralPath 'backend/.venv/Scripts/python.exe')) {
    python -m venv backend/.venv
    & 'backend/.venv/Scripts/python.exe' -m pip install -r backend/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Backend dependency setup failed.' }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.11 -m venv backend/.jobspy-venv
        if ($LASTEXITCODE -eq 0) {
            & 'backend/.jobspy-venv/Scripts/python.exe' -m pip install -r backend/requirements-jobspy.txt
        } else { Write-Warning 'Optional JobSpy needs Python 3.11/3.12. Direct ATS collection still works.' }
    }
}
if (-not (Test-Path -LiteralPath 'frontend/node_modules')) {
    Push-Location -LiteralPath 'frontend'
    npm ci
    Pop-Location
}
$env:PYTHONPATH = Join-Path $taskRoot 'backend'
$env:APP_DATA_DIR = Join-Path $taskRoot 'data'
$env:SCHEDULER_ENABLED = 'true'
if (Test-Path -LiteralPath 'backend/.jobspy-venv/Scripts/python.exe') { $env:JOBSPY_PYTHON = Join-Path $taskRoot 'backend/.jobspy-venv/Scripts/python.exe' }
foreach ($taskPort in @(8000,5173)) {
    if (Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue) { throw "Port $taskPort is in use. The app may already be running at http://127.0.0.1:5173." }
}
New-Item -ItemType Directory -Path (Join-Path $taskRoot 'data') -Force | Out-Null
$taskPython = Join-Path $taskRoot 'backend/.venv/Scripts/python.exe'
$taskApi = Start-Process -FilePath $taskPython -ArgumentList @('-m','uvicorn','internshipos.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRoot 'data/api.log') -RedirectStandardError (Join-Path $taskRoot 'data/api-error.log')
$taskUi = Start-Process -FilePath 'node.exe' -ArgumentList @('node_modules/vite/bin/vite.js','--host','127.0.0.1','--port','5173') -WorkingDirectory (Join-Path $taskRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRoot 'data/ui.log') -RedirectStandardError (Join-Path $taskRoot 'data/ui-error.log')
@{api=$taskApi.Id;frontend=$taskUi.Id} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRoot 'data/processes.json')
Write-Host 'InternshipOS is starting at http://127.0.0.1:5173. Collection continues in the background.'
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:5173' }
