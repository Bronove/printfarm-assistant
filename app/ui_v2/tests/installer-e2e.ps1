$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $root
$installer = Get-ChildItem -LiteralPath (Join-Path $root "installer_dist") `
    -Filter "*.exe" -File | Select-Object -First 1
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd("\") + "\"
$target = Join-Path $env:TEMP (
    "tuozhu-installer-e2e-" + [guid]::NewGuid().ToString("N")
)
$target = [IO.Path]::GetFullPath($target)

if (-not $installer) {
    throw "Installer executable was not found."
}
if (-not $target.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Temporary install target is outside the temp directory."
}

function Start-FrozenProcess {
    param(
        [string]$FilePath,
        [string]$Arguments
    )
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $FilePath
    $info.Arguments = $Arguments
    $info.UseShellExecute = $false
    return [System.Diagnostics.Process]::Start($info)
}

try {
    $smoke = Start-FrozenProcess -FilePath $installer.FullName -Arguments "--selftest"
    if (-not $smoke.WaitForExit(20000)) {
        $smoke.Kill()
        throw "Installer UI self-test timed out."
    }
    if ($smoke.ExitCode -ne 0) {
        throw "Installer UI self-test failed with exit code $($smoke.ExitCode)."
    }

    $started = Get-Date
    $installArgs = (
        '--auto --target "{0}" --no-shortcuts --no-registry' -f $target
    )
    $process = Start-FrozenProcess -FilePath $installer.FullName -Arguments $installArgs
    $deadline = (Get-Date).AddSeconds(120)
    do {
        Start-Sleep -Seconds 1
        $installedExe = Get-ChildItem -LiteralPath $target -Filter "*.exe" `
            -File -ErrorAction SilentlyContinue | Select-Object -First 1
        $installerStillRunning = Get-Process -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Path -eq $installer.FullName -and
                $_.StartTime -ge $started.AddSeconds(-2)
            }
    } while (
        (-not $installedExe -or $installerStillRunning) `
        -and (Get-Date) -lt $deadline
    )
    if (-not $installedExe) {
        throw "Installer did not create an application executable."
    }

    $env:TUOZHU_E2E_EXE = $installedExe.FullName
    $env:TUOZHU_E2E_CONFIG = Join-Path $target "config.json"
    & npm.cmd run test:e2e:packaged
    if ($LASTEXITCODE -ne 0) {
        throw "Installed application failed the real user-path test."
    }
} finally {
    Remove-Item Env:TUOZHU_E2E_EXE -ErrorAction SilentlyContinue
    Remove-Item Env:TUOZHU_E2E_CONFIG -ErrorAction SilentlyContinue
    if ([IO.Directory]::Exists($target)) {
        [IO.Directory]::Delete($target, $true)
    }
}

Write-Output "Installer end-to-end test passed."
