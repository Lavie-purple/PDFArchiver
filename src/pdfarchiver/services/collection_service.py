"""智能集合的口径层（**ISSUES I78** 乙，2026-10-19）—— 一组筛选条件只有一份表示法。

线框 §I78-yi（`docs/wireframes/2026-10-19-round14-i67-i78.html`）要的是：S1 顶栏把当前
筛选条件排成 chips、一键存成集合；S8 右栏的集合点开把那份条件灌回 S1。既然读写同源，
本模块只做三件界面自己做不到、也不许自己另算一遍的事：

1. **存之前先把条件读回一次**（`Criteria.from_query` 是唯一能判"这份 dict 到底生不生效"的人）。
   咽下去的后果是屏幕上写着筛过、库里一条 WHERE 都没加。
2. **命中数由 SQL 数**（`documents.count_matching`），不是界面数表格行数 —— 表格被 **ISSUES I51**
   虚拟化过，屏幕上那一屏从来不是全部；而 `count_matching` 用的 WHERE 与回放那张表的是同一份
   （`Criteria.browse_page().doc_filter()`），所以集合上那个数与回放结果对得上（硬断言 (d)）。
3. **空条件当场拒**。修前 S8 那颗「新建」存的是 `query={}` —— 一条集合等于"全库"，
   点了回放只是重新显示全部文档：一个改变不了任何读数的入口（**ISSUES I11** 那一类）。

量级：`entries()` 每条集合一次 `count_matching`。集合是人手写的（几十条这个量级），
不是千级列表，所以这里不做缓存、也不做懒数 —— 真要那条，先有实测说 S8 打开慢过。

不做的事（线框 §I78-yi「不做什么」）：集合是**保存的查询**，不是物化视图 —— 每次点开现查，
没有定时刷新；也不做导出（那是 **ISSUES I78** 丙）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone

from pdfarchiver.db.repositories.collections import Collection, CollectionRepository
from pdfarchiver.db.repositories.documents import DocumentRepository
from pdfarchiver.search.service import Criteria

#: 「修改时间」那一条件在界面上的粒度是**日**（线框 §I78-yi 画的就是 `修改时间 ≥ 2026-01-01`），
#: 而 `DocFilter` 比的是 `mtime_ns`（UTC 秒 × 10⁹）。这两头之间必须有人决定"一天"是什么，
#: 所以决定只写在这两个函数里 —— 界面里各算一次就会一个按本地日、一个按 UTC 日。
_DAY_FORMAT = "%Y-%m-%d"


def day_start(text: str) -> int:
    """`YYYY-MM-DD` → 那一天的第一秒（UTC）。"""
    return int(datetime.strptime(text.strip(), _DAY_FORMAT).replace(
        tzinfo=timezone.utc).timestamp())


def day_end(text: str) -> int:
    """`YYYY-MM-DD` → 那一天的最后一秒（UTC，`23:59:59`）。

    不写成次日 00:00:00：那样 `≤ 3月31日` 会把 3月31日 当天几乎全部文件排除掉，
    而 `mtime_ns` 的比较是闭区间（`documents.where_for_filter` 用的是 `<=`）。
    """
    parsed = datetime.strptime(text.strip(), _DAY_FORMAT)
    return int(datetime.combine(parsed.date(), time.max, tzinfo=timezone.utc).timestamp())


@dataclass(frozen=True)
class CollectionEntry:
    """S8 右栏那一行的全部读数：身份、名字、原样那份条件、以及此刻的命中数。

    `query` 一起带出来是给"复制为新"与回放用的 —— 那一件事只需要源集合的条件，不需要重新数一遍。
    `usable` 是"这一条真的设了至少一条条件吗"：旧版 S8 那颗「新建」存的就是 `query={}`，
    库里可能留着这样的行，屏幕上不能替它假装它筛过什么（**ISSUES I11**）。判据与
    `_require_usable` 同一条，所以它只在 `entries()` 里算一次，界面上没有第二份"什么算空"。
    """

    id: int
    name: str
    query: dict
    hits: int
    usable: bool = True

    def label(self) -> str:
        """上屏那句。与 `LinkReceipt.describe()` 同一条纪律（**ISSUES I60**）：读数只有一个出口。"""
        if not self.usable:
            return f"{self.name} · 无筛选条件（回放等于看全库）"
        return f"{self.name} · 命中 {self.hits}"


class CollectionService:
    def __init__(self, collections: CollectionRepository,
                 documents: DocumentRepository) -> None:
        self.collections = collections
        self.documents = documents

    # ---- 读数 ----

    def count(self, query: dict) -> int:
        """这份条件现在能数出几份文档 —— 与回放那张表用的是同一个 WHERE。"""
        return self.documents.count_matching(self._browse(query).doc_filter())

    def entries(self) -> list[CollectionEntry]:
        """S8 右栏整列的读数：按名字序（仓储层 `list()` 已经是），每条带现数的命中。

        一份条件只 `from_query` 一次：数命中要它，判"这条筛没筛"也要它 —— 分成两次解析就会
        出现"数的时候认了、显示的时候不认"的窗口。
        """
        out: list[CollectionEntry] = []
        for coll in self.collections.list():
            criteria = Criteria.from_query(coll.query)
            out.append(CollectionEntry(
                id=coll.id, name=coll.name, query=coll.query,
                hits=self.documents.count_matching(criteria.browse_page().doc_filter()),
                usable=criteria != Criteria()))
        return out

    def query_of(self, collection_id: int) -> dict:
        return self.collections.get(collection_id).query

    # ---- 写 ----

    def save(self, name: str, query: dict, note: str | None = None) -> Collection:
        """把一组筛选条件存成一条新集合。"""
        self._require_usable(query)
        return self.collections.add(name, self._normalized(query), note=note)

    def overwrite(self, collection_id: int, query: dict) -> Collection:
        """用当前条件覆盖这条集合存的查询（**ISSUES I78** 乙：`update_query` 在产品里的调用点）。"""
        self._require_usable(query)
        return self.collections.update_query(collection_id, self._normalized(query))

    def copy_as_new(self, source_id: int, name: str) -> Collection:
        """把一条集合的条件原样复制成另一条（线框 §I78-yi S8 那排按钮里的「复制为新」）。

        走 `save` 而不是直接 `add`：库里可能留着旧版「新建」那种 `query={}` 的行，
        复制它等于再造一条"改了名字、一条读数都不改"的集合 —— 那条拒要在这里拒。
        """
        return self.save(name, self.query_of(source_id))

    def rename(self, collection_id: int, new_name: str) -> Collection:
        return self.collections.rename(collection_id, new_name)

    def delete(self, collection_id: int) -> None:
        """删掉这一条集合。**只删那一行查询**：文档与它们的分类/标签关联一条不动
        （SPEC 3.3.5；硬断言 (c) 钉的就是这件事）。"""
        self.collections.delete(collection_id)

    # ---- 内部：一份条件的两个问题 ----

    @staticmethod
    def _browse(query: dict) -> Criteria:
        """条件 dict → 浏览形状的条件（分页/排序/含缺失的口径全在 `Criteria.browse_page` 一处）。"""
        return Criteria.from_query(query).browse_page()

    @staticmethod
    def _normalized(query: dict) -> dict:
        """存进去的那份 dict 与 `Criteria.to_query()` 同形：键固定、tuple 落成 list。

        不规范化就会出现同一个条件两种写法（`[3]` 与 `(3,)`），`==` 回不来，
        而"集合存的条件"与"界面显示的条件"从此是两个东西。
        """
        return Criteria.from_query(query).to_query()

    @staticmethod
    def _require_usable(query: dict) -> None:
        criteria = Criteria.from_query(query)          # 认不出的键在这里当场拒
        if criteria == Criteria():
            raise ValueError("这条集合没有任何筛选条件 —— 先加上至少一条条件再存")
