param(
    [int]$Port = 8000,
    [ValidateSet("deepseek_harness", "hermes_agent", "echo")]
    [string]$Harness,
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $projectDir ".venv\Scripts\python.exe"
$pushSkillDirectory = Join-Path $env:USERPROFILE ".codex\skills\push-notification\scripts"
$pushStatusScript = Join-Path $pushSkillDirectory "send-notification.ps1"
$pushServiceScript = Join-Path $pushSkillDirectory "start-push-service.ps1"
$port = $Port
$deepSeekRoot = "L:\WORKSPACE\deepseek-harness"
$deepSeekRuntimeCarrier = Join-Path $deepSeekRoot "python\sdk-runtime\src\deepseek_harness_runtime\runtime\node\node_modules\@deepseek-ai\dsh-sdk-jsonrpc-demo\lib\packaged-bin.js"
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
if (-not $pnpmCommand) { $pnpmCommand = Get-Command corepack -ErrorAction SilentlyContinue }

$availableHarnesses = @("echo")
if (Test-Path -LiteralPath "L:\WORKSPACE\deepseek-harness") {
    $availableHarnesses = @("deepseek_harness") + $availableHarnesses
}
if (Test-Path -LiteralPath "L:\WORKSPACE\hermes-agent") {
    $availableHarnesses = @("hermes_agent") + $availableHarnesses
}

if (-not $Harness) {
    Write-Host "Available Harnesses:"
    for ($index = 0; $index -lt $availableHarnesses.Count; $index++) {
        Write-Host "[$($index + 1)] $($availableHarnesses[$index])"
    }
    $selection = Read-Host "Select the default Harness (1-$($availableHarnesses.Count))"
    $selectionNumber = 0
    if (-not [int]::TryParse($selection, [ref]$selectionNumber) -or $selectionNumber -lt 1 -or $selectionNumber -gt $availableHarnesses.Count) {
        throw "Invalid Harness selection. Restart with -Harness deepseek_harness, -Harness hermes_agent, or -Harness echo."
    }
    $Harness = $availableHarnesses[$selectionNumber - 1]
}

$env:BOT_RUNTIME = $Harness
$configPath = Join-Path $env:USERPROFILE ".self_modifying_bot\config.toml"
if (Test-Path -LiteralPath $configPath) {
    $configText = Get-Content -LiteralPath $configPath -Raw
    if ($configText -match '(?m)^runtime\s*=') {
        $configText = [regex]::Replace($configText, '(?m)^runtime\s*=.*$', "runtime = `"$Harness`"")
    } else {
        $configText = $configText.TrimEnd() + "`r`n`r`n[agent]`r`nruntime = `"$Harness`"`r`n"
    }
    [System.IO.File]::WriteAllText($configPath, $configText, [System.Text.UTF8Encoding]::new($false))
}
Write-Host "Selected default Harness: $Harness"

$envPath = Join-Path $env:USERPROFILE ".self_modifying_bot\.env"
if (Test-Path -LiteralPath $envPath) {
    foreach ($settingName in @("DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DEEPSEEK_API_KEY")) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($settingName))) {
            $savedLine = Get-Content -LiteralPath $envPath | Where-Object { $_ -match "^$settingName=(.*)$" } | Select-Object -First 1
            if ($savedLine -match "^$settingName=(.*)$") {
                [Environment]::SetEnvironmentVariable($settingName, $Matches[1], "Process")
            }
        }
    }
}

if ($Harness -eq "deepseek_harness") {
    $needsBuild = $Rebuild -or -not (Test-Path -LiteralPath $deepSeekRuntimeCarrier)
    if ($needsBuild) {
        $buildAnswer = if ($Rebuild) { "Y" } else { Read-Host "DeepSeek Harness runtime is missing. Build it now? [Y/n]" }
        if ([string]::IsNullOrWhiteSpace($buildAnswer)) { $buildAnswer = "Y" }
        if ($buildAnswer -match '^(?i)y(es)?$') {
            if (-not $nodeCommand) { throw "Node.js is required to build DeepSeek Harness. Install Node.js 22.19+ and restart." }
            $nodeVersion = (& $nodeCommand.Source --version).TrimStart('v')
            $nodeMajor = [int]($nodeVersion.Split('.')[0])
            if ($nodeMajor -lt 22) { throw "DeepSeek Harness requires Node.js 22.19+; detected $nodeVersion. Upgrade Node.js and restart." }
            if (-not $pnpmCommand) { throw "pnpm or Corepack is required to build DeepSeek Harness. Install/enable Corepack and restart." }
            $packageManager = $pnpmCommand.Source
            $packageManagerArguments = @()
            if ($pnpmCommand.Name -eq 'corepack.cmd' -or $pnpmCommand.Name -eq 'corepack') {
                $packageManagerArguments = @('pnpm')
            }
            Push-Location $deepSeekRoot
            try {
                if (-not (Test-Path -LiteralPath (Join-Path $deepSeekRoot "node_modules"))) {
                    Write-Host "Installing DeepSeek Harness JavaScript dependencies..."
                    & $packageManager @packageManagerArguments install --frozen-lockfile
                    if ($LASTEXITCODE -ne 0) { throw "DeepSeek Harness dependency installation failed." }
                }
                Write-Host "Building the DeepSeek Harness runtime carrier..."
                & $packageManager @packageManagerArguments exec tsx scripts/build-exe-for-python-sdk.ts --targets=node24-linux-x64
                if ($LASTEXITCODE -ne 0) { throw "DeepSeek Harness runtime build failed." }
                Write-Host "DeepSeek Harness runtime build completed successfully."
            }
            finally { Pop-Location }
        }
    }
    if (-not (Test-Path -LiteralPath $deepSeekRuntimeCarrier)) {
        throw "DeepSeek Harness runtime is unavailable. Use -Harness echo, build it manually, or restart with -Rebuild."
    }
    $env:DSH_RUNTIME_MODE = "node"
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_BASE_URL)) {
        $baseUrl = Read-Host "Enter model Base URL [https://api.deepseek.com]"
        if ([string]::IsNullOrWhiteSpace($baseUrl)) { $baseUrl = "https://api.deepseek.com" }
        $env:DEEPSEEK_BASE_URL = $baseUrl
    }
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_MODEL)) {
        $modelName = Read-Host "Enter model name [deepseek-chat]"
        if ([string]::IsNullOrWhiteSpace($modelName)) { $modelName = "deepseek-chat" }
        $env:DEEPSEEK_MODEL = $modelName
    }
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        $secureKey = Read-Host "Enter model API key (input hidden)" -AsSecureString
        $keyPointer = [IntPtr]::Zero
        try {
            $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
            $deepSeekKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
        }
        finally {
            if ($keyPointer -ne [IntPtr]::Zero) {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
            }
        }
        if ([string]::IsNullOrWhiteSpace($deepSeekKey)) {
            throw "Model API key cannot be empty."
        }
        $env:DEEPSEEK_API_KEY = $deepSeekKey
    }
    $envDirectory = Split-Path -Parent $envPath
    New-Item -ItemType Directory -Path $envDirectory -Force | Out-Null
    $existingEnv = if (Test-Path -LiteralPath $envPath) { Get-Content -LiteralPath $envPath -Raw } else { "" }
    $settings = @{
        "DEEPSEEK_BASE_URL" = $env:DEEPSEEK_BASE_URL
        "DEEPSEEK_MODEL" = $env:DEEPSEEK_MODEL
        "DEEPSEEK_API_KEY" = $env:DEEPSEEK_API_KEY
    }
    foreach ($setting in $settings.GetEnumerator()) {
        $line = "$($setting.Key)=$($setting.Value)"
        if ($existingEnv -match "(?m)^$($setting.Key)=") {
            $existingEnv = [regex]::Replace($existingEnv, "(?m)^$($setting.Key)=.*$", [System.Text.RegularExpressions.MatchEvaluator]{ param($match) $line })
        } else {
            $existingEnv = $existingEnv.TrimEnd() + "`r`n$line`r`n"
        }
    }
    [System.IO.File]::WriteAllText($envPath, $existingEnv, [System.Text.UTF8Encoding]::new($false))
    Write-Host "DeepSeek API key saved to the user configuration directory."
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "Virtual environment not found. Run: py -m venv .venv"
}

if (-not (Test-Path -LiteralPath $pushStatusScript)) {
    throw "Push notification Skill not found: $pushStatusScript"
}

if (-not (Test-Path -LiteralPath $pushServiceScript)) {
    throw "Push notification initializer not found: $pushServiceScript"
}

& powershell -NoProfile -ExecutionPolicy Bypass -File $pushStatusScript -Status 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Push notification is not configured. Starting one-time authorization setup..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $pushServiceScript
}

$connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($connection in $connections) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)"
    if ($process.CommandLine -and $process.CommandLine -match "uvicorn.*app:app") {
        Write-Host "Stopping existing self_modifying_bot process $($connection.OwningProcess)..."
        Stop-Process -Id $connection.OwningProcess -Force
    } else {
        throw "Port $port is occupied by an unrelated process (PID $($connection.OwningProcess))."
    }
}

$workerProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine -match [regex]::Escape("$projectDir\worker.py")
}
foreach ($process in $workerProcesses) {
    Write-Host "Stopping existing self_modifying_bot worker $($process.ProcessId)..."
    Stop-Process -Id $process.ProcessId -Force
}

Write-Host "Starting self_modifying_bot worker..."
$worker = Start-Process -FilePath $pythonExe -ArgumentList "worker.py" -WorkingDirectory $projectDir -WindowStyle Hidden -PassThru
Write-Host "Worker started with PID $($worker.Id)."

try {
    Write-Host "Starting self_modifying_bot web service on 127.0.0.1:$port..."
    & $pythonExe -m uvicorn app:app --host 127.0.0.1 --port $port
}
finally {
    if ($worker -and -not $worker.HasExited) {
        Write-Host "Stopping self_modifying_bot worker $($worker.Id)..."
        Stop-Process -Id $worker.Id -Force -ErrorAction SilentlyContinue
    }
}
