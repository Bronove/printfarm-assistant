# PrintFarm Assistant MCP Server

Local stdio MCP connector for PrintFarm Assistant. It exposes a small,
typed tool surface to Codex, Claude Desktop, Cursor, and other MCP clients.

## Safety boundary

- Local only: no public HTTP listener and no cloud service.
- No arbitrary shell execution.
- No arbitrary file access. Models must be under the configured roots.
- Slicing starts a local task; it never sends a job to a printer.
- Credentials and Bambu access codes are never returned by tools.

## Tools

`assistant_status`, `find_assistant`, `lookup_parameter`, `slice_files`,
`job_status`, `cancel_job`, and `open_output`.

## Build

```powershell
.\build_mcp.ps1 -Python D:\python\python.exe
```

The executable is written to `dist_mcp\tuozhu-mcp.exe`.

## Configure Codex

Use the installer helper from the installed application directory:

```powershell
.\install_tuozhu_mcp.ps1 -Client codex
```

Or add this to `~/.codex/config.toml`:

```toml
[mcp_servers.tuozhu-assistant]
command = 'C:\Users\YOUR_NAME\AppData\Local\Programs\PrintFarmAssistant\tuozhu-mcp.exe'
args = ["--stdio"]
```

## Configure other clients

Run:

```powershell
.\install_tuozhu_mcp.ps1
```

It prints a generic `mcpServers` JSON block. Paste it into the client's MCP
configuration and restart that client.

## Allowed model directories

By default the server may read models from:

- `%USERPROFILE%\Desktop`
- `%USERPROFILE%\Downloads`
- `%USERPROFILE%\Documents`

Override without exposing other directories:

```powershell
$env:TUOZHU_MCP_ALLOWED_ROOTS = "D:\Models;E:\切片输入"
```

## Diagnostics

```powershell
.\tuozhu-mcp.exe --doctor
.\tuozhu-mcp.exe --print-config
```

`--doctor` checks the installed assistant, local service, parameter database,
and permitted roots.
