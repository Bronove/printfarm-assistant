# 安装说明

## 准备工作

1. 使用 Windows 10 1809 x64 或更高版本，并安装系统的重要更新。
2. 安装 Microsoft Edge WebView2 Runtime。新版 Windows 通常已经自带。
3. 从 Bambu Lab 官方渠道安装 Bambu Studio，并至少成功打开、登录和完成一次普通切片。
4. 从本仓库 Releases 下载安装包和 `SHA256SUMS.txt`。

## 校验安装包

在下载目录打开 PowerShell：

```powershell
Get-FileHash .\PrintFarmAssistant-v1.6.0-beta.1-win64-setup.exe -Algorithm SHA256
```

结果应与 `SHA256SUMS.txt` 一致。

## 安装

双击安装包。安装器使用当前用户权限，不弹出 UAC，默认安装到：

```text
%LOCALAPPDATA%\Programs\PrintFarmAssistant
```

安装器不会关闭 Bambu Studio。若打印农场助手正在运行，Windows Restart
Manager 会请求它退出，以便替换文件。

如果电脑上存在旧版 `拓竹助手1.0`、`拓竹助手` 或 `拓竹助手V2`，安装器会：

1. 优先沿用旧安装目录；
2. 把配置、日志和使用记录迁移到新的用户数据目录；
3. 删除旧版快捷方式和卸载登记；
4. 创建“打印农场助手”快捷方式。

## 首次启动

首次启动会创建：

```text
%LOCALAPPDATA%\PrintFarmAssistant
```

导入模型后请先确认打印机、工艺、耗材、打印板、输出目录和支撑设置，再开始切片。输出文件通常以 `_切片.gcode.3mf` 结尾。

使用“多色排盘”时请导入带颜色和材料信息的 3MF。软件会调用同安装目录下的
`protected_core.exe`；若提示受保护组件缺失或校验失败，请重新安装官方安装包，
不要只替换主程序文件。多色真实切片耗时较长，开始后请等待当前任务结束再修改
模型或参数。

## 卸载

在 Windows“设置 → 应用”中卸载“打印农场助手”。卸载程序不会删除
`%LOCALAPPDATA%\PrintFarmAssistant` 中的数据；如需彻底清理，请在确认不再需要配置和日志后手动删除该目录。

## 常见问题

### SmartScreen 显示未知发布者

当前安装包尚未代码签名。确认文件来自本仓库 Releases 且 SHA-256 正确后，可选择“更多信息 → 仍要运行”。

### 提示找不到 Bambu Studio

安装器不会阻断这种情况，但切片需要 Bambu Studio。请安装官方 Bambu Studio，并确认能在普通用户权限下启动。

### 提示缺少 WebView2

从 Microsoft 官方站点安装 Evergreen WebView2 Runtime 后重新启动打印农场助手。
