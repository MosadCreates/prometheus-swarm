$ProjectDir = "C:\Users\moham\OneDrive\Desktop\prometheus-swarm"
$Venv = "$ProjectDir\.venv-litellm\Scripts\Activate.ps1"

# Go to project
Set-Location $ProjectDir

# Activate LiteLLM environment
& $Venv

# Required for Anthropic → Chat Completions translation
$env:LITELLM_USE_CHAT_COMPLETIONS_URL_FOR_ANTHROPIC_MESSAGES = "true"

# Claude Code configuration
$env:ANTHROPIC_BASE_URL = "http://localhost:4000"
$env:ANTHROPIC_API_KEY = "anything"
$env:ANTHROPIC_AUTH_TOKEN = ""
$env:ANTHROPIC_MODEL = "qwen3.8-max-free"
$env:ANTHROPIC_SMALL_FAST_MODEL = "qwen3.8-max-free"

# Start LiteLLM in a separate PowerShell window
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$ProjectDir'; & '$Venv'; `$env:LITELLM_USE_CHAT_COMPLETIONS_URL_FOR_ANTHROPIC_MESSAGES='true'; litellm --config .\litellm_config.yaml --port 4000"
)

# Give LiteLLM a moment to start
Start-Sleep -Seconds 4

# Start Claude Code
claude