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

$root = Join-Path $env:TEMP ("skillos_smoke_pg_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $root | Out-Null

if (-not $env:SKILLOS_POSTGRES_DSN) {
    if ($env:DATABASE_URL) {
        $env:SKILLOS_POSTGRES_DSN = $env:DATABASE_URL
    } else {
        $env:SKILLOS_POSTGRES_DSN = "postgresql://postgres:postgres@localhost:5432/skillos"
    }
}

$env:SKILLOS_STORAGE_BACKEND = "postgres"
$env:SKILLOS_POSTGRES_SCHEMA = "skillos_smoke_" + [guid]::NewGuid().ToString("N")
if (-not $env:SKILLOS_TENANT_ID) {
    $env:SKILLOS_TENANT_ID = "smoke"
}
if (-not $env:SKILLOS_APPROVAL_TOKEN) {
    $env:SKILLOS_APPROVAL_TOKEN = "smoke-token"
}
$approvalToken = $env:SKILLOS_APPROVAL_TOKEN

$contextPath = Join-Path $root "context.json"
@'
[
  {
    "source": "calendar",
    "summary": "test window"
  }
]
'@ | Set-Content -Path $contextPath -Encoding UTF8

Invoke-Checked "poetry" @("run", "skillos", "add-skill", "travel/search_flights", "--root", $root)
Invoke-Checked "poetry" @("run", "skillos", "run", "Find flights to Sochi", "--root", $root)
Invoke-Checked "poetry" @(
    "run",
    "skillos",
    "schedule",
    "add",
    "travel/search_flights",
    "--run-at",
    (Get-Date).ToUniversalTime().AddMinutes(-5).ToString("o"),
    "--root",
    $root,
    "--approval",
    "approved",
    "--approval-token",
    $approvalToken,
    "--role",
    "admin"
)
Invoke-Checked "poetry" @(
    "run",
    "skillos",
    "job",
    "enqueue",
    "travel/search_flights",
    "--root",
    $root,
    "--payload",
    "ok",
    "--max-retries",
    "1"
)
Invoke-Checked "poetry" @(
    "run",
    "skillos",
    "feedback",
    "travel/search_flights",
    "--expected-skill-id",
    "travel/search_flights",
    "--root",
    $root
)
Invoke-Checked "poetry" @(
    "run",
    "skillos",
    "optimize",
    "travel/search_flights",
    "--variant",
    "v1",
    "--variant",
    "v2",
    "--result",
    "v1:success",
    "--result",
    "v2:failure",
    "--root",
    $root
)
Invoke-Checked "poetry" @(
    "run",
    "skillos",
    "suggestions",
    "run",
    "--context",
    $contextPath,
    "--root",
    $root
)
Invoke-Checked "poetry" @("run", "skillos", "validate", "--root", $root)

Write-Host "Postgres smoke checks completed."
