param(
    [string]$Python = "",
    [string]$OutDir = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Python) {
    $Python = $env:PRINTFARM_PYTHON
}
if (-not $Python) {
    $Python = "D:\python\python.exe"
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "找不到 Python：$Python"
}
if (-not $OutDir) {
    $OutDir = Join-Path $root "dist_mcp"
}

& $Python -m PyInstaller --noconfirm --clean --onefile --console `
    --name tuozhu-mcp `
    --distpath $OutDir `
    --workpath (Join-Path $root "build_mcp") `
    --specpath $root `
    (Join-Path $root "tuozhu_mcp.py")
if ($LASTEXITCODE -ne 0) {
    throw "MCP Server 构建失败"
}

$exe = Join-Path $OutDir "tuozhu-mcp.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "MCP Server 产物不存在：$exe"
}
$check = Start-Process -FilePath $exe -ArgumentList "--version" `
    -Wait -PassThru -WindowStyle Hidden
if ($check.ExitCode -ne 0) {
    throw "MCP Server 自检失败，退出码 $($check.ExitCode)"
}
Get-Item -LiteralPath $exe | Select-Object FullName, Length, LastWriteTime
