#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SleeveLiner (sleeve_liner.py) v2.3 —— 联网补齐音频文件的封面与歌词
（v2.1 修复：封面改走酷狗 trans_param.union_cover 真实封面，旧版
  imgessl/{hash}.jpg 返回的是通用默认图；并自动识别文件中已嵌入的默认图）
（v2.2：原始文件保持不动，处理结果（音频副本 + .lrc）统一输出到
  各输入根目录下的 output/ 文件夹，可用 --outdir 改输出文件夹名）
（v2.3：宽松二次匹配（歌名+时长硬约束、歌手加分）+ 纯歌名重搜；
  补年份/音轨号；歌词增加酷我第三源；.lrc 编码可选(GBK)；封面缓存；
  并发进度与汇总报告；中断保存缓存；多歌手分隔符规范化；SSL/请求头优化）

支持格式：MP3 / FLAC / M4A / OPUS / OGG
支持平台：酷狗（主源，真实封面 + 歌词）+ 网易云（高清封面、年份/音轨）+ 酷我（歌词兜底）

功能：
  1. 认出歌曲身份：已有标签 > 文件名（支持「歌手 - 歌名」「歌名 - 歌手」双向）
  2. 多源联网搜索，交叉印证（两源都命中同一首 = 高置信度）
  3. 下载封面并内嵌（自动选更清晰的一张）
  4. 搜索歌词并内嵌 + 输出同名 .lrc（自动清洗酷狗私有标签行）
  5. 顺带补全标题/歌手/专辑；可选把文件名规范成「歌名 - 歌手」
  6. 多文件并发处理 + 本地缓存（降低请求量与限流风险）
  7. 防错配三重校验：歌名 + 歌手 + 时长（简繁/别名自动归一）

用法示例：
  python sleeve_liner.py 周杰伦-晴天.mp3
  python sleeve_liner.py "音乐文件夹/" -r                 # 递归处理目录
  python sleeve_liner.py 无名.flac --artist 陈奕迅 --title 十年
  python sleeve_liner.py x.mp3 --rename                   # 顺便把文件名改成「歌名 - 歌手」
  python sleeve_liner.py "音乐/" -r --jobs 6              # 6 线程并发
  python sleeve_liner.py x.mp3 --dry-run                  # 只预览，不写入
  python sleeve_liner.py x.mp3 --no-cover / --no-lyric    # 只做其中一项
  python sleeve_liner.py x.mp3 --tol 8                    # 时长容差 8 秒
  python sleeve_liner.py x.mp3 --force                    # 已有封面/歌词也覆盖
"""

import argparse
import ast
import base64
import hashlib
import html
import json
import os
import re
import shutil
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import mutagen
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TRCK, USLT
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggopus import OggOpus
    from mutagen.oggvorbis import OggVorbis
except ImportError:
    sys.exit("[错误] 缺少 mutagen 库，请先安装：pip install mutagen")

try:
    import zhconv                      # 简繁转换（可选依赖）
    _HAS_ZHCONV = True
except ImportError:
    _HAS_ZHCONV = False

VERSION = "2.3"

# ---------------------------------------------------------------------------
# 常量 / HTTP（SSL 精细化：仅音乐平台域名关闭证书校验）
# ---------------------------------------------------------------------------

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

AUDIO_EXTS = (".mp3", ".flac", ".m4a", ".opus", ".ogg", ".oga", ".aac")

# 酷狗封面：真正的封面在 trans_param.union_cover（含 {size} 占位符），
# 而 imgessl/stdmusic/{hash}.jpg 返回的是一张通用默认占位图（黑胶图标），不可用
COVER_SIZE = 800
# 酷狗默认占位图的 md5，用于识别"假封面"（既避免下载它，也能识别文件中已嵌入的）
_DEFAULT_COVER_MD5 = "7d79006af51cdd1fe1aca16482a2ef3e"

# 这些平台的 CDN 证书链不完整，需关闭校验；其他域名保持严格校验
MUSIC_HOSTS = ("kugou.com", "music.163.com", "163.com", "126.net")

# 网易云请求头（带 Referer 更规范，提升接口稳定性）
_NETEASE_HEADERS = {"Referer": "https://music.163.com/"}
# 封面本地缓存目录（避免同一首歌重复下载）
_COVER_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".sleeveliner_cover_cache")

_CTX_UNVERIFIED = ssl.create_default_context()
_CTX_UNVERIFIED.check_hostname = False
_CTX_UNVERIFIED.verify_mode = ssl.CERT_NONE
_CTX_VERIFIED = ssl.create_default_context()


def _ctx_for(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in MUSIC_HOSTS):
        return _CTX_UNVERIFIED
    return _CTX_VERIFIED


def http_get(url, timeout=12, headers=None):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx_for(url)) as r:
        return r.read(), r.headers.get("Content-Type", "")


def http_get_json(url, timeout=12, headers=None):
    data, _ = http_get(url, timeout, headers)
    return json.loads(data.decode("utf-8", "replace"))


def retry(fn, times=2):
    last = None
    for _ in range(times):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


# ---------------------------------------------------------------------------
# 文本归一化：简繁统一 + 别名归一 + 版本噪声剥离
# ---------------------------------------------------------------------------

def norm(s):
    """基础归一：小写、去空白与标点"""
    if not s:
        return ""
    s = s.lower()
    return re.sub(r"[\s，。！？、（）()【】\[\]《》\"'“”‘’\-—_—·.…,.:：;；/\\|!?~～&＆+＊*@#%^]", "", s)


def to_simplified(s):
    """繁体 → 简体（zhconv 不可用时用内置小表兜底）"""
    if not s:
        return ""
    if _HAS_ZHCONV:
        return zhconv.convert(s, "zh-cn")
    return s


def norm_key(s):
    return norm(to_simplified(s))


# 常见歌手别名（键为归一化后的写法）→ 规范写法（同为归一化）
_ALIAS = {
    "gem": "邓紫棋", "gem邓紫棋": "邓紫棋", "邓紫棋": "邓紫棋",
    "jaychou": "周杰伦", "周杰伦": "周杰伦",
    "easonchan": "陈奕迅", "陈奕迅": "陈奕迅",
    "jolin": "蔡依林", "jolintsai": "蔡依林", "蔡依林": "蔡依林",
    "jjlin": "林俊杰", "林俊杰": "林俊杰",
    "mayday": "五月天", "五月天": "五月天",
    "taylorswift": "taylorswift", "taylor": "taylorswift",
    "edsheeran": "edsheeran", "brunomars": "brunomars",
    "adele": "adele", "justinbieber": "justinbieber",
    "jay": "周杰伦",            # 单独 "jay" 常指周杰伦（风险低，歌名仍要匹配）
    "jj": "林俊杰",
}

# 版本噪声词（去括号后仍残留的，用于歌名主体比对）
_NOISE_RE = re.compile(
    r"(live|现场|演唱会|伴奏|纯音乐|钢琴版?|吉他版?|和声|童声|铃声|抖音|慢速|加速|"
    r"原唱|cover|翻唱|翻自|feat\.?|ft\.?|remix|混音|dj版?|重制|remaster(ed)?|修复版?|"
    r"hq|无损|320k|flac|高音质|高清|完整版|新版|旧版|正式版|纯享|重唱|试听|片段|剪辑|"
    r"demo|acoustic|instrumental|karaoke|off\s*vocal)", re.I)


def canonical(s):
    """歌手规范名：简繁统一 + 别名归一"""
    k = norm_key(s)
    return _ALIAS.get(k, k)


def normalize_artist(a):
    """多歌手分隔符规范化：酷狗常用 _ 连接多歌手（如 隔壁老樊_樊凯杰）"""
    if not a:
        return a
    a = a.replace("_", " / ")
    a = re.sub(r"\s*/\s*", " / ", a)
    return a.strip()


def core_norm(s):
    """歌名主体：去括注 + 去版本噪声词 + 归一"""
    if not s:
        return ""
    s = re.sub(r"[（(【\[].*?[)）】\]]", "", s)   # 去括注内容
    s = _NOISE_RE.sub("", s)                     # 去残余噪声词
    return norm_key(s)


def names_ok(a, b):
    """匹配：规范名相等，或主体互为包含（短者长度>=2）"""
    if not a or not b:
        return False
    if canonical(a) == canonical(b):
        return True
    ka, kb = core_norm(a), core_norm(b)
    if ka and kb:
        if ka == kb:
            return True
        short, long_ = sorted((ka, kb), key=len)
        if len(short) >= 2 and short in long_:
            return True
    return False


# ---------------------------------------------------------------------------
# 候选数据结构
# ---------------------------------------------------------------------------

class Hit:
    def __init__(self, source, artist, title, duration_ms, album="",
                 cover_url="", extra=None):
        self.source = source
        self.artist = artist or ""
        self.title = title or ""
        self.duration_ms = int(duration_ms or 0)
        self.album = album or ""
        self.cover_url = cover_url or ""
        self.extra = extra or {}
        self.multi_source = False
        self.year = ""        # 发行年份（后补）
        self.track = ""       # 音轨号（后补）

    def to_dict(self):
        return {"source": self.source, "artist": self.artist,
                "title": self.title, "duration_ms": self.duration_ms,
                "album": self.album, "cover_url": self.cover_url,
                "extra": self.extra}

    @staticmethod
    def from_dict(d):
        return Hit(d.get("source", ""), d.get("artist", ""), d.get("title", ""),
                   d.get("duration_ms", 0), d.get("album", ""),
                   d.get("cover_url", ""), d.get("extra") or {})


def pick_best(hits, artist, title, dur_ms, tol_ms, strict_singer=True):
    """从候选中挑选最佳匹配；校验不通过返回 None"""
    if not hits:
        return None, "无搜索结果"
    best = None
    tol_ms = max(int(tol_ms), 1000)
    for h in hits:
        if not names_ok(h.title, title):
            continue
        d = abs(h.duration_ms - dur_ms)
        if h.duration_ms and dur_ms and d > tol_ms:
            continue
        if strict_singer and artist and not names_ok(h.artist, artist):
            continue
        score = 0
        if norm_key(h.title) == norm_key(title):
            score += 4
        if artist and norm_key(h.artist) == norm_key(artist):
            score += 4
        score -= d / 1000.0
        if best is None or score > best[0]:
            best = (score, h)
    if best is None:
        return None, "无通过校验的候选（歌名/歌手/时长不符）"
    return best[1], f"歌名匹配 | 时长差 {abs(best[1].duration_ms-dur_ms)/1000:.1f}s"


# ---------------------------------------------------------------------------
# 身份解析（命令行 > 标签 > 文件名，支持双向）
# ---------------------------------------------------------------------------

def _clean_stem(stem):
    stem = stem.strip()
    # 去掉常见的站点/音质后缀
    stem = re.sub(r"[-_\s]*(\[.*?\]|【.*?】|\(.*?\)|（.*?）)$", "", stem).strip()
    stem = re.sub(r"[-_\s]*(HQ|无损|320K|FLAC|高音质)$", "", stem, flags=re.I).strip()
    return stem


def parse_from_filename(path):
    """从文件名拆 (artist, title)，拆不出返回 None"""
    stem = _clean_stem(os.path.splitext(os.path.basename(path))[0])
    for sep in (" - ", " – ", " — ", "-", "–", "—", "_"):
        if sep in stem:
            parts = [p.strip() for p in stem.split(sep)]
            if len(parts) == 2 and parts[0] and parts[1]:
                return parts[0], parts[1]
    return None


def parse_identity(path, cli_artist, cli_title, existing):
    if cli_artist or cli_title:
        return (cli_artist or "").strip(), (cli_title or "").strip()
    if existing and (existing[0] or existing[1]):
        return existing[0].strip(), existing[1].strip()
    parts = parse_from_filename(path)
    if parts:
        return parts[0], parts[1]
    return "", _clean_stem(os.path.splitext(os.path.basename(path))[0])


# ---------------------------------------------------------------------------
# 酷狗接口
# ---------------------------------------------------------------------------

class Kugou:
    SEARCH = ("https://ioscdn.kugou.com/api/v3/search/song?format=json"
              "&keyword={kw}&page=1&pagesize=10&showtype=1")
    # 注：旧版用的 imgessl/stdmusic/{hash}.jpg 返回的是通用默认图，已弃用；
    #     真封面改用搜索结果里的 trans_param.union_cover（见 search_song）
    LYRIC_SEARCH = ("https://lyrics.kugou.com/search?ver=1&man=yes&client=pc"
                    "&keyword={kw}&duration={dur}")
    LYRIC_DOWN = ("https://lyrics.kugou.com/download?ver=1&client=pc"
                  "&id={id}&accesskey={key}&fmt=lrc&charset=utf8")

    @staticmethod
    def search_song(artist, title):
        kw = urllib.parse.quote(f"{artist} {title}".strip())
        data = retry(lambda: http_get_json(Kugou.SEARCH.format(kw=kw)))
        hits = []
        for s in data.get("data", {}).get("info", []):
            if not s.get("songname"):
                continue
            dur_ms = int(s.get("duration") or 0) * 1000     # ioscdn 单位是秒
            # 真封面在 trans_param.union_cover；替换 {size} 取高清
            uc = (s.get("trans_param") or {}).get("union_cover", "") or ""
            cover = (uc.replace("{size}", str(COVER_SIZE)).replace("http://", "https://")
                     if uc else "")
            hits.append(Hit("酷狗", s.get("singername", ""), s.get("songname", ""),
                            dur_ms, s.get("album_name", ""), cover))
        return hits

    @staticmethod
    def search_lyric(artist, title, dur_ms):
        kw = urllib.parse.quote(f"{artist}-{title}")
        data = retry(lambda: http_get_json(
            Kugou.LYRIC_SEARCH.format(kw=kw, dur=dur_ms)))
        out = []
        for c in data.get("candidates", []) or []:
            out.append({"id": c.get("id") or c.get("download_id") or "",
                        "accesskey": c.get("accesskey", ""),
                        "artist": c.get("singer", ""),
                        "title": c.get("song", ""),
                        "duration_ms": int(c.get("duration") or 0)})
        return out

    @staticmethod
    def download_lyric(lid, accesskey):
        if not lid or not accesskey:
            return None
        data = retry(lambda: http_get_json(
            Kugou.LYRIC_DOWN.format(id=lid, key=urllib.parse.quote(accesskey))))
        content = data.get("content") or ""
        if not content:
            return None
        return base64.b64decode(content).decode("utf-8-sig", "replace").strip()


# ---------------------------------------------------------------------------
# 网易云接口
# ---------------------------------------------------------------------------

class Netease:
    SEARCH = ("https://music.163.com/api/search/get/web?csrf_token=&type=1"
              "&s={kw}&offset=0&total=true&limit=20")
    DETAIL = "https://music.163.com/api/song/detail?ids=[{sid}]"
    LYRIC = "https://music.163.com/api/song/lyric?id={sid}&lv=1&kv=1&tv=-1"

    @staticmethod
    def search_song(artist, title):
        kw = urllib.parse.quote(f"{artist} {title}".strip())
        data = retry(lambda: http_get_json(Netease.SEARCH.format(kw=kw),
                                           headers=_NETEASE_HEADERS))
        hits = []
        for s in (data.get("result") or {}).get("songs", []) or []:
            ar = "/".join(a.get("name", "") for a in s.get("artists", []) or [])
            hits.append(Hit("网易云", ar, s.get("name", ""),
                            int(s.get("duration") or 0),
                            (s.get("album") or {}).get("name", ""),
                            extra={"id": s.get("id")}))
        return hits

    @staticmethod
    def detail(sid):
        """取歌曲详情 -> (year, track, cover_url)"""
        if not sid:
            return "", "", ""
        data = retry(lambda: http_get_json(Netease.DETAIL.format(sid=sid),
                                           headers=_NETEASE_HEADERS))
        songs = data.get("songs") or []
        if not songs:
            return "", "", ""
        s = songs[0]
        al = s.get("album") or {}
        year = ""
        pt = al.get("publishTime") or s.get("publishTime")
        if pt:
            try:
                year = str(time.localtime(pt / 1000).tm_year)
            except Exception:  # noqa: BLE001
                year = ""
        track = str(s.get("no") or "")
        pic = al.get("picUrl") or ""
        cover = (pic.split("?")[0] + "?param=800y800") if pic else ""
        return year, track, cover

    @staticmethod
    def cover_url(sid):
        return Netease.detail(sid)[2]

    @staticmethod
    def download_lyric(sid):
        if not sid:
            return None
        data = retry(lambda: http_get_json(Netease.LYRIC.format(sid=sid),
                                           headers=_NETEASE_HEADERS))
        lrc = ((data.get("lrc") or {}).get("lyric") or "").strip()
        return lrc or None


# ---------------------------------------------------------------------------
# 酷我（第三源，仅歌词兜底；实测无封面、搜索较杂，故仅作歌词备选）
# ---------------------------------------------------------------------------

class Kuwo:
    SEARCH = ("http://search.kuwo.cn/r.s?all={kw}&ft=music&itemset=web_2013"
              "&client=kt&pn=0&rn=10&rformat=json&encoding=utf8")
    LYRIC = "https://m.kuwo.cn/newh5/singles/songinfoandlrc?musicId={mid}"

    @staticmethod
    def search_lyric(artist, title):
        """返回 [{id, artist, title, duration_ms}]（酷我结果较杂，需上层严格校验）"""
        kw = urllib.parse.quote(f"{artist} {title}")
        raw, _ = retry(lambda: http_get(Kuwo.SEARCH.format(kw=kw)))
        text = raw.decode("utf-8", "replace")
        try:
            data = ast.literal_eval(text)      # 酷我老接口返回 Python 字面量
        except Exception:  # noqa: BLE001
            return []
        out = []
        for m in data.get("abslist", []) or []:
            name = html.unescape(str(m.get("SONGNAME", ""))).replace("&nbsp;", " ").strip()
            art = html.unescape(str(m.get("ARTIST", ""))).replace("&nbsp;", " ").strip()
            rid = str(m.get("MUSICRID", "")).replace("MUSIC_", "")
            dur = int(m.get("DURATION") or 0) * 1000
            if name and rid:
                out.append({"id": rid, "artist": art, "title": name,
                            "duration_ms": dur})
        return out

    @staticmethod
    def download_lyric(rid):
        if not rid:
            return None
        data = retry(lambda: http_get_json(
            Kuwo.LYRIC.format(mid=rid),
            headers={"Referer": "https://m.kuwo.cn/"}))
        lrclist = (data.get("data") or {}).get("lrclist") or []
        if not lrclist:
            return None
        lines = []
        for x in lrclist:
            try:
                t = float(x.get("time") or 0)
            except Exception:  # noqa: BLE001
                continue
            mm = int(t // 60)
            ss = t - mm * 60
            lines.append(f"[{mm:02d}:{ss:05.2f}]{x.get('lineLyric', '')}")
        return "\n".join(lines) if lines else None


# ---------------------------------------------------------------------------
# 本地缓存（进程内 dict + 线程锁 + JSON 落盘）
# ---------------------------------------------------------------------------

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           ".sleeveliner_cache.json")
_CACHE_TTL = 7 * 24 * 3600


def cache_load():
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            _CACHE.update(json.load(f))
    except Exception:  # noqa: BLE001
        pass


def cache_save(enabled):
    if not enabled:
        return
    with _CACHE_LOCK:
        data = dict(_CACHE)
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def cache_get(key, enabled):
    if not enabled:
        return None
    with _CACHE_LOCK:
        e = _CACHE.get(key)
    if e and time.time() - e.get("ts", 0) < _CACHE_TTL:
        return e.get("hits")
    return None


def cache_put(key, hits, enabled):
    if not enabled:
        return
    with _CACHE_LOCK:
        _CACHE[key] = {"ts": time.time(), "hits": hits}


def search_song(source, artist, title, enabled):
    """带缓存的歌曲搜索，返回 [Hit]"""
    key = f"v{VERSION}|{source}|{artist}|{title}"
    cached = cache_get(key, enabled)
    if cached is not None:
        return [Hit.from_dict(h) for h in cached]
    hits = (Kugou.search_song(artist, title) if source == "kugou"
            else Netease.search_song(artist, title))
    cache_put(key, [h.to_dict() for h in hits], enabled)
    return hits


# ---------------------------------------------------------------------------
# 封面 / 歌词清洗 / 语言检测
# ---------------------------------------------------------------------------

def detect_mime(head):
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _is_default_cover(data):
    """是否为酷狗通用默认占位图"""
    return bool(data) and hashlib.md5(data).hexdigest() == _DEFAULT_COVER_MD5


def _cover_cache_file(url):
    return os.path.join(_COVER_CACHE_DIR,
                        hashlib.md5(url.encode("utf-8")).hexdigest() + ".img")


def _try_cover(url, use_cache=True):
    """下载单张封面并校验（非过小、非默认图），成功返回 (bytes, mime)"""
    if not url:
        return None
    # 先查本地封面缓存
    if use_cache:
        try:
            cf = _cover_cache_file(url)
            if os.path.exists(cf):
                with open(cf, "rb") as f:
                    data = f.read()
                if len(data) >= 500 and not _is_default_cover(data):
                    return data, detect_mime(data[:12])
        except Exception:  # noqa: BLE001
            pass
    try:
        data, _ = retry(lambda: http_get(url))
    except Exception:  # noqa: BLE001
        return None
    if len(data) < 500 or _is_default_cover(data):
        return None
    if use_cache:
        try:
            os.makedirs(_COVER_CACHE_DIR, exist_ok=True)
            with open(_cover_cache_file(url), "wb") as f:
                f.write(data)
        except Exception:  # noqa: BLE001
            pass
    return data, detect_mime(data[:12])


def fetch_cover(hit, use_cache=True):
    """多级获取封面：候选自带URL(取清晰者) → 网易云跨源兜底。返回 (bytes, mime)"""
    # 1) 候选自带封面（酷狗 union_cover）：800 与 400 都取，选字节数更大（更清晰）的
    if hit.cover_url:
        urls = [hit.cover_url]
        alt = hit.cover_url.replace(f"/{COVER_SIZE}/", "/400/")
        if alt != hit.cover_url:
            urls.append(alt)
        best = None
        for u in urls:
            img = _try_cover(u, use_cache)
            if img and (best is None or len(img[0]) > len(best[0])):
                best = img
        if best:
            return best

    # 2) 跨源兜底：用歌名+歌手查网易云拿高清封面
    sid = hit.extra.get("id") if hit.source.startswith("网易云") else None
    if not sid:
        try:
            nhits = Netease.search_song(hit.artist, hit.title)
            best_hit, _ = pick_best(nhits, hit.artist, hit.title, hit.duration_ms,
                                    30000, strict_singer=False)
            sid = best_hit.extra.get("id") if best_hit else None
        except Exception:  # noqa: BLE001
            sid = None
    if sid:
        try:
            img = _try_cover(Netease.cover_url(sid), use_cache)
            if img:
                return img
        except Exception:  # noqa: BLE001
            pass
    return None


def fetch_extra_meta(hit, artist, title, dur_ms, tol_ms, use_cache):
    """补齐年份/音轨号（来自网易云 detail）。找不到返回 ('', '')
    注意：跨源查网易云时要求歌手/专辑匹配，避免拿到翻唱版或合辑的信息。"""
    sid = hit.extra.get("id") if hit.source.startswith("网易云") else None
    if not sid:
        try:
            nhits = search_song("netease", hit.artist or artist,
                                hit.title or title, use_cache)
        except Exception:  # noqa: BLE001
            nhits = []
        # 优先级1：专辑名 + 歌名 + 歌手都一致（最可能是同一专辑版本）
        if hit.album:
            for h in nhits:
                if (h.extra.get("id") and names_ok(h.title, hit.title or title)
                        and names_ok(h.album, hit.album)
                        and names_ok(h.artist, hit.artist or artist)):
                    sid = h.extra["id"]
                    break
        # 优先级2：严格匹配（歌名 + 歌手 + 时长）
        if not sid and nhits:
            best_hit, _ = pick_best(nhits, hit.artist or artist,
                                    hit.title or title, dur_ms, tol_ms,
                                    strict_singer=True)
            sid = best_hit.extra.get("id") if best_hit else None
    if not sid:
        return "", ""
    try:
        y, t, _ = Netease.detail(sid)
        return y, t
    except Exception:  # noqa: BLE001
        return "", ""


_LRC_PRIVATE = re.compile(r"^\s*\[(id|hash|sign|qq|by|total):", re.I)


def clean_lrc(text):
    """清洗歌词：去掉酷狗私有标签行（保留 [ar:][ti:][al:][offset:] 与时间行）"""
    if not text:
        return text
    lines = [ln for ln in text.splitlines() if not _LRC_PRIVATE.match(ln)]
    return "\n".join(lines).strip()


def detect_lang(text):
    if re.search(r"[\u3040-\u30ff]", text):
        return "jpn"
    if re.search(r"[\uac00-\ud7af]", text):
        return "kor"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "chi"
    return "und"


# ---------------------------------------------------------------------------
# 读写标签（按文件类型分派）
# ---------------------------------------------------------------------------

def file_duration_ms(path):
    a = mutagen.File(path)
    return int(a.info.length * 1000) if a and a.info else 0


def _existing_cover_data(a, t):
    """取出文件中已嵌入封面的原始字节；无则 None"""
    try:
        if isinstance(a, MP3):
            apics = t.getall("APIC") if t else []
            return apics[0].data if apics else None
        if isinstance(a, FLAC):
            return a.pictures[0].data if a.pictures else None
        if isinstance(a, MP4):
            cov = t.get("covr") if t else None
            return bytes(cov[0]) if cov else None
        if isinstance(a, (OggVorbis, OggOpus)):
            mb = t.get("metadata_block_picture") if t else None
            return Picture(base64.b64decode(mb[0])).data if mb else None
    except Exception:  # noqa: BLE001
        return None
    return None


def read_existing(path):
    """返回 (artist, title, has_cover, has_lyric)"""
    artist = title = ""
    has_cover = has_lyric = False
    try:
        a = mutagen.File(path)
    except Exception:  # noqa: BLE001
        return artist, title, has_cover, has_lyric
    if a is None:
        return artist, title, has_cover, has_lyric
    t = a.tags
    try:
        if isinstance(a, MP3):
            if t is not None:
                artist = str(t["TPE1"].text[0]) if "TPE1" in t and t["TPE1"].text else ""
                title = str(t["TIT2"].text[0]) if "TIT2" in t and t["TIT2"].text else ""
                has_cover = bool(t.getall("APIC"))
                has_lyric = bool(t.getall("USLT"))
        elif isinstance(a, FLAC):
            if t:
                artist = str(t.get("artist", [""])[0])
                title = str(t.get("title", [""])[0])
                has_lyric = bool(t.get("LYRICS") or t.get("UNSYNCEDLYRICS"))
            has_cover = bool(a.pictures)
        elif isinstance(a, MP4):
            if t:
                artist = (t.get("\u00a9ART", [""]) or [""])[0]
                title = (t.get("\u00a9nam", [""]) or [""])[0]
                has_cover = "covr" in t
                has_lyric = "\u00a9lyr" in t
        elif isinstance(a, (OggVorbis, OggOpus)):
            if t:
                artist = str(t.get("artist", [""])[0])
                title = str(t.get("title", [""])[0])
                has_cover = "metadata_block_picture" in t
                has_lyric = bool(t.get("LYRICS") or t.get("UNSYNCEDLYRICS"))
    except Exception:  # noqa: BLE001
        pass
    # 已嵌入的若是酷狗默认占位图（旧版遗留），视为无封面，以便自动替换
    if has_cover and _is_default_cover(_existing_cover_data(a, t)):
        has_cover = False
    return artist.strip(), title.strip(), has_cover, has_lyric


def file_missing_meta(path):
    """返回 (缺年份, 缺音轨号)"""
    try:
        a = mutagen.File(path)
        t = a.tags if a else None
    except Exception:  # noqa: BLE001
        return True, True
    if a is None or t is None:
        return True, True
    try:
        if isinstance(a, MP3):
            return ("TDRC" not in t and "TYER" not in t, "TRCK" not in t)
        if isinstance(a, (FLAC, OggVorbis, OggOpus)):
            return (not t.get("date"), not t.get("tracknumber"))
        if isinstance(a, MP4):
            return ("\u00a9day" not in t, "trkn" not in t)
    except Exception:  # noqa: BLE001
        pass
    return True, True


def write_tags(path, hit, cover, lyric, do_cover, do_lyric):
    a = mutagen.File(path)
    if isinstance(a, MP3):
        return _write_mp3(path, hit, cover, lyric, do_cover, do_lyric)
    if isinstance(a, FLAC):
        return _write_flac(path, hit, cover, lyric, do_cover, do_lyric)
    if isinstance(a, MP4):
        return _write_mp4(path, hit, cover, lyric, do_cover, do_lyric)
    if isinstance(a, (OggVorbis, OggOpus)):
        return _write_ogg(path, a, hit, cover, lyric, do_cover, do_lyric)
    raise ValueError(f"不支持的音频类型: {type(a).__name__}")


def _write_mp3(path, hit, cover, lyric, do_cover, do_lyric):
    try:
        tags = ID3(path)
    except Exception:  # noqa: BLE001
        tags = ID3()
    changed = False
    if do_cover and cover:
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime=cover[1], type=3, desc="cover", data=cover[0]))
        changed = True
    if do_lyric and lyric:
        tags.delall("USLT")
        tags.add(USLT(encoding=3, lang=detect_lang(lyric), desc="lrc",
                      text=lyric))
        changed = True
    if hit:
        if hit.title and "TIT2" not in tags:
            tags.add(TIT2(encoding=3, text=[hit.title])); changed = True
        if hit.artist and "TPE1" not in tags:
            tags.add(TPE1(encoding=3, text=[normalize_artist(hit.artist)])); changed = True
        if hit.album and "TALB" not in tags:
            tags.add(TALB(encoding=3, text=[hit.album])); changed = True
        if hit.year and "TDRC" not in tags:
            tags.add(TDRC(encoding=3, text=[hit.year])); changed = True
        if hit.track and "TRCK" not in tags:
            tags.add(TRCK(encoding=3, text=[hit.track])); changed = True
    if changed:
        tags.save(path, v2_version=4)
    return changed


def _write_flac(path, hit, cover, lyric, do_cover, do_lyric):
    fl = FLAC(path)
    if fl.tags is None:
        fl.add_vorbiscomment()
    changed = False
    if do_cover and cover:
        pic = Picture()
        pic.type = 3
        pic.mime = cover[1]
        pic.desc = "cover"
        pic.data = cover[0]
        fl.clear_pictures()
        fl.add_picture(pic)
        changed = True
    if do_lyric and lyric:
        fl["LYRICS"] = [lyric]
        fl["UNSYNCEDLYRICS"] = [lyric]     # 双写，兼容更多播放器
        changed = True
    if hit:
        if hit.title and not fl.tags.get("title"):
            fl["title"] = [hit.title]; changed = True
        if hit.artist and not fl.tags.get("artist"):
            fl["artist"] = [normalize_artist(hit.artist)]; changed = True
        if hit.album and not fl.tags.get("album"):
            fl["album"] = [hit.album]; changed = True
        if hit.year and not fl.tags.get("date"):
            fl["date"] = [hit.year]; changed = True
        if hit.track and not fl.tags.get("tracknumber"):
            fl["tracknumber"] = [hit.track]; changed = True
    if changed:
        fl.save()
    return changed


def _write_mp4(path, hit, cover, lyric, do_cover, do_lyric):
    m = MP4(path)
    if m.tags is None:
        try:
            m.add_tags()
        except Exception:  # noqa: BLE001
            pass
    changed = False
    if do_cover and cover:
        fmt = (MP4Cover.FORMAT_PNG if cover[1] == "image/png"
               else MP4Cover.FORMAT_JPEG)
        m["covr"] = [MP4Cover(cover[0], imageformat=fmt)]
        changed = True
    if do_lyric and lyric:
        m["\u00a9lyr"] = [lyric]
        changed = True
    if hit:
        if hit.title and "\u00a9nam" not in m:
            m["\u00a9nam"] = [hit.title]; changed = True
        if hit.artist and "\u00a9ART" not in m:
            m["\u00a9ART"] = [normalize_artist(hit.artist)]; changed = True
        if hit.album and "\u00a9alb" not in m:
            m["\u00a9alb"] = [hit.album]; changed = True
        if hit.year and "\u00a9day" not in m:
            m["\u00a9day"] = [hit.year]; changed = True
        if hit.track and "trkn" not in m:
            try:
                m["trkn"] = [(int(hit.track), 0)]; changed = True
            except Exception:  # noqa: BLE001
                pass
    if changed:
        m.save()
    return changed


def _write_ogg(path, audio, hit, cover, lyric, do_cover, do_lyric):
    if audio.tags is None:
        audio.add_tags()
    changed = False
    if do_cover and cover:
        pic = Picture()
        pic.type = 3
        pic.mime = cover[1]
        pic.desc = "cover"
        pic.data = cover[0]
        audio["metadata_block_picture"] = [
            base64.b64encode(pic.write()).decode("ascii")]
        changed = True
    if do_lyric and lyric:
        audio["LYRICS"] = [lyric]
        audio["UNSYNCEDLYRICS"] = [lyric]
        changed = True
    if hit:
        if hit.title and not audio.tags.get("title"):
            audio["title"] = [hit.title]; changed = True
        if hit.artist and not audio.tags.get("artist"):
            audio["artist"] = [normalize_artist(hit.artist)]; changed = True
        if hit.album and not audio.tags.get("album"):
            audio["album"] = [hit.album]; changed = True
        if hit.year and not audio.tags.get("date"):
            audio["date"] = [hit.year]; changed = True
        if hit.track and not audio.tags.get("tracknumber"):
            audio["tracknumber"] = [hit.track]; changed = True
    if changed:
        audio.save()
    return changed


# ---------------------------------------------------------------------------
# 单文件主流程
# ---------------------------------------------------------------------------

def enrich_one(src, out, args):
    lines = []
    ext = os.path.splitext(src)[1].lower()
    if ext not in AUDIO_EXTS:
        return "跳过（不支持的格式）"
    if ext == ".aac":
        return "跳过（裸 AAC 流不支持写标签，请用 M4A 容器）"

    artist, title, has_cover, has_lyric = read_existing(src)
    artist, title = parse_identity(src, args.artist, args.title,
                                   existing=(artist, title))
    if not title:
        return "跳过（无法解析歌名）"
    dur_ms = file_duration_ms(src)
    if dur_ms <= 0:
        return "跳过（无法读取时长）"
    lines.append(f"解析: 歌手={artist or '未知'} | 歌名={title} | 时长={dur_ms/1000:.0f}s")

    tol_ms = int(args.tol * 1000)
    want_cover = (not has_cover or args.force) and not args.no_cover
    want_lyric = (not has_lyric or args.force) and not args.no_lyric
    miss_year, miss_track = file_missing_meta(src)
    want_meta = (miss_year or miss_track) and not args.no_meta
    if not want_cover and not want_lyric and not want_meta and not args.rename:
        # 已具备封面+歌词+元数据，无需联网：仍按要求复制到输出目录
        lines.append("已具备封面+歌词")
        return _copy_out(src, out, args, lines)

    return _do_enrich(src, out, ext, artist, title, dur_ms, tol_ms,
                      want_cover, want_lyric, want_meta, args, lines)


def _copy_out(src, out, args, lines):
    """无需处理时，仅把原文件复制到输出目录"""
    rel = os.path.relpath(out)
    if args.dry_run:
        lines.append(f"预演: 复制到 {rel}")
        return "\n".join(lines) + "\n(DRY-RUN 未写入)"
    try:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        shutil.copy2(src, out)
        lines.append(f"✓ 已复制到 {rel}")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return "\n".join(lines) + f"\n✗ 复制失败: {e}"


def _do_enrich(src, out, ext, artist, title, dur_ms, tol_ms, want_cover,
               want_lyric, want_meta, args, lines):
    # 搜索顺序：文件名拆出的可能颠倒，做双向尝试
    orders = [(artist, title)]
    if not args.artist and not args.title and not _has_source_tags(src):
        parts = parse_from_filename(src)
        if parts and (parts[1], parts[0]) not in orders:
            orders.append((parts[1], parts[0]))

    hit = None
    reason = "无搜索结果"
    relaxed = False

    def _search(ar, ti):
        kh, nh = [], []
        try:
            kh = search_song("kugou", ar, ti, args.cache)
        except Exception as e:  # noqa: BLE001
            nonlocal reason
            reason = f"酷狗搜索失败: {e}"
        try:
            nh = search_song("netease", ar, ti, args.cache)
        except Exception:  # noqa: BLE001
            nh = []
        return kh, nh

    # 阶段1：歌手+歌名 严格匹配（歌手必须一致）
    for ar, ti in orders:
        kh, nh = _search(ar, ti)
        kbest, r1 = pick_best(kh, ar, ti, dur_ms, tol_ms, strict_singer=True)
        nbest, r2 = pick_best(nh, ar, ti, dur_ms, tol_ms, strict_singer=True)
        reason = r2 or r1
        if kbest or nbest:
            hit = kbest or nbest
            if kbest:
                kbest.multi_source = nbest is not None
            break

    # 阶段2：纯歌名重搜 + 宽松匹配（歌名+时长为硬约束，歌手仅加分）
    #        解决"歌手写法不同 / 字段有误"导致的搜不到
    if not hit:
        for _ar, ti in orders:
            kh, nh = _search("", ti)
            kbest, r1 = pick_best(kh, artist, ti, dur_ms, tol_ms, strict_singer=False)
            nbest, r2 = pick_best(nh, artist, ti, dur_ms, tol_ms, strict_singer=False)
            reason = r2 or r1
            if kbest or nbest:
                hit = kbest or nbest
                relaxed = True
                if kbest:
                    kbest.multi_source = nbest is not None
                break

    if not hit:
        # 最后兜底：只要歌词（歌名 + 时长）
        if want_lyric:
            lrc = _fallback_lyric(orders, dur_ms, tol_ms, args)
            if lrc:
                return _write(src, out, ext, None, None, lrc, args, lines, "宽松匹配")
        lines.append("⚠ 搜索匹配失败: " + reason)
        return "\n".join(lines)

    src_label = "酷狗+网易云" if hit.multi_source else hit.source
    flag = "（宽松匹配）" if relaxed else ""
    lines.append(f"✓ 匹配: {hit.artist} - {hit.title}（{hit.album}）[{src_label}]{flag}")

    # 补齐年份 / 音轨号（来自网易云）
    if want_meta:
        try:
            y, t = fetch_extra_meta(hit, artist, title, dur_ms, tol_ms, args.cache)
            hit.year, hit.track = y, t
            if y or t:
                bits = ([f"年份 {y}"] if y else []) + ([f"音轨 {t}"] if t else [])
                lines.append("✓ 元数据: " + " / ".join(bits))
        except Exception:  # noqa: BLE001
            pass

    cover = None
    if want_cover:
        cover = fetch_cover(hit, args.cache)
        lines.append(f"✓ 封面已下载 ({len(cover[0])//1024} KB, {cover[1]})"
                     if cover else "⚠ 封面下载失败（跳过）")
    lyric = (_fetch_lyric(hit, artist, title, dur_ms, tol_ms, args.cache)
             if want_lyric else None)
    if want_lyric and not lyric:
        lines.append("⚠ 歌词搜索失败（跳过）")
    return _write(src, out, ext, hit, cover, lyric, args, lines, "")


def _fetch_lyric(hit, artist, title, dur_ms, tol_ms, use_cache=True):
    """歌词：酷狗优先 → 网易云 → 酷我，均带歌名/时长校验"""
    ha, ht = hit.artist or artist, hit.title or title
    try:
        for c in Kugou.search_lyric(ha, ht, dur_ms):
            if names_ok(c["title"], ht) and \
                    abs(c["duration_ms"] - dur_ms) <= max(tol_ms, 1000):
                lrc = Kugou.download_lyric(c["id"], c["accesskey"])
                if lrc:
                    return clean_lrc(lrc)
    except Exception:  # noqa: BLE001
        pass
    try:
        nhits = search_song("netease", ha, ht, use_cache)
        nbest, _ = pick_best(nhits, ha, ht, dur_ms, tol_ms, strict_singer=False)
        if nbest and nbest.extra.get("id"):
            lrc = Netease.download_lyric(nbest.extra["id"])
            if lrc:
                return clean_lrc(lrc)
    except Exception:  # noqa: BLE001
        pass
    try:
        for c in Kuwo.search_lyric(ha, ht):
            if names_ok(c["title"], ht) and \
                    abs(c["duration_ms"] - dur_ms) <= max(tol_ms, 1000):
                lrc = Kuwo.download_lyric(c["id"])
                if lrc:
                    return clean_lrc(lrc)
    except Exception:  # noqa: BLE001
        pass
    return None


def _fallback_lyric(orders, dur_ms, tol_ms, args):
    """宽松兜底歌词：只要歌名 + 时长；酷狗 / 网易云 / 酷我 三源"""
    for ar, ti in orders:
        try:
            for c in Kugou.search_lyric(ar, ti, dur_ms):
                if names_ok(c["title"], ti) and \
                        abs(c["duration_ms"] - dur_ms) <= max(tol_ms, 1000):
                    lrc = Kugou.download_lyric(c["id"], c["accesskey"])
                    if lrc:
                        return clean_lrc(lrc)
        except Exception:  # noqa: BLE001
            pass
        try:
            nhits = search_song("netease", ar, ti, args.cache)
            nbest, _ = pick_best(nhits, ar, ti, dur_ms, tol_ms, strict_singer=False)
            if nbest and nbest.extra.get("id"):
                lrc = Netease.download_lyric(nbest.extra["id"])
                if lrc:
                    return clean_lrc(lrc)
        except Exception:  # noqa: BLE001
            pass
        try:
            for c in Kuwo.search_lyric(ar, ti):
                if names_ok(c["title"], ti) and \
                        abs(c["duration_ms"] - dur_ms) <= max(tol_ms, 1000):
                    lrc = Kuwo.download_lyric(c["id"])
                    if lrc:
                        return clean_lrc(lrc)
        except Exception:  # noqa: BLE001
            pass
    return None


def _has_source_tags(path):
    a, t, _, _ = read_existing(path)
    return bool(a or t)


# ---------------------------------------------------------------------------
# 写入 + 重命名
# ---------------------------------------------------------------------------

def _sanitize(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name)
    return name.strip().strip(".").strip()


def _write(src, out, ext, hit, cover, lyric, args, lines, note):
    do_cover = cover is not None
    do_lyric = lyric is not None
    out_stem = os.path.splitext(out)[0]
    final_out = out

    if args.dry_run:
        if do_cover:
            lines.append("预演: 内嵌封面")
        if do_lyric:
            lines.append(f"预演: 内嵌歌词({len(lyric)}字) + 输出 .lrc")
        if args.rename and hit and hit.title:
            lines.append(f"预演: 重命名为「{hit.title} - {hit.artist}」")
        lines.append(f"预演: 输出到 {os.path.relpath(out)}")
        return "\n".join(lines) + "\n(DRY-RUN 未写入)"

    # 1) 复制原文件到输出位置（原文件保持不动）
    try:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        shutil.copy2(src, out)
    except Exception as e:  # noqa: BLE001
        return "\n".join(lines) + f"\n✗ 复制到输出失败: {e}"

    # 2) 对输出副本写入封面/歌词/元数据
    changed = False
    try:
        changed = write_tags(out, hit, cover, lyric, do_cover, do_lyric)
    except Exception as e:  # noqa: BLE001
        return "\n".join(lines) + f"\n✗ 写入失败: {e}"

    # 3) 输出 .lrc（编码可配置，兼容车载/老播放器）
    if do_lyric and lyric and not args.no_lrc_file:
        try:
            with open(out_stem + ".lrc", "w", encoding=args.lrc_encoding,
                      errors="replace") as f:
                f.write(lyric + "\n")
            enc = args.lrc_encoding.upper()
            lines.append(f"✓ 已输出 {os.path.basename(out_stem)}.lrc（{enc}）")
        except Exception as e:  # noqa: BLE001
            lines.append(f"⚠ .lrc 写入失败: {e}")

    # 4) 文件名规范化（可选，作用于输出副本）
    if args.rename and hit and hit.title:
        newbase = f"{hit.title} - {hit.artist}".strip(" -")
        newstem = os.path.join(os.path.dirname(out), _sanitize(newbase))
        newpath = newstem + ext
        if newpath != out and not os.path.exists(newpath):
            try:
                os.rename(out, newpath)
                # 同名 .lrc 一并跟随重命名
                if os.path.exists(out_stem + ".lrc"):
                    os.rename(out_stem + ".lrc", newstem + ".lrc")
                final_out = newpath
                lines.append(f"✓ 已重命名为 {os.path.basename(newpath)}")
            except Exception as e:  # noqa: BLE001
                lines.append(f"⚠ 重命名失败: {e}")

    lines.append(f"✓ 已输出到 {os.path.relpath(final_out)}")
    if note:
        lines.append(f"({note})")
    return "\n".join(l for l in lines if l)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def collect_files(paths, recursive, outdir_name):
    """收集待处理文件，返回 [(源文件, 输出文件)]。

    原始文件保持不动；每个输出统一放到输入根目录下的 outdir_name/ 文件夹里。
    处理目录且递归时，在输出文件夹内保留相对子目录结构。
    """
    items = []
    for p in paths:
        if os.path.isdir(p):
            out_root = os.path.join(p, outdir_name)
            out_root_abs = os.path.abspath(out_root)
            if recursive:
                for root, dirs, fns in os.walk(p):
                    # 仅跳过输入根目录下的输出目录本身，避免误伤同名子目录
                    dirs[:] = [d for d in dirs
                               if os.path.abspath(os.path.join(root, d)) != out_root_abs]
                    for fn in sorted(fns):
                        if os.path.splitext(fn)[1].lower() in AUDIO_EXTS:
                            src = os.path.join(root, fn)
                            rel = os.path.relpath(src, p)
                            items.append((src, os.path.join(out_root, rel)))
            else:
                for fn in sorted(os.listdir(p)):
                    src = os.path.join(p, fn)
                    if os.path.isfile(src) and os.path.splitext(src)[1].lower() in AUDIO_EXTS:
                        items.append((src, os.path.join(out_root, fn)))
        elif os.path.isfile(p):
            out_root = os.path.join(os.path.dirname(p) or ".", outdir_name)
            items.append((p, os.path.join(out_root, os.path.basename(p))))
    return items


def main():
    ap = argparse.ArgumentParser(
        description=f"联网补齐音频封面与歌词 v{VERSION}"
                    "（酷狗主源 + 网易云/酷我副源）")
    ap.add_argument("paths", nargs="+", help="一个或多个文件/目录")
    ap.add_argument("-r", "--recursive", action="store_true", help="递归处理目录")
    ap.add_argument("--artist", default="", help="手动指定歌手")
    ap.add_argument("--title", default="", help="手动指定歌名")
    ap.add_argument("--tol", type=float, default=5.0, help="时长容差(秒)，默认5")
    ap.add_argument("--jobs", type=int, default=4, help="并发线程数，默认4")
    ap.add_argument("--rename", action="store_true",
                    help="成功后把文件名规范成「歌名 - 歌手」")
    ap.add_argument("--outdir", default="output",
                    help="输出文件夹名（在各输入根目录下创建），默认 output")
    ap.add_argument("--lrc-encoding", default="utf-8",
                    help=".lrc 编码（车载/老播放器可用 gbk），默认 utf-8")
    ap.add_argument("--no-cache", action="store_true", help="禁用本地搜索/封面缓存")
    ap.add_argument("--no-cover", action="store_true", help="不处理封面")
    ap.add_argument("--no-lyric", action="store_true", help="不处理歌词")
    ap.add_argument("--no-meta", action="store_true", help="不补齐年份/音轨号")
    ap.add_argument("--no-lrc-file", action="store_true", help="歌词只内嵌不输出.lrc")
    ap.add_argument("--force", action="store_true", help="已有封面/歌词也覆盖")
    ap.add_argument("--dry-run", action="store_true", help="只预览不写入")
    args = ap.parse_args()
    args.cache = not args.no_cache

    if not _HAS_ZHCONV:
        print("提示: 未安装 zhconv，简繁匹配降级为内置表。建议 pip install zhconv\n")

    items = collect_files(args.paths, args.recursive, args.outdir)
    if not items:
        print("没有找到可处理的音频文件")
        return

    cache_load()
    total = len(items)
    print(f"共 {total} 个文件，{args.jobs} 线程并发处理，"
          f"结果输出到「{args.outdir}/」...\n")

    lock = threading.Lock()
    done = 0
    records = {}    # idx -> (src, result)

    def task(idx, src, out):
        try:
            return idx, src, enrich_one(src, out, args)
        except Exception as e:  # noqa: BLE001
            return idx, src, f"✗ 处理出错: {type(e).__name__}: {e}"

    try:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            futs = {ex.submit(task, i, s, o): (i, s)
                    for i, (s, o) in enumerate(items, 1)}
            for fut in as_completed(futs):
                idx, src, res = fut.result()
                with lock:
                    done += 1
                    records[idx] = (src, res)
                    print(f"[{done}/{total}] {src}")
                    print("  " + res.replace("\n", "\n  "))
    except KeyboardInterrupt:
        print("\n⚠ 已中断（缓存已保存）")
    finally:
        cache_save(args.cache)

    # ---- 汇总报告 ----
    stats = {"ok": 0, "skip": 0, "fail": 0}
    bad = []
    for idx in sorted(records):
        src, res = records[idx]
        if "✗" in res or "失败" in res or "处理出错" in res:
            stats["fail"] += 1
            bad.append(("✗", src))
        elif res.startswith("跳过"):
            stats["skip"] += 1
            bad.append(("·", src))
        else:
            stats["ok"] += 1

    print(f"\n==== 完成: 成功 {stats['ok']} / 跳过 {stats['skip']} "
          f"/ 失败 {stats['fail']} ====")
    if bad:
        print("未成功项：")
        for mark, s in bad:
            print(f"  {mark} {s}")


if __name__ == "__main__":
    main()
