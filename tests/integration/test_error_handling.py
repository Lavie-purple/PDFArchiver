"""数据库与配置异常要**被记录、被处理**（阶段 1 验收第 4 条，SPEC 4.3「数据库损坏或锁定」）。

"处理"在这里的定义是三条，一条都不能少：
1. 原始错误文本进 app.log / crash.log（AGENTS.md：排障只认原始证据）；
2. 抛上来的异常带库路径，远程看一行就知道是哪个库；
3. 应用不静当作没事发生 —— 装配失败必须让组合根拿到非 0 退出码。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import threading
from datetime import datetime

import pytest

from pdfarchiver import app as appmod
from pdfarchiver.config.settings import SettingsError
from pdfarchiver.db.engine import DatabaseError, Engine
from pdfarchiver.db.migrate import MigrationError
from pdfarchiver.diagnostics.logs import (STAMP_RE, append_crash, install_crash_hooks,
                                          state_event)
from pdfarchiver.services.bootstrap import bootstrap


def _log_text(ctx) -> str:
    return (ctx.paths.logs_dir / "app.log").read_text(encoding="utf-8")


def test_DatabaseError的消息留着sqlite原文和库路径(ctx) -> None:
    ctx.catalog.add_tag("同名")
    with pytest.raises(DatabaseError) as e:
        ctx.catalog.add_tag("同名")
    msg = str(e.value)
    assert "UNIQUE" in msg.upper(), "要把 sqlite 原始文本带上，不然远程没法判断是谁拦的"
    assert "库=" in msg and str(ctx.engine.path) in msg, "要指得出是哪个库"
    assert isinstance(e.value.cause, sqlite3.IntegrityError), "原始异常对象不能丢"


def test_事务失败时回滚并带上出错场景说明(ctx) -> None:
    conn = ctx.engine.thread_connection()
    with pytest.raises(DatabaseError) as e:
        with ctx.engine.transaction(conn, on_error="批量写分类失败"):
            conn.execute("INSERT INTO tags(name, created_at) VALUES('回滚前的', 1)")
            conn.execute("INSERT INTO 不存在的表(x) VALUES(1)")
    assert "批量写分类失败" in str(e.value)
    assert conn.execute("SELECT count(*) FROM tags WHERE name='回滚前的'").fetchone()[0] == 0, \
        "事务里前半截没回滚 = 留下半条数据"


def test_设置文件损坏时启动失败且日志能定位到文件(data_root) -> None:
    cfg = data_root / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    target = cfg / "settings.json"
    target.write_text('{"worker_threads": "很多"}', encoding="utf-8")

    with pytest.raises(SettingsError) as e:
        bootstrap(data_root)
    assert str(target) in str(e.value)
    # 日志目录必须在读设置之前就绪，否则这条错误没人记得下来（AGENTS.md：任何异常都要能被远程读到）
    text = (data_root / "logs" / "app.log").read_text(encoding="utf-8")
    assert "设置文件读取失败" in text and str(target) in text
    state = (data_root / "logs" / "state.log").read_text(encoding="utf-8")
    assert "startup.settings_failed" in state


def test_库被锁住时报错带原文并且不吞掉(tmp_path) -> None:
    """SPEC 4.3「数据库锁定」。busy_timeout 用 200ms，免得测试真等 5 秒。"""
    db = tmp_path / "catalog.db"
    holder = sqlite3.connect(str(db))
    holder.execute("CREATE TABLE documents(x)")
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute("INSERT INTO documents VALUES(1)")

    engine = Engine(db, busy_timeout_ms=200)
    with pytest.raises((DatabaseError, sqlite3.OperationalError)) as e:
        conn = engine.connect()
        try:
            conn.execute("INSERT INTO documents VALUES(2)")
            conn.commit()
        finally:
            conn.close()
    assert "lock" in str(e.value).lower() or "busy" in str(e.value).lower()
    holder.close()


def test_迁移失败的现场同时留在日志和state_日志(data_root) -> None:
    mdir = data_root / "m"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "0001_boom.py").write_text(
        "VERSION = 1\n\n\ndef apply(conn):\n    raise ValueError('故意坏')\n", encoding="utf-8")
    with pytest.raises(MigrationError):
        bootstrap(data_root, migrations_dir=mdir)
    text = (data_root / "logs" / "app.log").read_text(encoding="utf-8")
    assert "迁移失败" in text and "故意坏" in text
    state = (data_root / "logs" / "state.log").read_text(encoding="utf-8")
    assert "startup.migration_failed" in state


def test_未捕获异常经excepthook落进crash_日志(tmp_path) -> None:
    from pdfarchiver.diagnostics.logs import crash_log_path

    install_crash_hooks(tmp_path)
    try:
        raise ValueError("主线程未捕获的测试异常")
    except ValueError:
        etype, value, tb = sys.exc_info()
        sys.excepthook(etype, value, tb)  # 直接调用钩子，不靠进程真的崩
    text = crash_log_path(tmp_path).read_text(encoding="utf-8")
    assert "主线程未捕获的测试异常" in text and "Traceback" in text


def test_后台线程里的异常也会留痕(tmp_path) -> None:
    """worker 线程抛出去的东西默认只打一行到 stderr 就没了（docs/ARCHITECTURE 三：worker 都在别的线程）。"""
    from pdfarchiver.diagnostics.logs import crash_log_path

    install_crash_hooks(tmp_path)
    done = threading.Event()

    def boom() -> None:
        try:
            raise RuntimeError("线程内的测试异常")
        except RuntimeError:
            args = sys.exc_info()

            class A:  # 直接喂 threading.excepthook，不依赖线程真的崩溃
                thread = None
                exc_info = args

            threading.excepthook(A())
        finally:
            done.set()

    t = threading.Thread(target=boom)
    t.start()
    t.join(2)
    assert done.is_set()
    assert "线程内的测试异常" in crash_log_path(tmp_path).read_text(encoding="utf-8")


def test_append_crash写不进去时不二次崩溃(tmp_path) -> None:
    """崩溃路径上的写入失败如果再抛，就把原始现场也弄丢了（SPEC 4.3 要求任何异常可诊断）。"""
    blocked = tmp_path / "占位"
    blocked.write_text("我是文件不是目录", encoding="utf-8")
    dest = append_crash("现场文本", blocked)  # log_dir 指向一个文件，写入必然失败
    assert not dest.exists()


def test_state_event一行一条JSON可被机器对账(tmp_path) -> None:
    (tmp_path / "logs").mkdir()
    state_event(tmp_path / "logs", "test.event", a=1, b="中文")
    line = (tmp_path / "logs" / "state.log").read_text(encoding="utf-8").strip()
    rec = json.loads(line)
    assert rec["event"] == "test.event" and rec["a"] == 1 and rec["b"] == "中文"
    assert STAMP_RE.fullmatch(rec["ts"]), f"对账用的 ts 必须自带 UTC 锚点：{rec['ts']}"


def test_装配失败时组合根返回非0并把堆栈写进crash_日志(data_root, capsys) -> None:
    cfg = data_root / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "settings.json").write_text("{ 坏 JSON", encoding="utf-8")
    code = appmod.run(["--data-dir", str(data_root)])
    assert code == appmod.EXIT_BOOTSTRAP_FAILED
    err = capsys.readouterr().err
    assert "启动失败" in err and "settings.json" in err
    crash = data_root / "logs" / "crash.log"
    assert crash.is_file() and "SettingsError" in crash.read_text(encoding="utf-8")


def test_坏值回落默认值时必须留下warning(bare_ctx, caplog) -> None:
    """`SettingsRepository.get` 对坏值可以回落默认，但必须留痕 —— 静默回落等于编造。"""
    ctx = bare_ctx
    conn = ctx.engine.thread_connection()
    conn.execute("INSERT INTO app_settings(key, value_json, kind, updated_at) VALUES('坏', ?, 'ui', 1)",
                 ("{ 不是 JSON",))
    conn.commit()
    with caplog.at_level(logging.WARNING, logger="pdfarchiver"):
        assert ctx.app_settings.get("坏", "兜底") == "兜底"
    assert "不是合法 JSON" in caplog.text


def test_三个日志出口用同一个时间口径(data_root) -> None:
    """AGENTS.md 禁止核心概念多个口径。时间戳的口径必须是：UTC ISO 8601 带 `Z`，三处一致。

    写成偏移量（+08:00）或裸 asctime 都算第二个口径 —— 对方拿 app.log 的一行和
    state.log 的一条 JSON 对时刻时，要先猜我这台机器在哪个时区，就等于没法远程诊断。
    """
    from pdfarchiver.diagnostics.logs import crash_log_path

    ctx = bootstrap(data_root)
    try:
        logging.getLogger("pdfarchiver.probe").error("口径自检留一行")
        for h in logging.getLogger("pdfarchiver").handlers:
            h.flush()

        app_lines = (ctx.paths.logs_dir / "app.log").read_text(encoding="utf-8").splitlines()
        assert app_lines, "app.log 是空的，下面的断言就全是摆设"
        for ln in app_lines:
            assert STAMP_RE.match(ln), f"app.log 行首不是 UTC+Z：{ln[:40]}"

        events = [json.loads(l) for l in
                  (ctx.paths.logs_dir / "state.log").read_text(encoding="utf-8").splitlines()]
        assert events
        for rec in events:
            assert STAMP_RE.fullmatch(rec["ts"]), f"state.log 的 ts 换了口径：{rec['ts']}"

        install_crash_hooks(ctx.paths.logs_dir)
        try:
            raise ValueError("口径自检的崩溃")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        head = re.search(r"===== (\S+) 未捕获异常", crash_log_path(ctx.paths.logs_dir).read_text(encoding="utf-8"))
        assert head and STAMP_RE.fullmatch(head.group(1)), f"crash.log 段头换了口径：{head}"

        # 同一次启动的两侧记录必须指同一瞬间（差 5 秒内），否则就是两块表
        first_app = datetime.fromisoformat(app_lines[0][:24].replace("Z", "+00:00")).timestamp()
        begin = [e for e in events if e["event"] == "startup.begin"][0]
        first_state = datetime.fromisoformat(begin["ts"].replace("Z", "+00:00")).timestamp()
        assert abs(first_app - first_state) < 5, f"app.log {first_app} vs state.log {first_state}"
    finally:
        ctx.shutdown()
