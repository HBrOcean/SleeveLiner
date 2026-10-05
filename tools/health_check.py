# -*- coding: utf-8 -*-
"""
SleeveLiner 音源健康检测
=========================

一键探测各音源接口是否仍然可用，用于「持续检测」——音乐平台接口会不定期变动，
定期跑一次可及早发现某个源失效（例如历史出现过的酷狗默认占位封面、酷我限流）。

用法（在项目根目录执行）：
    python tools/health_check.py            # 跑内置样例歌曲
    python tools/health_check.py "歌手" "歌名" [更多...]   # 自定义歌曲

退出码：0 = 全部正常；1 = 有源异常（便于 CI / 批处理判断）。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import sleeve_liner as sl
except ImportError as e:
    print(f"[错误] 无法导入 sleeve_liner（{e}）")
    print("       请先安装依赖：pip install -r requirements.txt")
    sys.exit(2)

# 样例：覆盖 中文 / 英文 / 日语，检验多语言与多源
DEFAULT_CASES = [
    ("周杰伦", "晴天", 269),
    ("Adele", "Hello", 295),
    ("米津玄師", "Lemon", 256),
]

OK, BAD = "[ OK ]", "[FAIL]"


def _line(tag, name, detail):
    print(f"  {tag} {name:<26s} {detail}")


def check_kugou(artist, title, dur_s):
    """酷狗：搜索 + 封面（校验非默认占位图）+ 歌词"""
    res = {"搜索": False, "封面": False, "歌词": False}
    try:
        hits = sl.Kugou.search_song(artist, title)
        if hits:
            res["搜索"] = True
            _line(OK, "酷狗搜索", f"{hits[0].title} / {hits[0].artist}")
            # 封面：下载并确认不是通用占位图
            for h in hits:
                if h.cover_url:
                    try:
                        data, _ = sl.http_get(h.cover_url)
                        if data and len(data) >= 500 and not sl._is_default_cover(data):
                            res["封面"] = True
                            _line(OK, "酷狗封面", f"{len(data)} B  {h.cover_url[:60]}")
                            break
                    except Exception:  # noqa: BLE001
                        pass
            if not res["封面"]:
                _line(BAD, "酷狗封面", "候选均无可用封面或为默认占位图")
        else:
            _line(BAD, "酷狗搜索", "无结果")
    except Exception as e:  # noqa: BLE001
        _line(BAD, "酷狗搜索", f"异常 {type(e).__name__}: {e}")
    try:
        cands = sl.Kugou.search_lyric(artist, title, dur_s * 1000)
        if cands:
            lrc = sl.Kugou.download_lyric(cands[0]["id"], cands[0]["accesskey"])
            if lrc:
                res["歌词"] = True
                _line(OK, "酷狗歌词", f"{len(lrc)} 字符")
        if not res["歌词"]:
            _line(BAD, "酷狗歌词", "无可用歌词")
    except Exception as e:  # noqa: BLE001
        _line(BAD, "酷狗歌词", f"异常 {type(e).__name__}: {e}")
    return res


def check_netease(artist, title):
    """网易云：搜索 + detail（封面）+ 歌词"""
    res = {"搜索": False, "封面": False, "歌词": False}
    try:
        hits = sl.Netease.search_song(artist, title)
        if hits:
            res["搜索"] = True
            _line(OK, "网易云搜索", f"{hits[0].title} / {hits[0].artist}")
            sid = hits[0].extra.get("id")
            _y, _t, cover = sl.Netease.detail(sid)
            if cover:
                try:
                    data, _ = sl.http_get(cover)
                    res["封面"] = bool(data and len(data) >= 500)
                except Exception:  # noqa: BLE001
                    pass
            _line(OK if res["封面"] else BAD, "网易云封面",
                  f"{cover[:60]}" if cover else "无封面字段")
            lrc = sl.Netease.download_lyric(sid)
            if lrc:
                res["歌词"] = True
                _line(OK, "网易云歌词", f"{len(lrc)} 字符")
            else:
                _line(BAD, "网易云歌词", "无歌词")
        else:
            _line(BAD, "网易云搜索", "无结果")
    except Exception as e:  # noqa: BLE001
        _line(BAD, "网易云搜索", f"异常 {type(e).__name__}: {e}")
    return res


def check_lrclib(artist, title, dur_s):
    """LRCLIB：精确匹配 + 搜索（均为同步歌词）"""
    res = {"精确": False, "搜索": False}
    try:
        lrc = sl.Lrclib.get_exact(artist, title, dur_s * 1000)
        if lrc:
            res["精确"] = True
            _line(OK, "LRCLIB 精确", f"{len(lrc)} 字符（同步歌词）")
        else:
            _line(BAD, "LRCLIB 精确", "未命中（可能时长/标题不符）")
    except Exception as e:  # noqa: BLE001
        _line(BAD, "LRCLIB 精确", f"异常 {type(e).__name__}: {e}")
    try:
        cands = sl.Lrclib.search_lyric(artist, title)
        if cands:
            res["搜索"] = True
            _line(OK, "LRCLIB 搜索", f"{len(cands)} 条候选，首条 {len(cands[0]['lrc'])} 字符")
        else:
            _line(BAD, "LRCLIB 搜索", "无候选")
    except Exception as e:  # noqa: BLE001
        _line(BAD, "LRCLIB 搜索", f"异常 {type(e).__name__}: {e}")
    return res


def check_kuwo(artist, title):
    """酷我：搜索 + 歌词（该源易限流，连续请求或返回 301）"""
    res = {"搜索": False, "歌词": False}
    try:
        cands = sl.Kuwo.search_lyric(artist, title)
        if cands:
            res["搜索"] = True
            _line(OK, "酷我搜索", f"{cands[0]['title']} / {cands[0]['artist']}")
            lrc = sl.Kuwo.download_lyric(cands[0]["id"])
            if lrc:
                res["歌词"] = True
                _line(OK, "酷我歌词", f"{len(lrc)} 字符")
            else:
                _line(BAD, "酷我歌词", "无歌词（多为限流，可稍后重试）")
        else:
            _line(BAD, "酷我搜索", "无结果")
    except Exception as e:  # noqa: BLE001
        _line(BAD, "酷我搜索", f"异常 {type(e).__name__}: {e}")
    return res


def main():
    argv = sys.argv[1:]
    if argv and len(argv) % 2 == 0:
        cases = [(argv[i], argv[i + 1], 0) for i in range(0, len(argv), 2)]
    elif argv:
        print("参数需成对给出：歌手 歌名 歌手 歌名 ...")
        sys.exit(2)
    else:
        cases = DEFAULT_CASES

    print("=" * 68)
    print(f"SleeveLiner 音源健康检测  (v{sl.VERSION})")
    print("=" * 68)

    summary = {"kugou": 0, "netease": 0, "lrclib": 0, "kuwo": 0}
    total = len(cases)
    for artist, title, dur_s in cases:
        print(f"\n▶ {artist} - {title}" + (f"  ({dur_s}s)" if dur_s else ""))
        r1 = check_kugou(artist, title, dur_s or 0)
        r2 = check_netease(artist, title)
        r3 = check_lrclib(artist, title, dur_s or 0)
        r4 = check_kuwo(artist, title)
        summary["kugou"] += int(r1["搜索"] and r1["歌词"])
        summary["netease"] += int(r2["搜索"] and r2["歌词"])
        summary["lrclib"] += int(r3["精确"] or r3["搜索"])
        summary["kuwo"] += int(r4["搜索"] and r4["歌词"])
        time.sleep(0.5)   # 轻量限速，避免触发平台风控

    print("\n" + "=" * 68)
    print(f"汇总（{total} 首样例，'核心可用' = 搜索且有歌词）")
    print("=" * 68)
    for label, key in [("酷狗", "kugou"), ("网易云", "netease"),
                       ("LRCLIB", "lrclib"), ("酷我", "kuwo")]:
        n = summary[key]
        mark = "✅" if n == total else ("⚠️" if n > 0 else "❌")
        print(f"  {mark} {label:<8s} 核心可用 {n}/{total}")

    core_ok = (summary["kugou"] or summary["netease"]) == total
    print("\n结论：" + ("核心源（酷狗/网易云）工作正常 ✅"
                      if core_ok else "核心源存在异常，请检查上表 ❌"))
    print("提示：酷我易限流，偶发 301 属正常；多源互补可保证整体可用性。")
    sys.exit(0 if core_ok else 1)


if __name__ == "__main__":
    main()
