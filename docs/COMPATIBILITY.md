# 兼容性

## 已验证环境

- Windows 10 1809 x64 或更高版本
- Windows 11 x64
- 普通用户权限
- Microsoft Edge WebView2 Runtime
- Bambu Studio 已安装并能正常运行命令行切片
- 输入格式：STL、3MF、STEP、STP
- 输出格式：`.gcode.3mf`

## 多色排盘

- 输入仅接受包含颜色和材料信息的 3MF 工程。
- 支持零串色、满盘参考和按盘时长三种策略。
- 可生成可在 Bambu Studio 继续编辑的 `.3mf`，也可生成
  `.gcode.3mf`。
- 多色排盘依赖同安装目录的 `protected_core.exe`。组件缺失、哈希不一致
  或协议版本不兼容时不会启动任务。

## Bambu Studio

打印农场助手复用用户本机安装的 Bambu Studio 及其预设。Bambu Studio
升级后，内部命令行参数或预设名称可能变化。遇到兼容性问题时，请附上：

- 打印农场助手版本；
- Bambu Studio 版本；
- 机器型号；
- 输入文件格式；
- 从“设置 → 本地日志”导出的相关日志。

不要上传保密模型、客户模型或完整 G-code。可以改用简单几何体复现。

## 打印机

机器列表来自本机 Bambu Studio 预设。实际切片前仍应确认喷嘴、打印板、
耗材和工艺组合是否匹配。软件不会替用户验证第三方耗材或非官方固件。

## 安装权限

官方安装器按当前用户安装，不需要管理员权限，也不会以管理员身份启动
Bambu Studio。若 Bambu Studio 自身被设置成“以管理员身份运行”，命令行
切片可能因 Windows 错误 740 失败，请在 Bambu Studio 属性中取消该选项。

## 暂不支持

- 32 位 Windows
- macOS / Linux
- 无图形桌面的服务器环境
