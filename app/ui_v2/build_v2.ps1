param(
    [string]$Python = "",
    [switch]$NoFrontendBuild,
    [switch]$SkipStepConverter
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Split-Path -Parent $root
$legacy = Join-Path $project "切片软件"
$buildTools = Join-Path $project "build_tools"
$dist = Join-Path $root "dist"
$out = Join-Path $root "dist_v2"
$work = Join-Path $root "build_v2"
$runtimeSource = Join-Path $root "build_runtime_source"
$converterScript = Join-Path $root "step_converter.py"
$converterDist = Join-Path $root "dist_step_converter"
$converterWork = Join-Path $root "build_step_converter"
$converterExe = Join-Path $converterDist "step_converter.exe"

if (-not $Python) {
    $Python = $env:PRINTFARM_PYTHON
}
if (-not $Python) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($pythonCommand) {
        $Python = $pythonCommand.Source
    }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) {
    throw "找不到 Python。请用 -Python 指定解释器，或设置 PRINTFARM_PYTHON。"
}

if (-not $NoFrontendBuild) {
    Push-Location $root
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $dist "index.html"))) {
    throw "找不到前端 dist/index.html"
}

if (-not $SkipStepConverter) {
    if (-not (Test-Path -LiteralPath $converterScript)) {
        throw "找不到 STEP 转换组件：$converterScript"
    }
    $gmshDll = (& $Python -c "import gmsh; print(gmsh.libpath)").Trim()
    if (-not (Test-Path -LiteralPath $gmshDll)) {
        throw "找不到 Gmsh 原生库：$gmshDll"
    }
    $ffiDll = (& $Python -c "import sys; from pathlib import Path; print(Path(sys.prefix) / 'Library' / 'bin' / 'ffi.dll')").Trim()
    if (-not (Test-Path -LiteralPath $ffiDll)) {
        throw "找不到 Python ctypes 运行库：$ffiDll"
    }
    & $Python -m PyInstaller `
        --noconfirm --clean --onefile --console `
        --name step_converter `
        --distpath $converterDist `
        --workpath $converterWork `
        --specpath $root `
        --paths $root `
        "--add-binary=$gmshDll;." `
        "--add-binary=$ffiDll;." `
        --exclude-module numpy `
        --exclude-module scipy `
        --exclude-module setuptools `
        --exclude-module pkg_resources `
        $converterScript
    if ($LASTEXITCODE -ne 0) {
        throw "STEP 转换组件打包失败"
    }
}

if (Test-Path -LiteralPath $runtimeSource) {
    [IO.Directory]::Delete($runtimeSource, $true)
}
New-Item -ItemType Directory -Path $runtimeSource -Force | Out-Null
$legacyEntry = Join-Path $legacy "切片软件.pyw"
if (Test-Path -LiteralPath $legacyEntry) {
    Copy-Item -LiteralPath $legacyEntry `
        -Destination (Join-Path $runtimeSource "legacy_slice_entry.py") -Force
}

$hidden = @(
    "analyze_stl", "clean_stl", "flatten_presets", "slice_bambu",
    "footprint", "pack", "merge_stl", "param_diff", "unpack_3mf",
    "repair_mesh", "bambu_wiki", "voice_norm", "materials",
    "min_support", "merge_3mf", "seam_profile",
    "native_dialog", "webview.platforms.edgechromium",
    "tkinter.scrolledtext", "tkinter.filedialog", "tkinter.messagebox",
    "tkinter.ttk", "headless_core"
)
$args = @(
    "-m", "PyInstaller",
    "--noconfirm", "--clean", "--onedir", "--windowed",
    "--name", "PrintFarmAssistant",
    "--distpath", $out,
    "--workpath", $work,
    "--specpath", $root,
    "--icon", (Join-Path $legacy "icon.ico"),
    "--version-file", (Join-Path $root "version_info_v2.txt"),
    "--paths", $root,
    "--paths", $legacy,
    "--paths", (Join-Path $legacy "bambu_cli"),
    "--paths", $buildTools,
    "--paths", $runtimeSource,
    "--add-data=$dist;dist",
    "--add-data=$((Join-Path $legacy 'icon.ico'));.",
    "--add-data=$((Join-Path $legacy '说明.txt'));.",
    "--add-data=$((Join-Path $legacy 'version.txt'));.",
    "--add-data=$((Join-Path $legacy 'ocr_win.ps1'));.",
    "--add-data=$((Join-Path $legacy 'ocr_corpus_zh.json'));.",
    "--add-data=$((Join-Path $legacy 'bambu_wiki_paths.json'));.",
    "--add-data=$((Join-Path $legacy 'bambu_wiki_catalog.json'));.",
    "--add-data=$((Join-Path $legacy 'bambu_wiki_tabs.json'));.",
    "--add-data=$((Join-Path $legacy 'assets'));assets",
    "--add-data=$((Join-Path $legacy 'user_rules_default.json'));."
)
foreach ($name in $hidden) {
    $args += @("--hidden-import", $name)
}
$args += @(
    "--exclude-module", "pandas",
    "--exclude-module", "matplotlib",
    "--exclude-module", "lxml",
    "--exclude-module", "openpyxl",
    "--exclude-module", "IPython",
    "--exclude-module", "jupyter",
    "--exclude-module", "nbformat",
    "--exclude-module", "notebook",
    "--exclude-module", "dask",
    "--exclude-module", "distributed",
    "--exclude-module", "numba",
    "--exclude-module", "llvmlite",
    "--exclude-module", "skimage",
    "--exclude-module", "pytest",
    "--exclude-module", "sphinx",
    "--exclude-module", "docutils",
    "--exclude-module", "black",
    "--exclude-module", "yapf",
    "--exclude-module", "Pygments",
    "--exclude-module", "pygments",
    "--exclude-module", "zmq",
    "--exclude-module", "cloudpickle",
    "--exclude-module", "PyQt5",
    "--exclude-module", "PyQt6",
    "--exclude-module", "PySide2",
    "--exclude-module", "PySide6",
    "--exclude-module", "gi",
    "--exclude-module", "tkinterdnd2",
    "--exclude-module", "torch",
    "--exclude-module", "torchvision",
    "--exclude-module", "tensorboard",
    (Join-Path $root "launcher.pyw")
)

& $Python @args
if ($LASTEXITCODE -ne 0) { throw "打印农场助手打包失败" }

$exe = Join-Path $out "PrintFarmAssistant\PrintFarmAssistant.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "构建产物不存在：$exe"
}

if (-not (Test-Path -LiteralPath $converterExe)) {
    throw "构建产物缺少 STEP 转换组件：$converterExe"
}
Copy-Item -LiteralPath $converterExe `
    -Destination (Join-Path $out "PrintFarmAssistant\step_converter.exe") -Force
$noticeDir = Join-Path $out "PrintFarmAssistant\licenses"
New-Item -ItemType Directory -Path $noticeDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root "THIRD_PARTY_NOTICES.md") `
    -Destination (Join-Path $noticeDir "THIRD_PARTY_NOTICES.md") -Force
$gplText = Join-Path $root "third_party\GPL-2.0.txt"
if (-not (Test-Path -LiteralPath $gplText)) {
    throw "缺少 GPL 许可证正文：$gplText"
}
Copy-Item -LiteralPath $gplText `
    -Destination (Join-Path $noticeDir "GPL-2.0.txt") -Force

$gmshFiles = Get-ChildItem -LiteralPath (Join-Path $out "PrintFarmAssistant") `
    -Recurse -File | Where-Object { $_.Name -like "gmsh*" }
if ($gmshFiles) {
    throw "主程序包不应直接包含 Gmsh：$($gmshFiles.FullName -join ', ')"
}

$smokeStep = Join-Path $project "test_files\block.stp"
if (Test-Path -LiteralPath $smokeStep) {
    $smokeStl = Join-Path ([IO.Path]::GetTempPath()) `
        ("printfarm-step-smoke-" + [guid]::NewGuid().ToString("N") + ".stl")
    try {
        & $converterExe $smokeStep $smokeStl --mesh-size 2
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $smokeStl)) {
            throw "STEP 转换组件冒烟测试失败"
        }
    } finally {
        if (Test-Path -LiteralPath $smokeStl) {
            Remove-Item -LiteralPath $smokeStl -Force
        }
    }
} else {
    Write-Warning "未提供 STEP 冒烟测试文件，跳过构建期 STEP 转换测试。"
}

Get-Item -LiteralPath $exe | Select-Object FullName, Length, LastWriteTime
Get-Item -LiteralPath (Join-Path $out "PrintFarmAssistant\step_converter.exe") |
    Select-Object FullName, Length, LastWriteTime
