$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [string]$Exe,
        [string[]]$ArgList
    )
    Write-Host ("> {0} {1}" -f $Exe, ($ArgList -join " "))
    & $Exe @ArgList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Exe $($ArgList -join ' ')"
    }
}

$root = Join-Path $env:TEMP ("skillos_smoke_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $root | Out-Null

Invoke-Checked "poetry" @("run", "skillos", "add-skill", "travel/search_flights", "--root", $root)
Invoke-Checked "poetry" @("run", "skillos", "run", "Find flights to Sochi", "--root", $root)
Invoke-Checked "poetry" @("run", "skillos", "run", "Find flights to Sochi", "--root", $root, "--debug", "--trace")
Invoke-Checked "poetry" @("run", "skillos", "run", "Find flights to Sochi", "--root", $root, "--mode", "pipeline")
Invoke-Checked "poetry" @("run", "skillos", "pipeline", "run", "--root", $root, "--step", "travel/search_flights", "--payload", "ok")
Invoke-Checked "poetry" @("run", "skillos", "validate", "--root", $root)
Invoke-Checked "poetry" @(
    "run",
    "skillos",
    "deprecate-skill",
    "travel/search_flights",
    "--root",
    $root,
    "--reason",
    "use travel/search_hotels",
    "--replacement",
    "travel/search_hotels"
)
Invoke-Checked "poetry" @(
    "run",
    "skillos",
    "undeprecate-skill",
    "travel/search_flights",
    "--root",
    $root
)

Write-Host "Smoke checks completed."
