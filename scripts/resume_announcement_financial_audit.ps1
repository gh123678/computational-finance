# Resume the approved data audit using the Windows profile that saved the credential.
$ErrorActionPreference = 'Stop'
$financialAuditRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $financialAuditRoot
try {
    & '.\.venv_ml_risk\Scripts\python.exe' '.\scripts\announcement_financial_audit.py' download
    if ($LASTEXITCODE -ne 0) { throw 'Financial audit stopped; cached responses and failures are preserved. No model or trading rule was changed.' }
} finally { Pop-Location }
