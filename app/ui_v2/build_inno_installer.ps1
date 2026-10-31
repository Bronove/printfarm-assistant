param(
    [string]$Version = "1.5.0-beta.1",
    [string]$SourceDir = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $SourceDir) {
    $SourceDir = Join-Path $root "dist_v2\PrintFarmAssistant"
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $root "installer_inno"
}
$SourceDir = [IO.Path]::GetFullPath($SourceDir)
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$appExe = Join-Path $SourceDir "PrintFarmAssistant.exe"
if (-not (Test-Path -LiteralPath $appExe)) {
    throw "找不到待安装程序：$appExe"
}

$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } |
    Select-Object -First 1
if (-not $iscc) {
    throw "未安装 Inno Setup 6"
}

New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$script = Join-Path $root "installer\inno\PrintFarmAssistant.iss"
& $iscc "/DMyAppVersion=$Version" "/DSourceDir=$SourceDir" `
    "/DOutputDir=$OutputDir" $script
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup 构建失败，退出码 $LASTEXITCODE"
}

$setup = Get-ChildItem -LiteralPath $OutputDir -Filter "*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $setup) {
    throw "安装器构建完成但没有找到输出文件"
}
Get-FileHash -Algorithm SHA256 -LiteralPath $setup.FullName |
    ForEach-Object { "$($_.Hash)  $([IO.Path]::GetFileName($setup.FullName))" } |
    Set-Content -LiteralPath (Join-Path $OutputDir "SHA256SUMS.txt") -Encoding ascii
Get-Item -LiteralPath $setup.FullName | Select-Object FullName, Length, LastWriteTime
