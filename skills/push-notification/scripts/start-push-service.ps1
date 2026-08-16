[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$botHome = if ($env:SELF_MODIFYING_BOT_HOME) {
    $env:SELF_MODIFYING_BOT_HOME
} else {
    Join-Path ([Environment]::GetFolderPath('UserProfile')) '.self_modifying_bot'
}
$configDirectory = Join-Path $botHome 'push-notification'
$settingsPath = Join-Path $configDirectory 'settings.json'
$secretPath = Join-Path $configDirectory 'qq-smtp-auth.xml'

if (-not $Force -and (Test-Path -LiteralPath $settingsPath) -and (Test-Path -LiteralPath $secretPath)) {
    $settings = Get-Content -Raw -LiteralPath $settingsPath | ConvertFrom-Json
    Write-Output "Push service is already configured for sender $($settings.sender)."
    exit 0
}

$sender = (Read-Host 'QQ sender email address').Trim()
if ($sender -notmatch '^[^@\s]+@qq\.com$') {
    throw 'Sender must be a valid @qq.com email address.'
}

$authorizationCode = Read-Host 'QQ SMTP authorization code (input is hidden)' -AsSecureString
if ($authorizationCode.Length -eq 0) {
    throw 'Authorization code cannot be empty.'
}

New-Item -ItemType Directory -Force -Path $configDirectory | Out-Null
@{
    sender = $sender
    smtpHost = 'smtp.qq.com'
    smtpPort = 587
} | ConvertTo-Json | Set-Content -LiteralPath $settingsPath -Encoding UTF8
$authorizationCode | Export-Clixml -LiteralPath $secretPath

Write-Output "Push service configured for sender $sender. The authorization code is encrypted for the current Windows user."
