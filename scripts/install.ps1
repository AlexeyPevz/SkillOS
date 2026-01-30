Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    pipx install skillos
} else {
    python -m pip install --user skillos
}

Write-Host "Installed. Try: skillos --help"
