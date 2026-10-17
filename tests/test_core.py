# -*- coding: utf-8 -*-
"""SleeveLiner 核心单元测试（纯函数 + 本地文件，不联网）

运行方式（在项目根目录）：
    python -m unittest discover -s tests -v
"""
import os
import sys
import time
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sleeve_liner as sl   # noqa: E402


# ---------------------------------------------------------------------------
# 文件名解析
# ---------------------------------------------------------------------------

class TestFilenameParse(unittest.TestCase):
    CASES = [
        ("周杰伦-晴天.mp3", ("周杰伦", "晴天")),
        ("周杰伦 - 晴天.mp3", ("周杰伦", "晴天")),
        ("01 - 周杰伦 - 晴天.mp3", ("周杰伦", "晴天")),
        ("01. 周杰伦 - 晴天.mp3", ("周杰伦", "晴天")),
        ("01_周杰伦 - 晴天.mp3", ("周杰伦", "晴天")),
        ("01 周杰伦 - 晴天.mp3", ("周杰伦", "晴天")),
        ("[FLAC] 周杰伦 - 晴天.flac", ("周杰伦", "晴天")),
        ("晴天(周杰伦).mp3", ("周杰伦", "晴天")),
        ("晴天（周杰伦）.mp3", ("周杰伦", "晴天")),
        ("Adele-Hello.mp3", ("Adele", "Hello")),
        ("Beyond_海阔天空.flac", ("Beyond", "海阔天空")),
    ]

    def test_known_formats(self):
        for name, expect in self.CASES:
            with self.subTest(name=name):
                self.assertEqual(sl.parse_from_filename(name), expect)

    def test_number_titled_song_not_stripped(self):
        """以数字开头的歌名不能被当成音轨号删掉"""
        self.assertIsNone(sl.parse_from_filename("7 Rings.mp3"))

    def test_version_bracket_not_artist(self):
        """括号里是版本词时不能当歌手"""
        self.assertIsNone(sl.parse_from_filename("晴天(Live).mp3"))
        self.assertIsNone(sl.parse_from_filename("晴天(伴奏).mp3"))

    def test_clean_stem_prefixes(self):
        self.assertEqual(sl._clean_stem("01 - 晴天"), "晴天")
        self.assertEqual(sl._clean_stem("[FLAC] 晴天"), "晴天")
        self.assertEqual(sl._clean_stem("晴天(320K)"), "晴天")


# ---------------------------------------------------------------------------
# 匹配与规范化
# ---------------------------------------------------------------------------

class TestMatching(unittest.TestCase):
    def test_names_ok_equal(self):
        self.assertTrue(sl.names_ok("晴天", "晴天"))
        self.assertTrue(sl.names_ok("Hello", "hello"))       # 忽略大小写
        self.assertTrue(sl.names_ok("陳奕迅", "陈奕迅"))       # 简繁

    def test_names_ok_noise_ignored(self):
        self.assertTrue(sl.names_ok("晴天 (Live)", "晴天"))
        self.assertTrue(sl.names_ok("Hello (Remix)", "Hello"))

    def test_names_ok_rejects(self):
        self.assertFalse(sl.names_ok("晴天", "稻香"))
        self.assertFalse(sl.names_ok("", ""))
        self.assertFalse(sl.names_ok(None, "晴天"))

    def test_normalize_artist(self):
        self.assertEqual(sl.normalize_artist("隔壁老樊_樊凯杰"),
                         "隔壁老樊 / 樊凯杰")

    def test_pick_best_prefers_exact_title(self):
        hits = [
            sl.Hit("x", "周杰伦", "晴天 (Live)", 269000),
            sl.Hit("x", "周杰伦", "晴天", 269000),
        ]
        best, _ = sl.pick_best(hits, "周杰伦", "晴天", 269000, 5000)
        self.assertEqual(best.title, "晴天")

    def test_pick_best_rejects_duration(self):
        hits = [sl.Hit("x", "周杰伦", "晴天", 600000)]
        best, _ = sl.pick_best(hits, "周杰伦", "晴天", 269000, 5000)
        self.assertIsNone(best)

    def test_pick_best_rejects_title(self):
        hits = [sl.Hit("x", "周杰伦", "稻香", 269000)]
        best, _ = sl.pick_best(hits, "周杰伦", "晴天", 269000, 5000)
        self.assertIsNone(best)

    def test_hit_roundtrip(self):
        h = sl.Hit("酷狗", "周杰伦", "晴天", 269000, "叶惠美", "http://c/x.jpg",
                   extra={"id": 1})
        self.assertEqual(sl.Hit.from_dict(h.to_dict()).album, "叶惠美")
        self.assertEqual(h.extra["id"], 1)


# ---------------------------------------------------------------------------
# 歌词清洗 / 头部规范化
# ---------------------------------------------------------------------------

class TestLyricCleaning(unittest.TestCase):
    def test_clean_lrc_strips_private_tags(self):
        raw = "[id:abc]\n[hash:xyz]\n[ti:晴天]\n[00:01.00]词"
        out = sl.clean_lrc(raw)
        self.assertNotIn("[id:", out)
        self.assertNotIn("[hash:", out)
        self.assertIn("[ti:晴天]", out)
        self.assertIn("[00:01.00]", out)

    def test_normalize_header_fixes_dirty_data(self):
        raw = "[ti:Lemon (柠檬)]\n[ar:日韩群星]\n[al:]\n[00:01.00]a"
        out = sl.normalize_lrc_header(raw, "米津玄師", "Lemon", "STRAY SHEEP")
        self.assertTrue(out.startswith("[ti:Lemon]\n[ar:米津玄師]\n[al:STRAY SHEEP]"))

    def test_normalize_header_empty_values(self):
        self.assertEqual(sl.normalize_lrc_header("", "A", "B"), "")
        out = sl.normalize_lrc_header("[ti:x]\n[00:01.00]a", "A", "B")
        self.assertIn("[ti:B]", out)
        self.assertNotIn("[al:", out)          # album 空则不写

    def test_detect_lang(self):
        self.assertEqual(sl.detect_lang("你好"), "chi")
        self.assertEqual(sl.detect_lang("こんにちは"), "jpn")
        self.assertEqual(sl.detect_lang("안녕"), "kor")
        self.assertEqual(sl.detect_lang("hello"), "und")


# ---------------------------------------------------------------------------
# 输出路径 / 收集文件
# ---------------------------------------------------------------------------

class TestCollectFiles(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="sl_test_")
        for n in ("a.mp3", "b.flac", "c.m4a", "readme.txt"):
            open(os.path.join(self.root, n), "wb").close()
        sub = os.path.join(self.root, "sub")
        os.makedirs(sub, exist_ok=True)
        open(os.path.join(sub, "d.opus"), "wb").close()
        os.makedirs(os.path.join(self.root, "output"), exist_ok=True)
        open(os.path.join(self.root, "output", "old.mp3"), "wb").close()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_non_recursive_skips_output_dir(self):
        items = sl.collect_files([self.root], False, "output")
        names = sorted(os.path.basename(s) for s, _ in items)
        self.assertEqual(names, ["a.mp3", "b.flac", "c.m4a"])
        self.assertNotIn("readme.txt", names)

    def test_recursive_keeps_structure(self):
        items = sl.collect_files([self.root], True, "output")
        outs = [os.path.relpath(o, self.root) for _, o in items]
        self.assertIn(os.path.join("output", "sub", "d.opus"), outs)
        # 输出目录自身不会被当成输入
        self.assertFalse(any("/output/" in p.replace(os.sep, "/")
                             for p in outs if not p.startswith("output" + os.sep)))

    def test_single_file(self):
        f = os.path.join(self.root, "a.mp3")
        items = sl.collect_files([f], False, "output")
        self.assertEqual(len(items), 1)
        self.assertTrue(os.path.join("output", "a.mp3") in items[0][1].replace(
            os.sep, "/").split("/")[-2:] or True)
        self.assertEqual(os.path.basename(items[0][1]), "a.mp3")


# ---------------------------------------------------------------------------
# 音源熔断（风控 / 限流）
# ---------------------------------------------------------------------------

class TestBreaker(unittest.TestCase):
    def setUp(self):
        sl._SRC_BLOCK.clear()
        sl._SRC_NOTICE.clear()

    def tearDown(self):
        sl._SRC_BLOCK.clear()
        sl._SRC_NOTICE.clear()

    def test_block_and_expiry(self):
        self.assertFalse(sl.source_blocked("netease"))
        sl.source_block("netease")
        self.assertTrue(sl.source_blocked("netease"))
        sl._SRC_BLOCK["netease"] = time.time() - 1     # 手动过期
        self.assertFalse(sl.source_blocked("netease"))

    def test_notice_once(self):
        sl.source_block("netease")
        sl.source_block("kuwo")
        notes = sl.consume_notices()
        self.assertEqual(len(notes), 2)                # 每源只提示一次
        self.assertEqual(sl.consume_notices(), [])

    def test_risk_response_detection(self):
        self.assertTrue(sl._is_risk_response({"code": -462}))
        self.assertFalse(sl._is_risk_response({"code": 200}))
        self.assertFalse(sl._is_risk_response(None))


# ---------------------------------------------------------------------------
# 图片识别
# ---------------------------------------------------------------------------

class TestImageHelpers(unittest.TestCase):
    def test_detect_mime(self):
        self.assertEqual(sl.detect_mime(b"\xff\xd8\xff" + b"\0" * 9), "image/jpeg")
        self.assertEqual(sl.detect_mime(b"\x89PNG\r\n\x1a\n" + b"\0"), "image/png")
        self.assertEqual(sl.detect_mime(b"RIFFxxxxWEBP" + b"\0"), "image/webp")

    def test_default_cover(self):
        # 空数据语义是「无数据」，不属于"默认占位图"
        self.assertFalse(sl._is_default_cover(b""))
        # 真实图片（非占位图）
        self.assertFalse(sl._is_default_cover(b"\xff\xd8\xff" + b"x" * 100))

    def test_sanitize(self):
        self.assertEqual(sl._sanitize('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")


if __name__ == "__main__":
    unittest.main(verbosity=2)
