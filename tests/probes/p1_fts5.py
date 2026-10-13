"""P1 全文检索探针：SQLite FTS5 在中文语料上的真实行为与量级外推。

回答的问题（每条打印可判定结论，不接受"看起来能用"）：
  Q1 FTS5 与 trigram tokenizer 在目标 Python 的 sqlite3.dll 里是否可用
  Q2 查询词 1/2/3/4+ 字在各方案下的命中数——"搜不到"必须是可见的 0，不许静默
  Q3 真实规模（7,768 份 x 平均页数）下建索引耗时、库体积、查询延迟
  Q4 外部内容表（正文只存一份，索引不复制正文）的增删改是否真的同步
  Q5 snippet()/offsets()/highlight() 能否用于"结果页码 + 命中高亮"
  Q6 WAL 一写多读是否阻塞读；backup API 一致性快照是否可用
  Q7 索引 rebuild 耗时（决定"重建索引"功能能不能对用户承诺）

正文是合成的中文段落，用于测规模与延迟；检索质量结论以 p2 真实 PDF 抽样为准。

用法: python tests/probes/p1_fts5.py [--rows 150000] [--quick] [--work .probe_work] [--out FILE.json]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
import threading
import time

CORPUS = [
    "人工智能产业在近三年的发展速度显著超出预期，大模型的训练成本持续下降。",
    "本报告分析了游戏行业的收入结构与用户付费行为，重点比较主机与移动端。",
    "量子计算的研究进展表明纠错码仍然是实现通用量子计算机的主要瓶颈。",
    "深度学习模型在自然语言处理任务上优于传统统计方法，但可解释性不足。",
    "金融市场波动加剧，投资者对固定收益类资产配置的需求明显上升。",
    "课程设计应遵循以学生为中心的原则，将评价指标与学习目标逐条对应。",
    "供应链管理中库存周转率与交付准时率常常存在此消彼长的关系。",
    "白皮书提出了跨平台渲染引擎的抽象层设计，并给出性能基准测试方法。",
    "城市规划中的交通拥堵需要结合公交线网密度与路网容量共同分析。",
    "医学影像自动分割依赖标注数据质量，标注不一致会直接放大模型偏差。",
    "半导体代工产能紧张，先进封装成为提升系统性能的关键路径之一。",
    "消费者调研显示，价格敏感度在二线城市的下降速度快于一线城市。",
    "电池材料的能量密度提升伴随着安全裕度的收窄，热管理设计因此更复杂。",
    "合同条款中关于知识产权归属的约定，应当与研发记录的署名保持一致。",
    "前端框架的渲染性能差异主要体现在长列表更新与状态订阅的粒度上。",
    "数据库索引的选择需要在写入放大与查询加速之间取得平衡。",
    "教育公平指标的区域差异，与师资流动性和财政转移支付高度相关。",
    "临床试验的入组标准过严会降低外部效度，过松则放大混杂偏倚。",
    "风控模型在样本外表现下滑，通常说明特征存在时间泄漏。",
    "城市燃气管网的巡检周期应按管龄、材质与周边人口密度分层设定。",
    "游戏美术风格的统一依赖色板约束，而非单个画师的个人偏好。",
    "学术论文的引用网络可用于识别研究前沿的分裂与融合时间点。",
    "音频降噪算法在低信噪比条件下容易引入音乐噪声，需权衡抑制强度。",
    "仓储机器人的调度目标是最小化总行驶距离，同时满足出库时间窗。",
    "法律条文的司法解释在适用顺序上优先于地方性的执行口径。",
    "组织内的知识沉淀如果只依赖个人笔记，会在人员流动时大量流失。",
    "推荐系统的短期点击率提升可能以长期留存下降为代价。",
    "分子对接的打分函数对柔性侧链的构象采样仍不够充分。",
    "教学评估中的课堂参与度难以用单一指标衡量，需要多源证据交叉。",
    "债券久期是利率敏感性的近似，凸性修正在中长期品种上不可忽略。",
    "图像超分辨率模型在人脸区域易产生结构畸变，需要专门的后处理。",
    "编译器内联策略过于激进会扩大代码体积并损害指令缓存命中率。",
    "农业灌溉用水量与土壤含水率传感器读数之间存在明显的空间异质性。",
    "谈判中的锚定效应会使后续让步区间被初始报价非对称地压缩。",
    "碳纤维复材的疲劳寿命受铺层方向与孔隙率的共同影响。",
    "多语言预训练词表过大时，低频语言的子词切分会变得不稳定。",
    "急诊分诊的准确性依赖生命体征与主诉的组合判断，单指标误判率高。",
    "广告竞价机制中二价拍卖在真实出价下才是激励相容的。",
    "机器人路径规划在动态障碍场景下需要保留重规划的时间预算。",
    "会计准则对研发支出资本化的认定条件，直接影响了利润表的形状。",
]

QUERIES = ["人工智能", "人工", "智", "产业", "量子计算", "渲染引擎", "供应链", "库存周转率"]


def reset(path: str) -> None:
    for p in (path, path + "-wal", path + "-shm"):
        if os.path.exists(p):
            os.remove(p)


def db_bytes(path: str) -> int:
    return sum(os.path.getsize(p) for p in (path, path + "-wal", path + "-shm") if os.path.exists(p))


def bigram(text: str) -> str:
    return " ".join(text[i:i + 2] for i in range(len(text) - 1)) if len(text) > 1 else text


def make_pages(conn: sqlite3.Connection, rows: int, rng: random.Random) -> None:
    conn.execute(
        "CREATE TABLE pages(doc_id INTEGER NOT NULL, page_no INTEGER NOT NULL, "
        "body TEXT NOT NULL, source_kind TEXT NOT NULL, PRIMARY KEY(doc_id, page_no))"
    )
    batch = []
    t0 = time.perf_counter()
    with conn:
        for i in range(rows):
            body = "".join(rng.choice(CORPUS) for _ in range(rng.randint(1, 3)))
            batch.append((i // 40, i % 40, body, "native"))
            if len(batch) >= 5000:
                conn.executemany("INSERT INTO pages VALUES(?,?,?,?)", batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT INTO pages VALUES(?,?,?,?)", batch)
    return time.perf_counter() - t0


def run_queries(conn: sqlite3.Connection, use_like: bool) -> tuple[dict, dict]:
    hits, lat = {}, {}
    for q in QUERIES:
        t0 = time.perf_counter()
        try:
            if len(q) >= 3 or not use_like:
                n = conn.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH ?", (f'"{q}"',)).fetchone()[0]
                via = "fts"
            else:
                n = conn.execute("SELECT count(*) FROM pages WHERE body LIKE ?", (f"%{q}%",)).fetchone()[0]
                via = "like_fallback"
        except sqlite3.OperationalError as exc:
            n, via = f"ERROR: {exc}", "error"
        hits[q] = {"count": n, "via": via, "chars": len(q)}
        lat[q] = round((time.perf_counter() - t0) * 1000, 2)
    return hits, lat


def aux_functions(conn: sqlite3.Connection, q: str) -> dict:
    out: dict = {}
    try:
        r = conn.execute(
            "SELECT p.doc_id, p.page_no, snippet(pages_fts, 0, '[', ']', ' ~ ', 12) "
            "FROM pages_fts JOIN pages p ON p.rowid = pages_fts.rowid WHERE pages_fts MATCH ? LIMIT 1",
            (f'"{q}"',),
        ).fetchone()
        out["snippet"] = {"works": r is not None, "doc_id": r[0] if r else None, "page_no": r[1] if r else None, "sample": (r[2][:48] if r else None)}
    except sqlite3.OperationalError as exc:
        out["snippet"] = {"works": False, "error": str(exc)}
    for fname in ("offsets", "highlight"):
        try:
            if fname == "offsets":
                r = conn.execute("SELECT offsets(pages_fts) FROM pages_fts WHERE pages_fts MATCH ? LIMIT 1", (f'"{q}"',)).fetchone()
            else:
                r = conn.execute("SELECT highlight(pages_fts, 0, '[', ']') FROM pages_fts WHERE pages_fts MATCH ? LIMIT 1", (f'"{q}"',)).fetchone()
            out[fname] = {"works": r is not None, "sample": (r[0][:80] if r and r[0] else None)}
        except sqlite3.OperationalError as exc:
            out[fname] = {"works": False, "error": str(exc)}
    try:
        t0 = time.perf_counter()
        rows = conn.execute(
            "SELECT p.doc_id, p.page_no, bm25(pages_fts) AS s FROM pages_fts "
            "JOIN pages p ON p.rowid = pages_fts.rowid "
            "WHERE pages_fts MATCH ? ORDER BY s LIMIT 50",
            (f'"{q}"',),
        ).fetchall()
        out["bm25_top50"] = {"works": len(rows) > 0, "ms": round((time.perf_counter() - t0) * 1000, 2), "n": len(rows)}
    except sqlite3.OperationalError as exc:
        out["bm25_top50"] = {"works": False, "error": str(exc)}
    return out


def build_trigram(rows: int, work: str) -> dict:
    path = os.path.join(work, "p1_trigram.db")
    reset(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    rng = random.Random(20261014)
    raw_s = make_pages(conn, rows, rng)
    conn.execute("CREATE VIRTUAL TABLE pages_fts USING fts5(body, content='pages', content_rowid='rowid', tokenize='trigram')")
    # 外部内容表不会自动同步：必须显式建触发器，或用 'rebuild' 全量回填。这里两条都要验证。
    conn.executescript(
        """
        CREATE TRIGGER pages_ai AFTER INSERT ON pages BEGIN
          INSERT INTO pages_fts(rowid, body) VALUES (new.rowid, new.body);
        END;
        CREATE TRIGGER pages_ad AFTER DELETE ON pages BEGIN
          INSERT INTO pages_fts(pages_fts, rowid, body) VALUES ('delete', old.rowid, old.body);
        END;
        CREATE TRIGGER pages_au AFTER UPDATE ON pages BEGIN
          INSERT INTO pages_fts(pages_fts, rowid, body) VALUES ('delete', old.rowid, old.body);
          INSERT INTO pages_fts(rowid, body) VALUES (new.rowid, new.body);
        END;
        """
    )
    t0 = time.perf_counter()
    conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('rebuild')")
    conn.commit()
    build_s = time.perf_counter() - t0
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    res = {
        "available": True,
        "raw_table_seconds": round(raw_s, 2),
        "index_build_seconds": round(build_s, 2),
        "rows": rows,
        "db_bytes_total": db_bytes(path),
        "text_bytes": conn.execute("SELECT sum(length(CAST(body AS BLOB))) FROM pages").fetchone()[0],
    }
    res["db_over_text_ratio"] = round(res["db_bytes_total"] / max(1, res["text_bytes"]), 2)
    res["hits"], res["query_ms"] = run_queries(conn, use_like=True)
    res["aux"] = aux_functions(conn, "人工智能")
    res["available_aux_functions"] = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT name FROM pragma_function_list "
            "WHERE name IN ('offsets','snippet','highlight','bm25','matchinfo','rank')"
        ).fetchall()
    ]
    # 确定性同步测试：插入一行带唯一标记词 -> 改 -> 删，逐步验证触发器是否真的同步索引
    def count(term: str) -> int:
        return conn.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH ?", (f'"{term}"',)).fetchone()[0]

    marker_a, marker_b = "甲乙丙丁子午卯酉", "戊己庚辛辰戌丑未"
    conn.execute("INSERT INTO pages VALUES(99001, 1, ?, 'native')", (f"一段普通文字 {marker_a} 收尾",))
    conn.commit()
    a_after_insert = count(marker_a)
    conn.execute("UPDATE pages SET body=? WHERE doc_id=99001", (f"换了内容 {marker_b} 收尾",))
    conn.commit()
    a_after_update = count(marker_a)
    b_after_update = count(marker_b)
    conn.execute("DELETE FROM pages WHERE doc_id=99001")
    conn.commit()
    b_after_delete = count(marker_b)
    row0 = conn.execute("SELECT body FROM pages WHERE doc_id=0 AND page_no=0").fetchone()[0]
    res["external_content_sync"] = {
        "insert_indexed": a_after_insert,
        "old_marker_after_update": a_after_update,
        "new_marker_after_update": b_after_update,
        "marker_after_delete": b_after_delete,
        "sample_row_present": row0 is not None,
    }
    t0 = time.perf_counter()
    n = conn.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH '\"量子计算\"'").fetchone()[0]
    res["top20_at_scale"] = {"count": n, "ms": round((time.perf_counter() - t0) * 1000, 2)}
    conn.close()
    return res


def build_bigram(rows: int, work: str) -> dict:
    path = os.path.join(work, "p1_bigram.db")
    reset(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    rng = random.Random(20261014)
    conn.execute("CREATE TABLE pages(doc_id INTEGER NOT NULL, page_no INTEGER NOT NULL, body TEXT NOT NULL, gram TEXT NOT NULL, source_kind TEXT, PRIMARY KEY(doc_id,page_no))")
    t0 = time.perf_counter()
    batch = []
    with conn:
        for i in range(rows):
            body = "".join(rng.choice(CORPUS) for _ in range(rng.randint(1, 3)))
            batch.append((i // 40, i % 40, body, bigram(body), "native"))
            if len(batch) >= 5000:
                conn.executemany("INSERT INTO pages VALUES(?,?,?,?,?)", batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT INTO pages VALUES(?,?,?,?,?)", batch)
    raw_s = time.perf_counter() - t0
    conn.execute("CREATE VIRTUAL TABLE pages_fts USING fts5(gram, content='pages', content_rowid='rowid')")
    t0 = time.perf_counter()
    conn.execute("INSERT INTO pages_fts(pages_fts) VALUES('rebuild')")
    conn.commit()
    build_s = time.perf_counter() - t0
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    res = {
        "available": True,
        "raw_table_seconds": round(raw_s, 2),
        "index_build_seconds": round(build_s, 2),
        "db_bytes_total": db_bytes(path),
        "text_bytes": conn.execute("SELECT sum(length(CAST(body AS BLOB))) FROM pages").fetchone()[0],
        "note": "gram 列把正文按 2 字滑窗复制了一份，体积代价必须单独看",
    }
    res["db_over_text_ratio"] = round(res["db_bytes_total"] / max(1, res["text_bytes"]), 2)
    hits, lat = {}, {}
    for q in QUERIES:
        t0 = time.perf_counter()
        pattern = bigram(q) if len(q) >= 2 else q
        try:
            n = conn.execute("SELECT count(*) FROM pages_fts WHERE pages_fts MATCH ?", (f'"{pattern}"',)).fetchone()[0]
        except sqlite3.OperationalError as exc:
            n = f"ERROR: {exc}"
        hits[q] = {"count": n, "chars": len(q)}
        lat[q] = round((time.perf_counter() - t0) * 1000, 2)
    res["hits"] = hits
    res["query_ms"] = lat
    t0 = time.perf_counter()
    res["single_char_like_count"] = conn.execute("SELECT count(*) FROM pages WHERE body LIKE ?", ("%智%",)).fetchone()[0]
    res["single_char_like_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    conn.close()
    return res


def build_unicode61(rows: int, work: str) -> dict:
    """对照组：不做任何中文处理，直接 FTS5 默认 unicode61。预期 4 字词命中 0。"""
    path = os.path.join(work, "p1_unicode61.db")
    reset(path)
    conn = sqlite3.connect(path)
    rng = random.Random(20261014)
    conn.execute("CREATE VIRTUAL TABLE pages USING fts5(doc_id UNINDEXED, page_no UNINDEXED, body)")
    data = [(i // 40, i % 40, "".join(rng.choice(CORPUS) for _ in range(2))) for i in range(rows)]
    with conn:
        conn.executemany("INSERT INTO pages VALUES(?,?,?)", data)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    hits = {}
    for q in QUERIES:
        try:
            hits[q] = conn.execute("SELECT count(*) FROM pages WHERE pages MATCH ?", (f'"{q}"',)).fetchone()[0]
        except sqlite3.OperationalError as exc:
            hits[q] = f"ERROR: {exc}"
    res = {"available": True, "db_bytes_total": db_bytes(path), "hits": hits}
    res["like_check_on_same_data"] = conn.execute("SELECT count(*) FROM pages WHERE body LIKE ?", ('%人工智能%',)).fetchone()[0]
    conn.close()
    return res


def delete_trigger_trap() -> dict:
    """负例：'delete' 命令省略被索引列时的真实行为。用来证明正确写法不是可选的。"""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE p(body TEXT)")
    conn.execute("CREATE VIRTUAL TABLE pf USING fts5(body, content='p', content_rowid='rowid', tokenize='trigram')")
    conn.executescript(
        """
        CREATE TRIGGER p_ad AFTER DELETE ON p BEGIN
          INSERT INTO pf(pf, rowid) VALUES ('delete', old.rowid);
        END;
        """
    )
    conn.execute("INSERT INTO p VALUES('独一无二的词甲乙丙丁')")
    conn.execute("INSERT INTO pf(rowid, body) VALUES(last_insert_rowid(), '独一无二的词甲乙丙丁')")
    conn.commit()
    before = conn.execute("SELECT count(*) FROM pf WHERE pf MATCH '\"甲乙丙丁\"'").fetchone()[0]
    conn.execute("DELETE FROM p WHERE rowid=1")
    conn.commit()
    after = conn.execute("SELECT count(*) FROM pf WHERE pf MATCH '\"甲乙丙丁\"'").fetchone()[0]
    rows_left = conn.execute("SELECT count(*) FROM p").fetchone()[0]
    conn.close()
    return {
        "wrong_form_hits_before_delete": before,
        "wrong_form_hits_after_delete": after,
        "content_table_rows_after_delete": rows_left,
        "conclusion": "省略被索引列时 SQLite 不报错，索引残留幽灵行 -> 删除后仍能搜到已删文件",
    }


def probe_wal_and_backup(work: str) -> dict:
    path = os.path.join(work, "p1_wal.db")
    reset(path)
    boot = sqlite3.connect(path)
    boot.execute("PRAGMA journal_mode=WAL")
    boot.execute("PRAGMA synchronous=NORMAL")
    boot.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v TEXT)")
    boot.commit()
    boot.close()
    lat: list[float] = []
    stop = threading.Event()
    errors: list[str] = []
    lock = threading.Lock()

    def writer() -> None:
        conn_w = sqlite3.connect(path, timeout=15)
        try:
            for i in range(40):
                with conn_w:
                    conn_w.executemany("INSERT INTO t(v) VALUES (?)", [(f"row-{i}-{j}",) for j in range(500)])
        except sqlite3.Error as exc:
            errors.append(f"writer: {type(exc).__name__}: {exc}")
        finally:
            conn_w.close()

    def reader() -> None:
        conn_r = sqlite3.connect(path, timeout=15)
        try:
            while not stop.is_set():
                t0 = time.perf_counter()
                conn_r.execute("SELECT count(*) FROM t").fetchone()
                with lock:
                    lat.append((time.perf_counter() - t0) * 1000)
                time.sleep(0.005)
        except sqlite3.Error as exc:
            errors.append(f"reader: {type(exc).__name__}: {exc}")
        finally:
            conn_r.close()

    tw, tr = threading.Thread(target=writer), threading.Thread(target=reader)
    t0 = time.perf_counter()
    tw.start()
    tr.start()
    tw.join()
    stop.set()
    tr.join()
    res = {
        "write_seconds": round(time.perf_counter() - t0, 2),
        "rows": sqlite3.connect(path).execute("SELECT count(*) FROM t").fetchone()[0],
        "reads_sampled": len(lat),
        "read_ms_max": round(max(lat), 2) if lat else None,
        "read_ms_p99": round(sorted(lat)[int(len(lat) * 0.99)], 2) if lat else None,
        "errors": errors,
    }
    snap = os.path.join(work, "p1_snapshot.db")
    reset(snap)
    src = sqlite3.connect(path)
    dst = sqlite3.connect(snap)
    with dst:
        src.backup(dst)
    res["backup_bytes"] = os.path.getsize(snap)
    res["backup_integrity"] = dst.execute("PRAGMA integrity_check").fetchone()[0]
    res["backup_row_count"] = dst.execute("SELECT count(*) FROM t").fetchone()[0]
    dst.close()
    src.close()
    res["cross_thread_connection_note"] = "sqlite3.Connection 默认 check_same_thread=True：每个后台 worker 必须自开连接，不能共享"
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=300_000)
    ap.add_argument("--work", default=".probe_work")
    ap.add_argument("--out", default=".probe_work/p1_fts5_result.json")
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    # Windows 控制台默认 GBK，中文输出会碎成乱码；探针统一强制 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    os.makedirs(args.work, exist_ok=True)
    rows = 3000 if args.quick else args.rows

    report = {
        "python": sys.version.split()[0],
        "sqlite_version": sqlite3.sqlite_version,
        "rows_tested": rows,
        "unicode61": build_unicode61(rows, args.work),
        "trigram": build_trigram(rows, args.work),
        "bigram": build_bigram(rows, args.work),
        "wal_backup": probe_wal_and_backup(args.work),
        "delete_trigger_trap": delete_trigger_trap(),
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    tri, big, uni, wal = report["trigram"], report["bigram"], report["unicode61"], report["wal_backup"]
    ec = tri["external_content_sync"]
    checks = [
        ("sqlite >= 3.34 (trigram 前置条件)", tuple(int(x) for x in sqlite3.sqlite_version.split(".")[:2]) >= (3, 34)),
        ("trigram 表可创建", tri.get("available") is True),
        ("默认 unicode61 对 4 字中文词命中为 0（证明不能裸用）", uni["hits"].get("人工智能") == 0),
        ("LIKE 证明数据里确实有该词（排除语料本身的问题）", uni.get("like_check_on_same_data", 0) > 0),
        ("trigram 对 4 字词有命中", isinstance(tri["hits"]["人工智能"]["count"], int) and tri["hits"]["人工智能"]["count"] > 0),
        ("bigram 对 4 字词有命中", isinstance(big["hits"]["人工智能"]["count"], int) and big["hits"]["人工智能"]["count"] > 0),
        ("bigram 对 2 字词有命中（trigram 需要 >=3 字）", isinstance(big["hits"]["人工"]["count"], int) and big["hits"]["人工"]["count"] > 0),
        ("FTS5 无 offsets()（位置需 Python 侧计算，方案据此定）", "offsets" not in (tri.get("available_aux_functions") or [])),
        ("外部内容表+触发器：INSERT 即被索引", ec["insert_indexed"] == 1),
        ("外部内容表+触发器：UPDATE 后旧词消失、新词可搜", ec["old_marker_after_update"] == 0 and ec["new_marker_after_update"] == 1),
        ("外部内容表+触发器：DELETE 后索引清除", ec["marker_after_delete"] == 0),
        ("WAL 读查询 p99 < 20ms", (wal["read_ms_p99"] or 999) < 20),
        ("一写多读无 sqlite 错误", not wal["errors"]),
        ("负例成立：省略列的错误写法会留下幽灵行（证明上一条断言可被欺骗）", report["delete_trigger_trap"]["wrong_form_hits_after_delete"] == 1),
        ("backup API 快照行数一致且 integrity ok", wal["backup_integrity"] == "ok" and wal["backup_row_count"] == wal["rows"]),
    ]
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print(f"  INFO trigram: raw {tri['raw_table_seconds']}s + index {tri['index_build_seconds']}s / {rows} rows, ratio {tri['db_over_text_ratio']}")
    print(f"  INFO bigram : raw {big['raw_table_seconds']}s + index {big['index_build_seconds']}s / {rows} rows, ratio {big['db_over_text_ratio']}")
    print(f"  INFO trigram aux: {json.dumps(tri['aux'], ensure_ascii=False)[:300]}")
    print(f"  INFO 1-2 字 LIKE 回退: {tri['query_ms'].get('人工')}ms / {tri['query_ms'].get('智')}ms")
    print(f"  INFO 30 万行 LIKE 全表扫描就是上面这两个数（决定要不要单字/双字副表）")
    print("VERDICT: " + ("ALL GREEN" if all(ok for _, ok in checks) else "RED"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
