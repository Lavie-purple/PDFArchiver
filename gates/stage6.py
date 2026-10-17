#!/usr/bin/env python
"""阶段 6 门禁：语义搜索层。

验收：
1. EmbeddingService 能实例化
2. VectorStore 实例化后**不许**在缺表时静默建表 —— 必须报 `VectorSchemaMissing` 并指名迁移 0007
   （`vector_meta` 的结构由迁移定义，ISSUES I62）
3. VectorStore 能对真迁移链建出来的库增删查
4. SemanticSearchService 能实例化，空查询返回空
5. 阶段 3 / 阶段 4 的门禁**不在这里代跑**：本脚本只判定上面四条真跑过的，
   阶段 3/4 由 `gates/stage3.py`、`gates/stage4.py` 各自验（见末尾 SKIP 行）

用法：
    python gates/stage6.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 把 src 加到路径
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

JUDGED: list[tuple[str, bool]] = []    # 真判定过的项目，用来数「合计判定 N 条」


def check(label: str, ok: bool, detail: str = "") -> bool:
    """打印并登记一条判定。"""
    JUDGED.append((label, ok))
    status = "PASS" if ok else "FAIL"
    msg = f"[{status}] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return ok


def main() -> int:
    print("=" * 70)
    print("阶段 6 门禁 · 语义搜索层")
    print("=" * 70)

    # 1. EmbeddingService 能实例化
    try:
        from pdfarchiver.semantic.embedding import EmbeddingService
        emb = EmbeddingService()
        check("EmbeddingService 实例化", True)
    except Exception as exc:
        check("EmbeddingService 实例化", False, str(exc))

    # 2. VectorStore 实例化 + 缺表时响亮报错
    try:
        import tempfile
        from pdfarchiver.config.paths import AppPaths
        from pdfarchiver.semantic.vector_store import VectorStore, VectorSchemaMissing

        with tempfile.TemporaryDirectory() as bare:
            # 空目录 = 一个字段都没迁移过的库。以前这一步会**静默建表**（ISSUES I62），
            # 现在必须响亮拒绝 —— 静默建表让同一个 schema_version 对应两种库形状。
            AppPaths.resolve(Path(bare)).mkdirs()
            try:
                VectorStore(Path(bare)).count()
                check("VectorStore 实例化", False,
                                  "库里没有 vector_meta 却成功了 —— 运行时建表又回来了")
            except VectorSchemaMissing as exc:
                ok = "0007" in str(exc)
                check("VectorStore 实例化", ok, "" if ok else f"报错没指名迁移 0007：{exc}")
            except Exception as exc:  # noqa: BLE001 - 报错原文要进门禁输出，不许转述
                check("VectorStore 实例化", False, f"异常类型不对：{type(exc).__name__}: {exc}")
    except Exception as exc:
        check("VectorStore 实例化", False, str(exc))

    # 3. SemanticSearchService 能实例化
    try:
        from pdfarchiver.semantic.search_service import SemanticSearchService
        ss = SemanticSearchService()
        check("SemanticSearchService 实例化", True)
    except Exception as exc:
        check("SemanticSearchService 实例化", False, str(exc))

    # 4. 空查询返回空列表
    try:
        from pdfarchiver.semantic.search_service import SemanticSearchService
        ss = SemanticSearchService()
        results = ss.search("")
        ok = results == []
        check("空查询返回空列表", ok, f"got {results}")
    except Exception as exc:
        check("空查询返回空列表", False, str(exc))

    # 5. VectorStore 基本操作
    try:
        import tempfile
        import sqlite3
        import numpy as np
        from pdfarchiver.config.paths import AppPaths
        from pdfarchiver.db.engine import Engine
        from pdfarchiver.db.migrate import migrate
        from pdfarchiver.semantic.vector_store import VectorStore

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # 走**真实迁移链**建库，不手抄 DDL —— 手抄那份已经悄悄少了 `is_encrypted` 列，
            # 而结构只能由迁移定义（docs/DATABASE 四、ISSUES I62）
            paths = AppPaths.resolve(tmpdir)
            paths.mkdirs()
            engine = Engine(paths.catalog_db)
            migrate(engine, backup_dir=paths.backups_dir)
            engine.close_thread_connection()
            db_path = paths.catalog_db

            vs = VectorStore(tmpdir)

            # 真库的 `documents` 有一串 NOT NULL 无默认值的列，插入必须给全（手抄那份宽松 DDL
            # 掩盖了这一点，所以这条 INSERT 从没被真库验过 —— 换成迁移链之后第一次跑就红了）
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "INSERT INTO documents (path, path_key, name, ext, size_bytes, mtime_ns,"
                    " created_at, updated_at, parse_status, text_status, ocr_status,"
                    " fts_status, vector_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("C:/test/doc.pdf", "test/doc.pdf", "doc.pdf", "pdf", 1000, 1000000000,
                     1, 1, "pending", "pending", "na", "pending", "na"))
                doc_id = conn.execute("SELECT id FROM documents WHERE path_key='test/doc.pdf'").fetchone()[0]
                conn.commit()
            finally:
                # 必须在这里就关掉：留着句柄，临时目录清理时 rmtree  unlink 失败，
                # 报出来的是 `[WinError 267] 目录名称无效`（实测会把真正的 IntegrityError 盖掉）
                conn.close()

            # 添加向量
            vector = np.random.randn(512).astype(np.float32)
            vector = vector / np.linalg.norm(vector)
            idx = vs.add(doc_id, 1, vector)
            ok = idx >= 0
            check("VectorStore.add", ok, f"idx={idx}")

            # 搜索
            results = vs.search(vector, top_k=1)
            ok = len(results) == 1 and results[0][0] == doc_id
            check("VectorStore.search", ok, f"results={results}")

            # 计数
            count = vs.count()
            ok = count == 1
            check("VectorStore.count", ok, f"count={count}")
    except Exception as exc:
        check("VectorStore 基本操作", False, str(exc))

    # 6. 阶段 3 / 阶段 4 的门禁不在这里代跑。
    # 原来这里是两行 `check("…门禁回归", True, "跳过")` —— 结构上永远不会变红，却进了
    # 判定序列，正是 `gates/final.py` 那条「未跑却算 PASS」的同一形状（ISSUES I36）。
    # 代跑还会把负载绑定的冷启动读数嵌进这一场（D-033：满载机器上同一命令会判 RED）。
    print("\n—— 本场未跑的判定 ——")
    print("  SKIP  阶段 3 门禁（gates/stage3.py）与阶段 4 门禁（gates/stage4.py）"
          "：这一场不判它们，全绿不覆盖它们")

    failed = [label for label, ok in JUDGED if not ok]
    print("\n" + "=" * 70)
    print(f"合计判定 {len(JUDGED)} 条｜本场未跑 2 项（阶段 3 / 阶段 4 门禁）")
    if not failed:
        print("VERDICT: ALL GREEN")
        print("=" * 70)
        return 0
    print(f"VERDICT: RED（{len(failed)} 条未过：{'、'.join(failed)}）")
    print("=" * 70)
    return 1


if __name__ == "__main__":
    sys.exit(main())
