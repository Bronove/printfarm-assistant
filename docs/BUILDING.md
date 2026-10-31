# 构建说明

公开仓库只构建开源基础工作台。官方安装包中的闭源优化器和 Bambu 桌面
自动化桥不包含在本仓库。

## 环境

- Windows 11 x64
- Python 3.12 x64
- Node.js 20 或更新版本
- Inno Setup 6
- 可用的 Bambu Studio 安装
- Microsoft Edge / WebView2

## 安装依赖

```powershell
cd app\ui_v2
npm ci
python -m pip install -r requirements.txt
```

## 测试

```powershell
npm run test:backend
npm run test:ui
npm run build
.\build_v2.ps1 -NoFrontendBuild
npm run test:e2e:packaged
```

公开测试不附带任何真实模型。基础 STL 测试会在临时目录运行时生成简单
几何体；STEP 深度测试仅在开发者本机存在私有测试文件时运行。

`app/ui_v2/headless_core.py` 是发布时从经过审核的旧内核方法中提取的无界面
代码，不包含多色排盘、手办或悬浮助手。维护者可以用主项目中的
`scripts/extract_headless_core.py` 和 `scripts/assemble_public_repo.ps1`
重新生成，禁止直接把完整旧界面文件复制到公开仓库。

## 构建安装器

```powershell
.\build_inno_installer.ps1 -Version 1.5.0-beta.1
npm run test:installer:inno
```

发布前必须重新计算 SHA-256，并确认安装包不包含：

- 用户模型或切片结果；
- `config.json`、`usage.json`、日志；
- API Key、访问令牌或其他凭据；
- Gmsh 动态库在主程序目录中的副本。

## STEP 转换器

`step_converter.exe` 是独立 GPL 组件。主程序只通过子进程调用它，不链接
Gmsh。发布时必须在 `licenses` 中保留 GPL 正文和第三方声明。
