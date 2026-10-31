$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $root
$setup = Get-ChildItem -LiteralPath (Join-Path $root "installer_inno") `
    -Filter "*-setup.exe" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
$bambuExe = @(
    (Join-Path $env:ProgramFiles "Bambu Studio\bambu-studio.exe"),
    "D:\Bambu Studio\bambu-studio.exe"
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$tempRoot = [IO.Path]::GetFullPath($env:TEMP).TrimEnd("\") + "\"
$target = Join-Path $env:TEMP (
    "printfarm-inno-e2e-" + [guid]::NewGuid().ToString("N")
)
$target = [IO.Path]::GetFullPath($target)
$initialBambuIds = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -eq $bambuExe } |
        Select-Object -ExpandProperty ProcessId
)

if (-not $setup) {
    throw "Inno Setup package was not found."
}
if (-not $target.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Temporary install target is outside the temp directory."
}

function Get-InstalledApp {
    $candidate = Get-ChildItem -LiteralPath $target -Filter "*.exe" `
        -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne "unins000.exe" } |
        Select-Object -First 1
    return $candidate
}

function Invoke-Setup {
    param([switch]$WithBambu)
    $app = Get-InstalledApp
    if ($app -and -not (Get-CimInstance Win32_Process |
            Where-Object { $_.ExecutablePath -eq $app.FullName })) {
        Start-Process -FilePath $app.FullName -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 2
    }

    if ($WithBambu) {
        $runningBambu = Get-CimInstance Win32_Process |
            Where-Object { $_.ExecutablePath -eq $bambuExe }
        if (-not $runningBambu) {
            Start-Process -FilePath $bambuExe -WindowStyle Hidden | Out-Null
            Start-Sleep -Seconds 3
        }
    }

    $arguments = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/NOICONS",
        "/TASKS=",
        "/DIR=$target"
    )
    $installLog = Join-Path $env:TEMP (
        "printfarm-inno-step-" + [guid]::NewGuid().ToString("N") + ".log"
    )
    $arguments += "/LOG=$installLog"
    $process = Start-Process -FilePath $setup.FullName `
        -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        $detail = if (Test-Path -LiteralPath $installLog) {
            (Get-Content -LiteralPath $installLog -Tail 40) -join [Environment]::NewLine
        } else {
            "Installer log was not created."
        }
        throw "Installer failed with exit code $($process.ExitCode).`n$detail"
    }

    $appCount = @(Get-CimInstance Win32_Process |
        Where-Object {
            $app -and $_.ExecutablePath -eq $app.FullName
        }).Count
    $bambuCount = @(Get-CimInstance Win32_Process |
        Where-Object { $_.ExecutablePath -eq $bambuExe }).Count
    if ($appCount -ne 0) {
        throw "Installer left the previous Assistant process running."
    }
    if ($WithBambu -and $bambuCount -eq 0) {
        throw "Installer closed Bambu Studio."
    }
}

try {
    Invoke-Setup
    $app = Get-InstalledApp
    if (-not $app) {
        throw "Installer did not create the application executable."
    }

    $env:TUOZHU_E2E_EXE = $app.FullName
    & npm.cmd run test:e2e:packaged
    if ($LASTEXITCODE -ne 0) {
        throw "Installed application failed the real user-path test."
    }

    Invoke-Setup
    Invoke-Setup -WithBambu

    $uninstaller = Join-Path $target "unins000.exe"
    if (-not (Test-Path -LiteralPath $uninstaller)) {
        throw "Inno Setup uninstaller was not created."
    }
    $uninstallRun = Start-Process -FilePath $uninstaller `
        -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" `
        -Wait -PassThru -WindowStyle Hidden
    if ($uninstallRun.ExitCode -ne 0) {
        throw "Uninstaller failed with exit code $($uninstallRun.ExitCode)."
    }
    if (Get-InstalledApp) {
        throw "Application executable remained after uninstall."
    }
    $bambuCountAfterUninstall = @(
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -eq $bambuExe }
    ).Count
    if ($bambuCountAfterUninstall -lt 1) {
        throw "Uninstaller closed Bambu Studio."
    }
} finally {
    Remove-Item Env:TUOZHU_E2E_EXE -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.ExecutablePath -and
            (
                $_.ExecutablePath.StartsWith($target, [StringComparison]::OrdinalIgnoreCase) -or
                (
                    $_.ExecutablePath -eq $bambuExe -and
                    $_.ProcessId -notin $initialBambuIds
                )
            )
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    if ([IO.Directory]::Exists($target)) {
        [IO.Directory]::Delete($target, $true)
    }
}

Write-Output "Inno installer end-to-end test passed."
