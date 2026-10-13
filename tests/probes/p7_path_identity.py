"""P7 路径与文件身份探针：SPEC 4.3 要求的路径规范化、大小写、重叠目录、长路径、跨盘唯一性。

这一层是整个索引正确性的地基：如果同一文件在不同监测根下产生两条主记录，
后续的分类、全文索引、归档、去重全部会错。必须在写库之前用真实文件系统验证。

验证项：
  I1 Windows 大小写不敏感 + 大小写不同写法 -> 必须解析成同一个身份
  I2 8.3 短路径、冗余分隔符、"." 与 ".." 段 -> 规范化后同一身份
  I3 >260 字符的中文长路径：普通 API vs \\?\ 前缀的真实行为（不许假设开了长路径就能用）
  I4 重叠监测根：同一文件被两个根覆盖 -> 只产生一条主记录（含 SQLite COLLATE NOCASE 唯一索引）
  I5 内容相同但路径不同 -> 哈希相同、主记录仍是两条（SPEC 3.7：不得擅自合并）
  I6 网络路径 / 卷不可达时不崩
  I7 同名不同内容 / 同路径被替换 -> 能通过 mtime+size+hash 判出变化

用法: python tests/probes/p7_path_identity.py
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import sqlite3
import sys
import time

import psutil
import pymupdf

pymupdf.TOOLS.mupdf_display_errors(False)

WORK = os.path.join(".probe_work", "p7_paths")
def norm(path: str) -> str:
    """项目规范化的唯一口径。

    必须走 realpath 而不是 normpath：P7 实测 Windows 的 8.3 短名会把空格直接吃掉
    （"报告 A.pdf" -> "报告A~1.PDF"），纯字符串规范化无法把短名和长名归一，
    而文件系统事件和 API 返回的写法不固定。realpath 同时解 8.3 名、符号链接与 junction。
    """
    p = os.path.realpath(path)
    p = os.path.normpath(p)
    p = p.replace("\\", "/")
    if len(p) > 1 and p.endswith("/"):
        p = p.rstrip("/")
    return p


def identity_key(path: str) -> str:
    """文件系统身份键。Windows 卷大小写不敏感 -> 用 casefold；不用 lower()（casefold 对 Unicode 更稳）。"""
    return norm(path).casefold()


def get_win_long_paths_enabled() -> dict:
    """读注册表看系统是否开启 LongPathsEnabled，不猜。"""
    out = {"queried": False, "LongPathsEnabled": None, "error": None}
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",  # LongPathsEnabled 实际在这里，不在 CurrentVersion
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as k:
            v, _ = winreg.QueryValueEx(k, "LongPathsEnabled")
            out["LongPathsEnabled"] = int(v)
        out["queried"] = True
    except OSError as exc:
        out["error"] = f"{type(exc).__name__}: {exc.winerror} {exc.strerror}"
    return out


def make_pdf(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    d = pymupdf.open()
    d.new_page().insert_text((72, 110), text[:60])
    d.save(path)
    d.close()


def trap_shortname(long_path: str) -> str | None:
    """用 GetShortPathNameW 拿 8.3 名，验证它是否指向同一文件。"""
    try:
        buf = ctypes.create_unicode_buffer(260)
        n = ctypes.windll.kernel32.GetShortPathNameW(long_path, buf, 260)
        return buf.value if n else None
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if os.path.exists(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    wv = sys.getwindowsversion()
    rep: dict = {"work": WORK, "os_win": {"major": wv.major, "build": wv.build, "platform": wv.platform}}
    rep["long_path_registry"] = get_win_long_paths_enabled()

    # --- I1 大小写 ---
    a = os.path.join(WORK, "CaseTest", "报告 A.pdf")
    make_pdf(a, "case identity")
    variants = [a, a.replace("CaseTest", "cAsEtEsT"), a.replace("报告 A.pdf", "REPORT~1.PDF" if False else "报告 a.pdf")]
    rep["case"] = {
        "variants": [v.replace(WORK, "") for v in variants],
        "all_exist_via_os": [os.path.exists(v) for v in variants],
        "identity_keys_unique": len({identity_key(v) for v in variants}),
        "raw_string_equal": len(set(norm(v) for v in variants)) == 1,
    }

    # --- I2 冗余段 / 分隔符 ---
    noisy = [
        a,
        os.path.join(WORK, "CaseTest", "..", "CaseTest", "报告 A.pdf"),
        os.path.join(WORK, "CaseTest", ".", "报告 A.pdf"),
        WORK.replace("\\", "/") + "//CaseTest//报告 A.pdf",
    ]
    rep["redundant_segments"] = {
        "distinct_identity_keys": len({identity_key(v) for v in noisy}),
        "all_exist": [os.path.exists(v) for v in noisy],
    }

    # --- I3 长路径 >260，中文 ---
    deep = WORK
    seg = "中文目录名"
    created_normal, created_ext, err_n, err_e = False, False, None, None
    p = deep
    for i in range(60):
        p = os.path.join(p, f"{seg}{i:02d}")
    longfile = os.path.join(p, "很深的目标文件.pdf")
    rel_len = len(longfile.replace(WORK, ""))
    rep["long_path"] = {"absolute_length": len(os.path.abspath(longfile)), "over_260": len(os.path.abspath(longfile)) > 260}
    try:
        os.makedirs(os.path.dirname(longfile), exist_ok=True)
        make_pdf(longfile, "deep")
        created_normal = os.path.exists(longfile)
    except OSError as exc:
        err_n = f"{type(exc).__name__}: {exc.winerror} {exc.strerror}"
    rep["long_path"]["plain_api_created"] = created_normal
    rep["long_path"]["plain_api_error"] = err_n
    ext = "\\\\?\\" + os.path.abspath(longfile).replace("/", "\\")
    try:
        if not created_normal:
            os.makedirs(os.path.dirname(ext), exist_ok=True)
            make_pdf(ext, "deep")
        created_ext = os.path.exists(ext)
    except OSError as exc:
        err_e = f"{type(exc).__name__}: {exc.winerror} {exc.strerror}"
    rep["long_path"]["extended_prefix_created"] = created_ext
    rep["long_path"]["extended_prefix_error"] = err_e
    if created_normal or created_ext:
        real = longfile if created_normal else ext
        try:
            st = os.stat(real)
            rep["long_path"]["stat_bytes"] = st.st_size
        except OSError as exc:
            rep["long_path"]["stat_error"] = str(exc)

    # --- I4 重叠监测根 + SQLite 唯一索引 ---
    rootA = os.path.join(WORK, "roots", "A")
    rootB = os.path.join(WORK, "roots", "A", "sub", "B_overlap")  # B 在 A 之内 -> 真重叠
    os.makedirs(rootB, exist_ok=True)
    shared = os.path.join(rootB, "重叠文件.pdf")
    make_pdf(shared, "overlapping roots")
    own_a, own_b = os.path.join(rootA, "只在A.pdf"), os.path.join(rootB, "只在B.pdf")
    make_pdf(own_a, "a only")
    make_pdf(own_b, "b only")

    db = os.path.join(WORK, "p7_identity.db")
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE documents(
          id INTEGER PRIMARY KEY,
          path TEXT NOT NULL,
          path_key TEXT NOT NULL COLLATE NOCASE UNIQUE,
          size INTEGER, mtime REAL, sha256 TEXT
        );
        """
    )

    def scan(root: str) -> int:
        inserted = 0
        for dp, _, fns in os.walk(root):
            for fn in fns:
                if not fn.lower().endswith(".pdf"):
                    continue
                fp = os.path.join(dp, fn)
                st = os.stat(fp)
                try:
                    conn.execute(
                        "INSERT INTO documents(path, path_key, size, mtime) VALUES(?,?,?,?)",
                        (norm(fp), identity_key(fp), st.st_size, st.st_mtime),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass  # 重叠根命中同一主记录
        conn.commit()
        return inserted

    ins_a, ins_b = scan(rootA), scan(rootB)
    rows = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    rep["overlapping_roots"] = {
        "rootB_inside_rootA": identity_key(rootB).startswith(identity_key(rootA)),
        "inserted_by_A": ins_a,
        "rejected_by_unique_index_from_B": ins_b,
        "main_records_total": rows,
        "expected_records": 3,
        "b_case_variant_rejected": None,
    }
    # 大小写变体再插一次，必须撞唯一索引
    try:
        conn.execute(
            "INSERT INTO documents(path, path_key, size, mtime) VALUES(?,?,?,?)",
            (norm(shared).upper(), identity_key(shared).upper(), 1, 0.0),
        )
        conn.commit()
        rep["overlapping_roots"]["b_case_variant_rejected"] = False
    except sqlite3.IntegrityError:
        conn.rollback()
        rep["overlapping_roots"]["b_case_variant_rejected"] = True

    # --- I5 同内容不同路径 -> 哈希相同但记录不同 ---
    dup1 = os.path.join(rootA, "dup_original.pdf")
    dup2 = os.path.join(WORK, "elsewhere", "dup_copy_renamed_differently.pdf")
    make_pdf(dup1, "duplicate content")
    os.makedirs(os.path.dirname(dup2), exist_ok=True)
    shutil.copy2(dup1, dup2)

    def sha(p: str) -> str:
        import hashlib

        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for blk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(blk)
        return h.hexdigest()

    # 同一秒内复制 -> mtime 相同，只有 hash 能判出同内容；这里证明 hash 一致且路径独立
    t0 = time.perf_counter()
    h1, h2 = sha(dup1), sha(dup2)
    hash_rate = round(os.path.getsize(dup1) / 1048576 / max(1e-6, time.perf_counter() - t0), 2)
    rep["same_content"] = {
        "hash_equal": h1 == h2,
        "paths_distinct": True,
        "identity_keys_distinct": identity_key(dup1) != identity_key(dup2),
        "tiny_file_hash_mb_per_s": hash_rate,
    }

    # --- I6 不可达路径 ---
    bogus = "Z:/ definitely/not/here/x.pdf"
    unc = "\\\\this-share-does-not-exist\\a.pdf"
    rep["unreachable"] = {
        "bogus_drive_exists": os.path.exists(bogus),
        "unc_exists": os.path.exists(unc),
        "stat_raises": None,
        "walk_returns_empty_not_crash": None,
    }
    try:
        os.stat(bogus)
        rep["unreachable"]["stat_raises"] = False
    except OSError:
        rep["unreachable"]["stat_raises"] = True
    try:
        rep["unreachable"]["walk_returns_empty_not_crash"] = list(os.walk(unc)) == []
    except Exception as exc:  # noqa: BLE001
        rep["unreachable"]["walk_error"] = f"{type(exc).__name__}: {exc}"

    # --- I7 同路径内容被替换 ---
    mutable = os.path.join(rootA, "will_change.pdf")
    make_pdf(mutable, "version one")
    st1 = os.stat(mutable)
    h_before = sha(mutable)
    time.sleep(0.05)
    make_pdf(mutable, "version two is different text")
    st2 = os.stat(mutable)
    h_after = sha(mutable)
    rep["content_changed_same_path"] = {
        "size_differs": st1.st_size != st2.st_size,
        "mtime_differs": st1.st_mtime != st2.st_mtime,
        "hash_differs": h_before != h_after,
        "mtime_only_would_have_caught_it": st1.st_mtime != st2.st_mtime,
    }

    # --- I7b NTFS 文件 ID：路径写法之外更硬的身份 ---
    try:
        s1, s2 = os.stat(a), os.stat(trap_shortname(os.path.abspath(a)) or a)
        rep["file_id"] = {
            "st_dev_ino_available": bool(s1.st_ino and s1.st_dev),
            "matches_through_short_name": (s1.st_dev, s1.st_ino) == (s2.st_dev, s2.st_ino),
        }
    except OSError as exc:
        rep["file_id"] = {"error": str(exc)}

    # --- I8 8.3 短名（如果卷启用了短名）---
    sn = trap_shortname(os.path.abspath(a))
    rep["short_name"] = {
        "obtained": sn,
        "resolves_to_same_file": bool(sn and os.path.exists(sn)),
        "identity_key_matches_long": bool(sn and identity_key(sn) == identity_key(a)),
    }
    conn.close()

    checks = [
        ("大小写不同的同一文件必须归一成一个身份键", rep["case"]["identity_keys_unique"] == 1),
        ("大小写变体都要能被 os 识别为存在", all(rep["case"]["all_exist_via_os"])),
        ("大小写变体经 realpath 归一后得到同一个规范展示路径（不是靠 lower() 糊的）", rep["case"]["raw_string_equal"] is True),
        ("冗余分隔符与 ./.. 段归一成一个身份", rep["redundant_segments"]["distinct_identity_keys"] == 1),
        ("重叠监测根只产生一条主记录", rep["overlapping_roots"]["main_records_total"] == rep["overlapping_roots"]["expected_records"]),
        ("B 根重复扫描被唯一索引拒绝（幂等）", rep["overlapping_roots"]["rejected_by_unique_index_from_B"] == 0),
        ("大小写变体再插入也被 COLLATE NOCASE 唯一索引拒绝", rep["overlapping_roots"]["b_case_variant_rejected"] is True),
        ("长路径 (>260) 的真实结果已被记录（成不成都要写清）", rep["long_path"]["over_260"] and "plain_api_created" in rep["long_path"]),
        ("系统是否开启长路径支持已从注册表实测读出（不靠假设）", rep["long_path_registry"]["queried"] is True),
        ("开启长路径后，深路径确实能用普通 API 建立并读取（决定要不要到处加 \\?\ 前缀）",
         rep["long_path"]["plain_api_created"] is True),
        ("同内容不同路径：哈希相同但保持两条独立记录（不许自动合并）",
         rep["same_content"]["hash_equal"] and rep["same_content"]["identity_keys_distinct"]),
        ("不可达路径返回 False 而不是抛异常", rep["unreachable"]["bogus_drive_exists"] is False and rep["unreachable"]["unc_exists"] is False),
        ("同路径被替换内容能被 hash 判出", rep["content_changed_same_path"]["hash_differs"]),
        ("8.3 短名若存在必须归一到同一身份（拿不到则视为卷未启用，不算失败）",
         rep["short_name"]["obtained"] is None or rep["short_name"]["identity_key_matches_long"]),
        ("NTFS 文件 ID 可用且能跨短名/长名匹配（路径写法之外的硬身份）",
         rep["file_id"].get("st_dev_ino_available") is True and rep["file_id"].get("matches_through_short_name") is True),
    ]
    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print("  INFO long_path: " + json.dumps(rep["long_path"], ensure_ascii=False))
    print("  INFO registry: " + json.dumps(rep["long_path_registry"], ensure_ascii=False))
    print("  INFO overlap: " + json.dumps(rep["overlapping_roots"], ensure_ascii=False))
    print("  INFO short_name: " + json.dumps(rep["short_name"], ensure_ascii=False))
    print("  INFO unreachable: " + json.dumps(rep["unreachable"], ensure_ascii=False))
    with open(".probe_work/p7_path_identity_result.json", "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    print("VERDICT: " + ("ALL GREEN" if all(ok for _, ok in checks) else "RED"))
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
