$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m p1_platform
if ($LASTEXITCODE -ne 0) { throw 'Project execution failed' }
python -m pytest tests p1_platform -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python scripts/independent_verify.py
if ($LASTEXITCODE -ne 0) { throw 'Independent verification failed' }
python scripts/verify_p1_integration.py
if ($LASTEXITCODE -ne 0) { throw 'P1 integration verification failed' }
python scripts/manual_checks.py
if ($LASTEXITCODE -ne 0) { throw 'Small-sample verification failed' }
python report/build_report.py
if ($LASTEXITCODE -ne 0) { throw 'Report generation failed' }
