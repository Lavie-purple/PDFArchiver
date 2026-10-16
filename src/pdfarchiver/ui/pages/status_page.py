"""「运行状态与自检」—— 阶段 1 建起来，阶段 2 在上面加了任务读数，
**2026-10-17 起它是 S7 的上半区**（**D-040** 第三条后果：不再是独立的导航项，内容一字未改）。

它是 AGENTS.md 那条「启动必须打印当前默认值 / 用户覆盖值 / 来源文件」和 SPEC 4.3「数据库损坏要能被知道」
在界面上的落点。阶段 2 第 10 项（显示扫描与索引任务的进度、错误和重试）继续落在这一块，
因为它的契约本来就是"把库里算出来的事实打出来"—— 加一块读数不需要新布局、新按钮。
内容全部来自 `StatusService.read()` / `read_tasks()` / `AppContext.background_state()` 的真查询，
页面里没有任何写死的数字。

**它作为控件被 `SettingsPage` 嵌入，而不是被复制一份渲染代码** —— 抄一份就会有两个口径，
而且实际已经漂过：这一份结尾原先挂着"语义搜索/归档/备份的界面都还没实现"那句散文，
抄的那一份没有，而那句话后来逐条过期。**现在页尾只有两处口径**：`UNWIRED_ACTIONS`（没接到
后端的动作）与 `DISK_EFFECT_LINE`（磁盘口径），各一份、由测试盯着。
"""
from __future__ import annotations

from PySide6 import QtWidgets

from pdfarchiver import __version__
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.nav import NAV_ITEMS

# 磁盘口径一句话。归档执行与整批撤销**接到后端之后这行必须改**，改它要带着 G17/G18/G19
# 的实测证据一起来（**ISSUES I55**），所以把它写成常量、由测试盯着，而不是散在正文里。
DISK_EFFECT_LINE = ("界面上没有任何按钮会移动、改名或删除你磁盘上的文件；"
                    "备份与恢复只会新写文件，不覆盖当前库。")

# 见 `StatusPage._unwired_block`：屏已落地、动作没接到后端的那一档。
UNWIRED_ACTIONS = (
    "S3 执行归档：预览算得出目标路径，但不会生成操作批次、不会开始搬运",
    "S4 整批撤销：反向批次的执行器还没实现",
    "OCR：只有 O1/O2/O3 读数，界面上没有触发入口（后端已交付）",
)


class StatusPage(QtWidgets.QWidget):
    def __init__(self, ctx: AppContext, cold_start_seconds: float | None = None,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.cold_start_seconds = cold_start_seconds
        self.view = QtWidgets.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.refresh = QtWidgets.QPushButton("重新读取数据库状态")
        self.refresh.setObjectName("searchBtn")
        self.refresh.clicked.connect(self.reload)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.refresh)
        self.reload()

    def _runtime_block(self) -> list[str]:
        ctx = self.ctx
        lines = [
            f"应用版本 = {__version__}",
            ctx.paths.describe(),
            f"日志目录 = {ctx.paths.logs_dir}",
            f"备份目录 = {ctx.paths.backups_dir}",
            f"本次装配耗时 = {ctx.bootstrap_seconds:.3f}s",
        ]
        if self.cold_start_seconds is not None:
            lines.append(f"冷启动（进程起来到窗口就绪）= {self.cold_start_seconds:.3f}s"
                         " 门禁 G1 [约定] ≤1.5s")
        return lines

    def _pending_block(self) -> list[str]:
        return [f"  · {i.title} —— 未实现：{i.blocked_by}"
                for i in NAV_ITEMS if not i.implemented]

    def _unwired_block(self) -> list[str]:
        """屏在、但某个动作没接到后端 —— 一个 `implemented` 布尔位表达不了的那一档。

        口径来源是 **ISSUES I55**，不是记忆。这三条以前写成一句散文贴在页尾，
        然后逐个过期（语义搜索与归档/备份界面都早已落地，那句还挂着"都还没实现"），
        现在由 `test_状态读数不许把已实现的屏说成没实现` 钉住不许再漂。
        """
        return [f"  · {line}" for line in UNWIRED_ACTIONS]

    def reload(self) -> None:
        """重查一遍库再渲染。刷新按钮存在的全部意义就是让"重启后数据还在"这件事可当场验证。

        任务块每次都是新查询、不缓存：进度缓存了等于在界面上展示一个已经过去的时刻。
        """
        bg = self.ctx.background_state()
        st = self.ctx.status.read()
        tasks = self.ctx.status.read_tasks(max_attempts=bg.max_attempts)
        parts = ["== 运行时 =="] + self._runtime_block()
        parts += ["", "== 设置（生效值 / 是否覆盖 / 来源）==", self.ctx.settings.describe()]
        parts += ["", "== 数据库 =="] + [f"  {ln}" for ln in st.lines()]
        parts += ["", f"== 默认分类写入结果 ==\n  {self.ctx.seed.describe()}"]
        parts += ["", "== 扫描与索引任务：进度 / 错误 / 重试 ==", *bg.lines(), *tasks.lines()]
        parts += ["", "== 界面尚未实现 =="] + self._pending_block()
        parts += ["", "== 还没接到界面上的动作 =="] + self._unwired_block()
        parts += ["", DISK_EFFECT_LINE]
        self.view.setPlainText("\n".join(parts))
