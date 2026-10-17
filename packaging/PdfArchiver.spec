# -*- mode: python ; coding: utf-8 -*-
"""产品级冻结配置 —— 打的是真 `main.py`，不是 p8 那个阶段 0 自检脚本。

跟 p8 的三点不同，每一点都是"p8 绿了但产品仍然起不来"的地方：

1. `--windowed`（console=False）：产品形态没有控制台窗口，p8 打的是控制台程序。
2. OCR 可选层**整层进包**：`rapidocr_onnxruntime` 的三个 .onnx 模型是数据文件，
   默认不收；`onnxruntime` 的 provider DLL 是 binary，也要显式收。
   不收的后果是"开发机跑得、装到别人机器上报 OCR 不可用"，而那正好是本项目最容易
   伪装成功的一条 —— 没装可选层时应用照理就该照常起。
3. 入口用仓库根的 `main.py`：它自带 `sys.path` 处理，`pathex` 指到 `src/` 让
   PyInstaller 的静态分析能找到 `pdfarchiver` 包。

还有一处 p8 根本没碰到的坑：迁移脚本要当数据文件收进来，见下面 `MIGRATION_FILES` 那段。
首版冻结产物就是因为漏了它，双击起来直接崩在建表之前 —— 这条由 `packaging/build.py`
的"包内迁移清单 == 源目录迁移清单"断言钉住。

第二处同类坑，同一族：**发行包元数据（`.dist-info`）默认不进包**。`ocr/engine.py` 的版本指纹走
`importlib.metadata.version("rapidocr-onnxruntime")`，冻结产物里模块 import 得动、元数据却不在，
于是 `PackageNotFoundError` 被当成"这台机器没装 OCR"，OCR 任务整批 `failed`，而构建报告那头的
`rapidocr: True` 是在 venv 里 import 成功的读数 —— 两边都"没骗人"，拼起来就是假绿。
所以可选层除了代码/模型/DLL，还要 `copy_metadata()` 把 `.dist-info` 一起收进来。

可选层没装时这份 spec 必须照样能跑（退化成基础运行时包），所以整段收集逻辑包在 try 里，
并把"到底收没收"写进构建产物旁边的一行说明 —— 靠 `packaging/build.py` 读回来对账。
"""
import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
SRC = os.path.join(ROOT, "src")

datas = []
binaries = []
hiddenimports = []

# 迁移脚本必须**以 .py 文件的形式**进包：`migrations/__init__.py` 的 discover() 是对目录做
# `glob("*.py")` 再用 importlib 按路径加载（文件名以数字开头，不能靠 import 语句发现），
# 所以它们不在 PYZ 里，冻结后磁盘上没有这份目录 = 一条迁移也发现不了 = 一张表也不建。
# 冻结模块的 __file__ 是 `sys._MEIPASS/<包名路径>/<模块>.py`（见 PyInstaller loader），
# 于是目标目录只能是 pdfarchiver/db/migrations —— 与 migrate.py 里
# `Path(__file__).parent / "migrations"` 同一个位置。
# 不收 __init__.py：discover() 本来就跳过下划线开头的文件，而目录里少了 __init__.py 也
# 就不会有任何东西把 _MEIPASS 下的这份数据目录误认成可 import 的包。
_MIGRATIONS_SRC = os.path.join(SRC, "pdfarchiver", "db", "migrations")
_MIGRATIONS_DEST = os.path.join("pdfarchiver", "db", "migrations")
MIGRATION_FILES = sorted(
    os.path.basename(_p) for _p in glob.glob(os.path.join(_MIGRATIONS_SRC, "*.py"))
    if not os.path.basename(_p).startswith("_")
)
datas += [(os.path.join(_MIGRATIONS_SRC, _f), _MIGRATIONS_DEST) for _f in MIGRATION_FILES]

# OCR 可选层：装了才收。没装就冻一个不含 OCR 的包，应用侧由 tests/integration/test_ocr_progress_and_budget.py
# 那条子进程断言保证"起得来、并明确报不可用"。
#
# 元数据（.dist-info）与代码是两件事：`copy_metadata` 收的是**发行包名**，与 import 名可以不同
# （发行包 `onnxruntime-directml` import 进来叫 `onnxruntime`），所以按 `_dist()` 实际查询的名字收。
# 收不到就当场炸：宁可打不出包，也不能打出一个"OCR 层在、版本指纹读不到"的包 —— 那种包在
# 用户机上会把整批 OCR 任务标成 failed，而构建报告里 `rapidocr: True` 依然一片祥和。
def _metadata(*dists: str) -> list:
    for _d in dists:
        try:
            return list(copy_metadata(_d))
        except Exception as exc:  # noqa: BLE001 - 逐个发行包名试，全失败才炸
            last = exc
    raise RuntimeError(f"发行包元数据一个都收不到（试过 {dists}）：{type(last).__name__}: {last}")


try:
    import rapidocr_onnxruntime  # noqa: F401

    datas += collect_data_files("rapidocr_onnxruntime")
    hiddenimports += collect_submodules("rapidocr_onnxruntime")
    datas += _metadata("rapidocr-onnxruntime")
    OCR_BUNDLED = True
except ImportError:
    OCR_BUNDLED = False

try:
    import onnxruntime as _ort

    binaries += collect_dynamic_libs("onnxruntime")
    hiddenimports += collect_submodules("onnxruntime")
    datas += _metadata("onnxruntime-directml", "onnxruntime")
    ORT_BUNDLED = True
except ImportError:
    ORT_BUNDLED = False

# shapely / pyclipper 是 rapidocr 的几何后处理，DLL 型依赖，静态分析容易漏
for _m in ("shapely", "pyclipper"):
    try:
        __import__(_m)
        binaries += collect_dynamic_libs(_m)
        datas += collect_data_files(_m)
        hiddenimports += collect_submodules(_m)
    except ImportError:
        pass

hiddenimports += ["psutil", "watchdog"]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 开发/测试工具链不许混进产品运行时（requirements/dev.txt 明确"不进产品运行时"）
    excludes=["pytest", "_pytest", "pytestqt", "PySide6.QtWebEngineCore", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PdfArchiver",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PdfArchiver",
)
