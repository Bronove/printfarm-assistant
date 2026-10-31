# PrintFarm Assistant 1.5.0-beta.1

首个公开测试版。支持 Windows 10 1809 x64 和 Windows 11 x64。

## 下载

- `PrintFarmAssistant-v1.5.0-beta.1-win64-setup.exe`
- `SHA256SUMS.txt`
- `COMPONENT-SHA256SUMS.txt`
- `PrintFarmAssistant-1.5.0-beta.1.spdx.json`
- `MIT-LICENSE.txt`
- `GPL-2.0.txt`
- `THIRD_PARTY_NOTICES.md`

## 主要功能

- 切片工作台与批量切片。
- STL、3MF、STEP/STP 输入，输出可直接打印的 `.gcode.3mf`。
- 普通自动摆盘、自动朝向、参数修改、克隆、最省空间和最少支撑。
- 每用户安装，不需要管理员权限。
- 安装和卸载都不会关闭 Bambu Studio。
- 配置、日志和模型数据全部留在本机。

## 本版修复

- 修复最省空间合盘被 Bambu 误判为空盘后回退成多个文件的问题。
- 修复 ASCII STL 在预分析阶段卡住的问题。
- 修复 Windows 10 安装尾声旧版清理异常。
- 修复未处理切片子进程异常后一直显示“切片中”的问题。

## 已知限制

- 安装包未代码签名，SmartScreen 可能提示未知发布者。
- 不支持 32 位 Windows。
- 多色排盘、手办模式和悬浮助手不包含在本次公开版本中。
- 最省空间、最少支撑和 Bambu 桌面自动化组件保持闭源。

## 安装包校验

```text
BFC9CD65D55F56717CD5D184FCBAEF51C0E25D6F3540B60BD580D77480890E79
```

请只从本仓库 Releases 下载，并在运行前核对 SHA-256。
