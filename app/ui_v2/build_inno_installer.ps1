param(
    [string]$Version = "",
    [ValidateSet("dev", "public")]
    [string]$Channel = "dev",
    [string]$SourceDir = "",
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildTime = Get-Date
if ([string]::IsNullOrWhiteSpace($Version)) {
    if ($Channel -eq "dev") {
        $Version = $buildTime.ToString("yyyyMMdd-HHmm")
    } else {
        throw "公开构建必须显式指定 -Version，例如 1.5.0。"
    }
}
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
foreach ($required in @(
    "step_converter.exe",
    "protected_core.exe",
    "protected_core.sha256",
    "tuozhu-mcp.exe",
    "install_tuozhu_mcp.ps1",
    "mcp\README.md"
)) {
    $requiredPath = Join-Path $SourceDir $required
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "安装目录缺少组件：$requiredPath"
    }
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
$outputTag = if ($Channel -eq "public") { "" } else { "-本机研发" }
$sourceVersion = (Get-Content -LiteralPath (Join-Path $root "version.txt") -Raw).Trim()
$versionMatch = [regex]::Match($sourceVersion, '^(\d+)\.(\d+)\.(\d+)')
if (-not $versionMatch.Success) {
    throw "无法从 version.txt 解析数字版本：$sourceVersion"
}
$revisionMatch = [regex]::Match($sourceVersion, '(?:-dev\.|-beta\.)(\d+)$')
$fileRevision = if ($revisionMatch.Success) {
    $revisionMatch.Groups[1].Value
} else {
    "1"
}
$fileVersion = "{0}.{1}.{2}.{3}" -f `
    $versionMatch.Groups[1].Value, `
    $versionMatch.Groups[2].Value, `
    $versionMatch.Groups[3].Value, `
    $fileRevision
@(
    "构建渠道：$Channel"
    "构建版本：$Version"
    "构建时间：$($buildTime.ToString('yyyy-MM-dd HH:mm:ss zzz'))"
    "源码版本：$sourceVersion"
    "构建主机：$env:COMPUTERNAME"
) | Set-Content -LiteralPath (Join-Path $SourceDir "BUILD_INFO.txt") -Encoding utf8
& $iscc "/DMyAppVersion=$Version" "/DMyOutputTag=$outputTag" `
    "/DMyFileVersion=$fileVersion" `
    "/DSourceDir=$SourceDir" `
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
    Set-Content -LiteralPath (Join-Path $OutputDir "SHA256SUMS.txt") -Encoding utf8
Get-Item -LiteralPath $setup.FullName | Select-Object FullName, Length, LastWriteTime
