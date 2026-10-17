"""命名模板渲染器的口径（阶段 4 · A3）。

这一份是**纯函数**测试：模板串进、路径段出，不碰库、不碰磁盘。
带库和磁盘的那半（`plan()` 的跳过原因、跨盘判定、journal 顺序）在
`tests/integration/test_archive_disk_safety.py`。

每条断言的存在理由都写在行上，因为这类规则最坏的坏法是"看起来对，其实在拆词"：
`{category}` 里的 `/` 必须变成**目录层级**而不是一个带斜杠的文件名，
而 Windows 的保留名和尾点会让整批搬运输掉。
"""
from __future__ import annotations

import pytest

from pdfarchiver.services.archive_service import (
    MAX_SAFE_COMPONENT_LENGTH, TEMPLATE_FIELDS, UNCLASSIFIED_FOLDER, UNKNOWN_YEAR_FOLDER,
    PathTooLongError, TemplateError, render_relative, sanitize_component, validate_path_length,
    validate_template)

DEFAULT_TEMPLATE = "{category}/{year}/{name}.pdf"


class TestSanitizeComponent:
    def test_非法字符换成下划线(self):
        # 分类名是用户在 S8 里自己打的，里面有 `:` 不该让整批归档失败
        assert sanitize_component("报销:2024<年度>") == "报销_2024_年度_"

    def test_分隔符也被换掉(self):
        # 清洗发生在**拆开之后**，所以段里绝不允许再出现 / 或 \
        assert "/" not in sanitize_component("a/b") and "\\" not in sanitize_component("a\\b")

    def test_尾点和尾空格被剥掉(self):
        # Windows 会静默丢掉结尾的点和空格：留着就有两个口径指向同一个目录
        assert sanitize_component("报告 ") == "报告"
        assert sanitize_component("报告.") == "报告"

    def test_保留设备名加前缀(self):
        # `nul.pdf`、`com1` 会被 Windows 当成设备，写进去直接失败
        assert sanitize_component("nul.pdf") == "_nul.pdf"
        assert sanitize_component("COM1") == "_COM1"
        assert sanitize_component("lpt9.txt") == "_lpt9.txt"

    def test_普通名字一个字节都不动(self):
        assert sanitize_component("合同 2024 年度") == "合同 2024 年度"

    def test_超长段截到上限(self):
        assert len(sanitize_component("名" * 900)) == MAX_SAFE_COMPONENT_LENGTH

    def test_全点清洗完是空(self):
        assert sanitize_component("...") == ""


class TestValidateTemplate:
    def test_默认模板合法(self):
        validate_template(DEFAULT_TEMPLATE)

    def test_空模板当场拒(self):
        with pytest.raises(TemplateError, match="空的"):
            validate_template("   ")

    def test_一个变量都没有也拒(self):
        # 全部文件落到同一个名字 = 第一项之后全是冲突，比报错更难发现
        with pytest.raises(TemplateError, match="一个变量都没有"):
            validate_template("归档文件.pdf")

    def test_未知变量点名是哪几个(self):
        # 报错必须把那个变量本身打出来（英文原词），只说"有未知变量"用户找不到是哪个字打错了
        with pytest.raises(TemplateError, match=r"\['author'\]"):
            validate_template("{category}/{author}/{name}.pdf")

    def test_不支持对齐与转换写法(self):
        with pytest.raises(TemplateError, match="对齐"):
            validate_template("{name:>20}")
        with pytest.raises(TemplateError, match="对齐"):
            validate_template("{name!r}")

    def test_绝对路径与盘符被拒(self):
        for bad in ("/etc/{name}", "C:\\归档\\{name}", "D:/x/{name}"):
            with pytest.raises(TemplateError, match="相对路径"):
                validate_template(bad)

    def test_模板里的双点被拒(self):
        # 目标必须落在目标根**里面**，`..` 是一条往外的逃逸路径
        with pytest.raises(TemplateError, match=r"\.\."):
            validate_template("../{name}")
        with pytest.raises(TemplateError, match=r"\.\."):
            validate_template("{category}/../../{name}.pdf")

    def test_变量口径只有三个(self):
        # 这三个名字就是 S7 界面文案与 S3 预览列的口径来源，多一个少一个都要同时改文档
        assert TEMPLATE_FIELDS == ("category", "year", "name")


class TestRenderRelative:
    def test_多级分类天然变成多级目录(self):
        got = render_relative(DEFAULT_TEMPLATE, {"category": "财务/报销", "year": "2024",
                                                "name": "报销A"})
        assert got == ("财务", "报销", "2024", "报销A.pdf")

    def test_反斜杠与正斜杠都是分隔符(self):
        assert render_relative("{category}\\{name}.pdf", {"category": "法律", "name": "判决"}) == \
            ("法律", "判决.pdf")

    def test_连续与多余的斜杠不产生空段(self):
        assert render_relative("{category}//{name}.pdf", {"category": "法律", "name": "判决"}) == \
            ("法律", "判决.pdf")

    def test_值里带双点当场拒(self):
        # 模板自己那条在 validate_template 就炸了；这一条拦的是**分类名**里蹦出来的 ..
        with pytest.raises(TemplateError, match=r"\.\."):
            render_relative("{category}/{name}.pdf", {"category": "..", "name": "判决"})

    def test_值清洗完是空段当场拒(self):
        # 文件名是 "..." 这种（剥掉后缀就什么都不剩）时，落出来的会是"只有目录没有文件"
        with pytest.raises(TemplateError, match="是空的"):
            render_relative("{category}/{name}", {"category": "财务", "name": "..."})

    def test_没传全变量当模板错误而不是KeyError(self):
        # 界面把这条原文显示给用户看，`'year'` 这种原文没人看得懂
        with pytest.raises(TemplateError, match="渲染失败"):
            render_relative(DEFAULT_TEMPLATE, {"category": "财务", "name": "报销A"})

    def test_缺分类与缺年份各有兜底目录名(self):
        assert UNCLASSIFIED_FOLDER == "_未分类"
        assert UNKNOWN_YEAR_FOLDER == "_无年份"


class TestValidatePathLength:
    """ISSUES I10：长路径的自检。这条以前**零测试**（台账里记着"由界面显示项销账"却没人断言过）。

    基准用相对路径：这条断言量的是**字符串长度**，与盘符无关，而 `tests/guards` 不许出现盘字样面量。
    """

    def test_上限之内放行(self):
        from pathlib import Path
        ok = Path("归档/财务") / ("名" * 100)
        assert len(str(ok)) < 240
        validate_path_length(ok)

    def test_超上限抛可读错误(self):
        from pathlib import Path
        too_long = Path("归档/财务") / ("名" * 400)
        with pytest.raises(PathTooLongError, match="目标路径过长"):
            validate_path_length(too_long)

    def test_错误消息带实长与上限两个数(self):
        # 只说"太长了"等于没说：用户要缩短多少、能不能靠 LongPathsEnabled 救，全靠这两个数
        from pathlib import Path
        p = Path("归档/财务") / ("名" * 400)
        with pytest.raises(PathTooLongError) as got:
            validate_path_length(p)
        message = str(got.value)
        assert f"{len(str(p))} 字符" in message
        assert "上限 240" in message

    def test_上限可以被调用方收紧(self):
        from pathlib import Path
        with pytest.raises(PathTooLongError):
            validate_path_length(Path("归档/一个很长的目录名.pdf"), limit=10)
