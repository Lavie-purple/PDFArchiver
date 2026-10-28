"""「运行状态与自检」—— 阶段 1 建起来，阶段 2 在上面加了任务读数，
**2026-10-17 起它是 S7 的上半区**（**D-040** 第三条后果：不再是独立的导航项，内容一字未改）。

它是 AGENTS.md 那条「启动必须打印当前默认值 / 用户覆盖值 / 来源文件」和 SPEC 4.3「数据库损坏要能被知道」
在界面上的落点。阶段 2 第 10 项（显示扫描与索引任务的进度、错误和重试）继续落在这一块，
因为它的契约本来就是"把库里算出来的事实打出来"—— 加一块读数不需要新布局、新按钮。
内容全部来自 `StatusService.read()` / `read_tasks()` / `AppContext.background_state()` 的真查询，
页面里没有任何写死的数字。

**它有两条重查路线，差别只在一格读数上**（**ISSUES I109** 丙）：`reload()` 是完整的，只有
「重新读取数据库状态」那颗按钮走它；`reload_progress()` 是建窗路径与 5 秒巡检节拍走的轻版本，
跳过「库里已存 OCR 正文 N 页」那一格，因为那一格要逐行扫正文表。两条路线都不缓存其余读数，
所以"进度停在过去的时刻"这条老规矩没变。

**完整重查在后台线程跑**（**ISSUES I109** ①）：那一格在 11GB 真库上实测 201–212 秒，放在 GUI 线程
里就是把整个应用按住三分钟。与 `HealthPanel` 同一形状 —— `threading.Thread` + `Signal`，不用
`QThread`（窗口关掉时 QThread 还在跑会打 "Destroyed while thread is still running"；daemon 线程
随进程退出）。线程里只拼字符串、回主线程再 `setPlainText`，不碰任何控件。

**它作为控件被 `SettingsPage` 嵌入，而不是被复制一份渲染代码** —— 抄一份就会有两个口径，
而且实际已经漂过：这一份结尾原先挂着"语义搜索/归档/备份的界面都还没实现"那句散文，
抄的那一份没有，而那句话后来逐条过期。**现在页尾只有两处口径**：`UNWIRED_ACTIONS`（没接到
后端的动作）与 `DISK_EFFECT_LINE`（磁盘口径），各一份、由测试盯着。
"""
from __future__ import annotations

import threading
import time

from PySide6 import QtCore, QtWidgets

from pdfarchiver import __version__
from pdfarchiver.services.bootstrap import AppContext
from pdfarchiver.ui.nav import NAV_ITEMS

# 磁盘口径一句话。**2026-10-17 起它是假的**（归档执行与整批撤销接上了后台执行器），
# 所以那一行改成了"哪两个按钮会动盘、怎么个动法"。再改它仍然要带着 G17/G18/G19 的实测证据
# 一起来（**ISSUES I55** 记的就是这条线），所以写成常量、由测试盯着，而不是散在正文里。
DISK_EFFECT_LINE = ("「执行归档」与「撤销选中批次」会真的移动你磁盘上的文件"
                    "（先写 journal，跨盘要验完哈希才删源，被跳过的项带着原因落在台账里）；"
                    "备份与恢复只会新写文件，不覆盖当前库。")

# 见 `StatusPage._unwired_block`：屏已落地、动作没接到后端的那一档。
# **ISSUES I55** 乙（2026-10-17）在这一档里加了「命名模板」：勾乙 = 维持现状（诚实文案 + 挂账），
# 但它要求的不是"再写一句道歉"，而是**把事实显示在控件旁边**。
# 2026-10-17 收尾：这一档只剩 OCR 一条 —— 「S3 执行归档」「S3 命名模板」「S4 整批撤销」
# 三条随 A2/A3/A4 接线一起销账（模板现在真的参与渲染，S3 屏上那句 `SCOPE_NOTE` 说的是
# "改动不写回 settings.json"这件仍然真的事，不是"改了什么都不变"）。
# 还欠的一条是 **D-042** 丙 定的「模板编辑入口挪到 S7」，那是**缺入口**不是**断链**，
# 记在 **ISSUES I55** 的销账说明里，不进这张"动作没接到后端"的表。
# **2026-10-19 轮十四 A：OCR 那一条随 **ISSUES I67** 甲 销账** —— S1 表格底下那颗
# 「送去识别」是 `request_ocr` 在产品里的第一个调用点，这张表现在是空的。
# 空表是**真实状态**而不是"忘了写"：`unwired_lines()` 的唯一消费者就是这张表，
# 条目回来时由 `test_用户文档不许把未接线的动作写成界面能做的事` 要求补话题词映射。
UNWIRED_ACTIONS: tuple[str, ...] = ()


def unwired_lines(page_prefix: str) -> list[str]:
    """某一屏自己该显示的未接线条目（去掉「S3 」这种屏名前缀）。

    状态页显示全量、每一屏只显示属于自己那一条（去掉 `S3 ` 这种屏名前缀），
    **两处都走这一个函数**：在界面里另写一句「本轮不按模板改名」就是同一件事的第二个口径，
    代码一改它悄悄变成假话（与
    `test_状态读数里的缺什么只许来自两个列表` 盯的是同一条规则）。
    """
    return [line.removeprefix(page_prefix + " ") for line in UNWIRED_ACTIONS
            if line.startswith(page_prefix + " ")]


class StatusPage(QtWidgets.QWidget):
    #: 后台线程把拼好的正文递回主线程（跨线程 emit 走队列连接）。第二个参数是失败原文，
    #: 空串表示没出错 —— 分开传是为了失败时不静默吞掉，也不把上一次的读数一起洗掉。
    _text_ready = QtCore.Signal(str, str)
    #: 正文铺上屏之后对外发一次，给测试与"等这一轮读完"的调用方一个可等待的点。
    finished = QtCore.Signal()

    def __init__(self, ctx: AppContext, cold_start_seconds: float | None = None,
                 parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.cold_start_seconds = cold_start_seconds
        self._reloading = False
        self._t0 = 0.0
        self.view = QtWidgets.QPlainTextEdit()
        self.view.setReadOnly(True)
        self.refresh = QtWidgets.QPushButton("重新读取数据库状态")
        self.refresh.setObjectName("searchBtn")
        # 全站唯一会现数「库里已存 OCR 正文」的入口，代价写在按钮上（**ISSUES I109** 丙）。
        self.refresh.setToolTip("会连「库里已存 OCR 正文」一起现数 —— 那一条要逐行扫正文表，"
                                "库大了要在这里等几分钟；读取在后台跑，界面可以继续用")
        self.refresh.clicked.connect(self.reload)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._text_ready.connect(self._on_text)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.refresh)
        # 建窗路径不现数全库页数（**ISSUES I109** 丙）：这条在 11GB 真库上实测 ~200s，
        # 而窗口构造完就要画出来 —— G1 冷启动 1.5s 测在小库夹具上，照不到这个形状。
        self.reload_progress()

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
        """完整重查一遍再渲染 —— 只有「重新读取数据库状态」这颗按钮走这条。

        刷新按钮存在的全部意义就是让"重启后数据还在"这件事可当场验证。
        它同时也是全站**唯一**会现数「库里已存 OCR 正文 N 页」的入口（**ISSUES I109** 丙）：
        那条计数没有索引可走，真库 197 万页实测单条 201–212 秒，所以它只许出现在
        用户亲手按下的一次，不放在任何自动节拍上（代价写在按钮的 tooltip 上）。

        **这条重查在后台线程跑**（**ISSUES I109** ①）：201–212 秒放在 GUI 线程里等于把整个
        应用按住三分钟。线程里只拼字符串，回主线程再铺上屏。已在跑时忽略重复点击（按钮也禁用）。
        """
        if self._reloading:
            return
        self._reloading = True
        self._t0 = time.perf_counter()
        self.refresh.setEnabled(False)
        self._tick()
        self._timer.start()
        previous = self.view.toPlainText()

        def work() -> None:
            try:
                text = self._render_text(with_ocr_pages=True)
                error = ""
            except BaseException as exc:  # noqa: BLE001 - 没读出来也要把原文交给界面
                text, error = previous, f"{type(exc).__name__}: {exc}"
            self._text_ready.emit(text, error)

        threading.Thread(target=work, name="status-reload", daemon=True).start()

    @property
    def reloading(self) -> bool:
        return self._reloading

    @QtCore.Slot(str, str)
    def _on_text(self, text: str, error: str) -> None:
        self._timer.stop()
        self._reloading = False
        self.refresh.setEnabled(True)
        self.refresh.setText("重新读取数据库状态")
        self.view.setPlainText(text)
        if error:
            # 不许伪装成功：上一次的读数留在上面，失败原文贴在下面并指到日志。
            self.view.appendPlainText(
                f"\n== 重新读取失败 ==\n  {error}\n\n"
                "（上面是上一次读到的内容；失败的详细经过在日志里）")
        self.finished.emit()

    def _tick(self) -> None:
        if not self._reloading:
            self._timer.stop()
            return
        self.refresh.setText(f"正在重新读取… 已用 {time.perf_counter() - self._t0:.0f} 秒"
                             "（界面可以继续用）")

    def reload_progress(self) -> None:
        """自动路径（建窗、5 秒巡检节拍、回填冷启动耗时）走的轻版本：除那一格全库计数之外全部现数。

        与判重页同一处理（`main_window.patrol_tick` 里"只刷进度行"那条先例）。摘掉的只有
        `text_pages` 全表那一格 —— 其余读数（任务条数 / 进度 / 错误 / 重试 / 监测根 / 索引状态）
        每次都是新查询、不缓存：进度缓存了等于在界面上展示一个已经过去的时刻。

        完整重查在跑时整条跳过：那一轮读完会把整块正文覆盖掉，这里再查一遍只是白做一遍
        同样的查询、还会让读数在中途闪一下旧值。
        """
        if self._reloading:
            return
        self._render(with_ocr_pages=False)

    def _render(self, *, with_ocr_pages: bool) -> None:
        self.view.setPlainText(self._render_text(with_ocr_pages=with_ocr_pages))

    def _render_text(self, *, with_ocr_pages: bool) -> str:
        """把整页读数拼成一个字符串。**不碰控件** —— 后台线程也调它（只读库、拼字符串）。"""
        bg = self.ctx.background_state()
        st = self.ctx.status.read()
        tasks = self.ctx.status.read_tasks(max_attempts=bg.max_attempts,
                                           with_ocr_pages=with_ocr_pages)
        parts = ["== 运行时 =="] + self._runtime_block()
        parts += ["", "== 设置（生效值 / 是否覆盖 / 来源）==", self.ctx.settings.describe()]
        parts += ["", "== 数据库 =="] + [f"  {ln}" for ln in st.lines()]
        parts += ["", f"== 默认分类写入结果 ==\n  {self.ctx.seed.describe()}"]
        # 全库同步到哪个时刻（轮三十六 乙）：与状态栏那一格同一份读数、同一个方法，
        # 所以两处不会出现两个口径。放在任务块之前 —— 它是判断"任务块里那些进度是
        # 为哪一段时间服务的"的前提。
        parts += ["", "== 全库同步到哪个时刻 =="] + self.ctx.status.sync_status().lines()
        parts += ["", "== 扫描与索引任务：进度 / 错误 / 重试 ==", *bg.lines(), *tasks.lines()]
        parts += ["", "== 界面尚未实现 =="] + self._pending_block()
        parts += ["", "== 还没接到界面上的动作 =="] + self._unwired_block()
        parts += ["", DISK_EFFECT_LINE]
        return "\n".join(parts)
