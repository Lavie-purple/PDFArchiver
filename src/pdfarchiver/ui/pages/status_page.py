"""「运行状态与自检」页 —— 阶段 1 唯一有真实内容的一屏。

它不属于 A1–A8 任何一屏，也不参与产品布局：它是 AGENTS.md 那条「启动必须打印当前默认值 /
用户覆盖值 / 来源文件」和 SPEC 4.3「数据库损坏要能被知道」在界面上的落点。
内容全部来自 `StatusService.read()` 的真查询，页面里没有任何写死的数字。
"""
from __future__ import annotations

from PySide6 import QtWidgets

from pdfarchiver import __version__
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.nav import NAV_ITEMS


class StatusPage(QtWidgets.QWidget):
    def __init__(self, ctx: AppContext, cold_start_seconds: float | None = None,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.cold_start_seconds = cold_start_seconds
        self.view = QtWidgets.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.refresh = QtWidgets.QPushButton("重新读取数据库状态")
        self.refresh.clicked.connect(self.reload)

        lay = QtWidgets.QVBoxLayout(self)
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
        return [f"  · {i.title}（SPEC {i.spec}）—— 未实现：{i.blocked_by}"
                for i in NAV_ITEMS if not i.implemented]

    def reload(self) -> None:
        """重查一遍库再渲染。刷新按钮存在的全部意义就是让"重启后数据还在"这件事可当场验证。"""
        st = self.ctx.status.read()
        parts = ["== 运行时 =="] + self._runtime_block()
        parts += ["", "== 设置（生效值 / 是否覆盖 / 来源）==", self.ctx.settings.describe()]
        parts += ["", "== 数据库 =="] + [f"  {ln}" for ln in st.lines()]
        parts += ["", f"== 默认分类写入结果 ==\n  {self.ctx.seed.describe()}"]
        parts += ["", "== 本阶段未实现 =="] + self._pending_block()
        parts += ["", "本阶段刻意没做：目录扫描、全文索引、OCR、语义搜索、任何文件移动。"]
        self.view.setPlainText("\n".join(parts))
