param(
  [int]$MaxIterations = 20,
  [string]$AgentCmd = $env:AGENT_CMD,
  [string]$AgentArgs = $env:AGENT_ARGS,
  [string]$AgentPromptFlag = $env:AGENT_PROMPT_FLAG
)

if (-not $AgentCmd) {
  $AgentCmd = "codex"
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$promptFile = Join-Path $root ".ralph\prompt.md"
$progressFile = Join-Path $root ".ralph\progress.md"
$lastMessageFile = Join-Path $root ".ralph\last_message.txt"

$argsArray = @()
if ($AgentArgs) {
  $argsArray = $AgentArgs -split " "
} else {
  $argsArray = @(
    "exec",
    "-",
    "--skip-git-repo-check",
    "--dangerously-bypass-approvals-and-sandbox",
    "-C",
    $root,
    "--output-last-message",
    $lastMessageFile
  )
}

for ($i = 1; $i -le $MaxIterations; $i++) {
  Write-Host "Iteration $i"
  $donePattern = "Promise Complete|<promise>DONE</promise>"

  if (!(Test-Path $promptFile)) {
    throw "Missing prompt file: $promptFile"
  }

  $promptText = Get-Content $promptFile -Raw

  if ($AgentPromptFlag) {
    & $AgentCmd @argsArray $AgentPromptFlag $promptText
  } else {
    $promptText | & $AgentCmd @argsArray
  }

  if (Test-Path $progressFile) {
    if (Select-String -Path $progressFile -Pattern $donePattern -Quiet) {
      Write-Host "Job Done"
      break
    }
  }

  if (Test-Path $lastMessageFile) {
    if (Select-String -Path $lastMessageFile -Pattern $donePattern -Quiet) {
      Write-Host "Job Done"
      break
    }
  }
}
