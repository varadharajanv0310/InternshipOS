$taskFile = Join-Path $PSScriptRoot 'data/processes.json'
if (Test-Path -LiteralPath $taskFile) {
    $taskProcesses = Get-Content -LiteralPath $taskFile -Raw | ConvertFrom-Json
    foreach ($taskProcessId in @($taskProcesses.api,$taskProcesses.frontend)) {
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId" -ErrorAction SilentlyContinue
        if ($taskProcess -and $taskProcess.Name -in @('python.exe','node.exe') -and ($taskProcess.CommandLine -like '*uvicorn internshipos.main:app*' -or $taskProcess.CommandLine -like '*node_modules/vite/bin/vite.js*')) { Stop-Process -Id $taskProcessId }
    }
    Remove-Item -LiteralPath $taskFile
}
