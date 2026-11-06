param(
    [ValidateSet("print", "codex")]
    [string]$Client = "print",
    [string]$Name = "tuozhu-assistant",
    [string]$AllowedRoots = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$exe = Join-Path $root "tuozhu-mcp.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    $exe = Join-Path $root "dist_mcp\tuozhu-mcp.exe"
}
if (-not (Test-Path -LiteralPath $exe)) {
    throw "找不到 tuozhu-mcp.exe"
}

$envArgs = @{}
if ($AllowedRoots) {
    $envArgs["TUOZHU_MCP_ALLOWED_ROOTS"] = $AllowedRoots
}

if ($Client -eq "codex") {
    $codex = Get-Command codex -ErrorAction SilentlyContinue
    if (-not $codex) {
        throw "没有找到 Codex CLI。请先安装 Codex，或使用默认 print 模式。"
    }
    $existing = & codex mcp get $Name 2>$null
    if ($LASTEXITCODE -eq 0) {
        throw "Codex 已存在名为 $Name 的 MCP 配置；请先手动检查，脚本不会覆盖。"
    }
    $command = @("mcp", "add", $Name)
    foreach ($entry in $envArgs.GetEnumerator()) {
        $command += @("--env", "$($entry.Key)=$($entry.Value)")
    }
    $command += @("--", $exe, "--stdio")
    & codex @command
    if ($LASTEXITCODE -ne 0) {
        throw "写入 Codex MCP 配置失败"
    }
    "已添加 Codex MCP：$Name -> $exe"
    exit 0
}

$payload = @{
    mcpServers = @{
        $Name = @{
            command = $exe
            args = @("--stdio")
        }
    }
}
if ($envArgs.Count) {
    $payload.mcpServers[$Name]["env"] = $envArgs
}
$payload | ConvertTo-Json -Depth 6
