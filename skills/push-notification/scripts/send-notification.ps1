[CmdletBinding()]
param(
    [string]$Recipient,
    [string]$Subject = 'self_modifying_bot task completed',
    [string]$Body = 'The requested self_modifying_bot task is complete.',
    [switch]$Status,
    [switch]$WhatIf
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

if (-not (Test-Path -LiteralPath $settingsPath) -or -not (Test-Path -LiteralPath $secretPath)) {
    throw 'Push service is not configured. Run start-push-service.ps1 first.'
}

$settings = Get-Content -Raw -LiteralPath $settingsPath | ConvertFrom-Json
if ($Status) {
    Write-Output "Push service is configured for sender $($settings.sender)."
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Recipient) -or $Recipient -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') {
    throw 'Recipient must be supplied as a valid email address with -Recipient.'
}

if ($WhatIf) {
    Write-Output "WhatIf: would send '$Subject' to $Recipient through $($settings.smtpHost):$($settings.smtpPort)."
    exit 0
}

$secureAuthorizationCode = Import-Clixml -LiteralPath $secretPath
$credential = [System.Management.Automation.PSCredential]::new($settings.sender, $secureAuthorizationCode)
$plainAuthorizationCode = $credential.GetNetworkCredential().Password

$message = [System.Net.Mail.MailMessage]::new()
$client = [System.Net.Mail.SmtpClient]::new([string]$settings.smtpHost, [int]$settings.smtpPort)
try {
    $message.From = [System.Net.Mail.MailAddress]::new([string]$settings.sender)
    [void]$message.To.Add($Recipient)
    $message.Subject = $Subject
    $message.SubjectEncoding = [System.Text.Encoding]::UTF8
    $message.Body = $Body
    $message.BodyEncoding = [System.Text.Encoding]::UTF8
    $message.IsBodyHtml = $false

    $client.EnableSsl = $true
    $client.UseDefaultCredentials = $false
    $client.Credentials = [System.Net.NetworkCredential]::new([string]$settings.sender, $plainAuthorizationCode)
    $client.Timeout = 30000
    $client.Send($message)
    Write-Output "Notification accepted by QQ SMTP for $Recipient."
}
finally {
    $plainAuthorizationCode = $null
    $message.Dispose()
    $client.Dispose()
}
