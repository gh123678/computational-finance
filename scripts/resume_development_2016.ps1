# Run from the Windows account that saved .secrets/tushare.dpapi.
# Never prints or writes the credential. Stops immediately on a failed stage.
$ErrorActionPreference = 'Stop'
$researchRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $researchRoot
try {
    python -m quant_research.download --dataset development_2016 --interval 0.4 --workers 12
    if ($LASTEXITCODE -ne 0) { throw '2016 download failed. Review credential/profile or API error; no backtest was started.' }
    python -m quant_research.research --dataset development_2016
    if ($LASTEXITCODE -ne 0) { throw '2016 research stopped. Review the reported data or corporate-action issue before continuing.' }
    python scripts/verify_annual.py --dataset development_2016
    if ($LASTEXITCODE -ne 0) { throw '2016 verification failed. Results must not be treated as verified.' }
    python scripts/compare_development_years.py
    if ($LASTEXITCODE -ne 0) { throw 'Development comparison failed.' }
} finally {
    Pop-Location
}
