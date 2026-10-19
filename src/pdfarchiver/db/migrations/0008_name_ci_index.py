"""0008 · 给 `documents.name` 建一条区分大小写的表达式索引（**ISSUES I77** 的"甲"）。

**为什么要有它**：文档库那一列是分批取的（**ISSUES I51**），每批的 SQL 是
`ORDER BY d.name COLLATE NOCASE, d.id LIMIT ? OFFSET ?`（排序口径唯一定义在
`db/repositories/documents.py::SORTS["name"]`）。`0001_initial.py` 在 `documents` 上只建了
`ux_documents_path_key` / `ix_documents_sha` / 部分索引 `ix_documents_missing` —— **没有一条
能供 name 排序用**，所以 SQLite 每取一批都要把全表排一遍，`OFFSET` 越深排得越久。

8 万份的临时库里逐深度实测（`.probe_work/i51_1018/depth_80000.json`，2026-10-18，
每档都是「一批 50 行」的后端耗时，不含界面建行的成本）：

| 深度（offset） | 无索引 | 有索引 |
| --- | --- | --- |
| 0 | 64.3ms | 1.7ms |
| 1,000 | 83.6ms | 1.7ms |
| 10,000 | 217.8ms | 2.9ms |
| 40,000 | 468.9ms | 6.7ms |
| 79,950（库尾） | 772.9ms | **12.4ms（62×）** |

代价两处，也都是同一场实测：建索引 **0.337s@8 万份**（首启/升级时一次性），
写入侧 **0.908 → 0.975 ms/份（+7.4%）** —— 每入库一份要多维护一棵 B 树。

**为什么是表达式索引而不是 `COLLATE NOCASE` 加在列上**：列上加 COLLATE 要改 `documents.name`
的 DDL，SQLite 只能重建整张表（`docs/DATABASE.md` 四：不许让用户删库重来），而且会顺带改掉
所有按 name 比较的语义。表达式索引 `ON documents(name COLLATE NOCASE)` 不动列、不动数据、
不动任何接口，与排序表达式**逐字**同形才能被查询规划器认下。

**`IF NOT EXISTS` 不是形式主义**：同名索引此前由那两支探针在**临时库**里手动建过
（`browse_depth_probe.py:118` / `index_write_probe.py:45`，都没碰真库也没进产品代码），
而迁移是可以重放的（水位被人工改回去、或同一份库换机器再升一次）；任何已经带着这条索引的库
碰 0008 必须是无操作，而不是 `index ... already exists` 把整笔迁移回滚掉。

它**不解决**另一半问题：滚过的行不释放、也不满足 §S1 线框那句「只渲染视口内 ~25 行」——
那是真虚拟化（本条"乙"，`QTableView` + `QAbstractTableModel`），要动列宽口径与 25 处
`.item(r, c)` 型断言，排在界面线框轮之后。
"""
from __future__ import annotations

VERSION = 8


def apply(conn) -> None:  # noqa: ANN001 - sqlite3.Connection，不 import 类型以免多一层依赖
    """整个函数在调用方的一个事务里执行：中途失败整体回滚，库回到 0007。

    不跟 `ANALYZE`。实测这条索引不需要统计信息就被用上（同一份库 `EXPLAIN QUERY PLAN`
    两种状态都是 `USING INDEX ix_documents_name_ci`），而 `ANALYZE` 是 O(库大小) 的慢操作 ——
    把它放进迁移等于给首启加一次全表采样（**ISSUES I45** 那条「慢操作只许放在显式慢路径」）。
    """
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_name_ci ON documents(name COLLATE NOCASE)"
    )


def rollback(conn) -> None:
    """回到 0007：只把索引撤掉。

    与 0006/0007 一样，这条**只由人手动执行**（迁移执行器只往前不往后，见 `db/migrate.py` 规矩 3）。
    索引里没有用户数据，删它不丢任何东西，代价只是深分页退回每批全表排序。
    """
    conn.execute("DROP INDEX IF EXISTS ix_documents_name_ci")
