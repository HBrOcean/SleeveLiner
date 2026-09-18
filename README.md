<p align="center">
  <img src="assets/cover_named.jpg" width="320" alt="SleeveLiner cover">
</p>

<h1 align="center">SleeveLiner</h1>

<p align="center">
  <b>为没有封面、没有歌词的本地音乐文件，联网自动补齐封面与歌词</b>
</p>

<p align="center">
  <a href="README.en.md">English</a> · <b>简体中文</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-3DA639" alt="License">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/Formats-MP3%20%7C%20FLAC%20%7C%20M4A%20%7C%20OPUS%20%7C%20OGG-orange" alt="Formats">
</p>

---

从网上下载的音乐，经常**没有封面、没有内嵌歌词、也没有 `.lrc` 文件**。
**SleeveLiner** 会联网搜索，把封面、歌词、元数据自动补全，并统一输出到 `output/` 文件夹——
**原始文件始终不动**。

> 名字取自黑胶唱片：**sleeve**（唱片封套）+ **liner notes**（唱片内页文案）——
> 正好对应它做的两件事：**补封面**、**补歌词**。

## ✨ 特性

| | |
|---|---|
| 🎵 **多格式** | MP3 / FLAC / M4A / OPUS / OGG |
| 🌐 **多数据源** | 酷狗（真实封面 + 歌词）+ 网易云（高清封面、年份/音轨）+ 酷我（歌词兜底） |
| 🖼️ **封面** | 自动取高清图（酷狗 400/800 择清晰者、网易云 800×800），内嵌进文件 |
| 📝 **歌词** | 联网匹配 → 内嵌 + 另存同名 `.lrc`（编码可选 UTF-8 / GBK） |
| 🏷️ **元数据** | 缺标题 / 歌手 / 专辑 / 年份 / 音轨号时自动补齐 |
| 🛡️ **防错配** | 歌名 + 歌手 + 时长三重校验；简体繁体、歌手别名自动归一 |
| 🔁 **宽松二次匹配** | 严格匹配失败时，用纯歌名重搜 + 「歌名/时长」硬约束再试一次 |
| 📂 **无损原文件** | 结果输出到 `output/`，原文件保持不动 |
| ⚡ **批量并发** | 多线程处理 + 本地缓存，大批量也快 |
| 🧩 **零配置** | 一条命令即可，无需手动指定封面/歌词地址 |

## 📦 安装

```bash
pip install mutagen          # 必需
pip install zhconv           # 可选但强烈建议：简体/繁体匹配
```

## 🚀 快速开始

```bash
# 处理单个文件
python sleeve_liner.py 周杰伦-晴天.mp3

# 处理整个文件夹（递归子目录）
python sleeve_liner.py "D:/Music/" -r

# 递归 + 6 线程 + 顺便把文件名规范成「歌名 - 歌手」
python sleeve_liner.py "D:/Music/" -r --jobs 6 --rename

# 只预览会搜到什么，不写入
python sleeve_liner.py x.mp3 --dry-run

# 歌词输出 GBK 编码（兼容车载音响 / 老播放器）
python sleeve_liner.py "D:/Music/" -r --lrc-encoding gbk

# 文件没有名字，手动指定歌手/歌名
python sleeve_liner.py 无名.flac --artist 陈奕迅 --title 十年
```

## 📂 输出说明

- **原始文件保持不动**，绝不修改
- 处理结果（**补全后的音频副本 + `.lrc`**）统一放进各输入根目录下的 **`output/`**
- 递归处理时，`output/` 内**保留原有子目录结构**
- 输出文件夹名可用 `--outdir 名字` 自定义

```
D:/Music/                      ← 你的原始文件，不动
├─ 周杰伦-晴天.mp3
└─ output/                     ← 处理结果都在这里
    ├─ 周杰伦-晴天.mp3          （已内嵌封面 + 歌词 + 元数据）
    └─ 周杰伦-晴天.lrc
```

## ⚙️ 命令行参数

| 参数 | 作用 | 默认 |
|---|---|---|
| `paths` | 一个或多个文件 / 目录 | 必填 |
| `-r, --recursive` | 递归处理目录 | 关 |
| `--artist` / `--title` | 手动指定歌手 / 歌名 | 自动解析 |
| `--tol` | 时长匹配容差（秒） | 5 |
| `--jobs` | 并发线程数 | 4 |
| `--rename` | 成功后将文件名规范成「歌名 - 歌手」 | 关 |
| `--outdir` | 输出文件夹名 | `output` |
| `--lrc-encoding` | `.lrc` 编码（车载可用 `gbk`） | `utf-8` |
| `--no-cover` / `--no-lyric` | 只做其中一项 | 都做 |
| `--no-meta` | 不补齐年份 / 音轨号 | 补齐 |
| `--no-lrc-file` | 歌词只内嵌、不输出 `.lrc` | 输出 |
| `--no-cache` | 禁用本地搜索 / 封面缓存 | 启用 |
| `--force` | 已有封面 / 歌词也覆盖 | 跳过已有的 |
| `--dry-run` | 只预览，不写入 | 关 |

## 🛡️ 匹配逻辑：宁可不写，也不写错

同名歌曲、不同版本极多，程序用**三重校验**防止张冠李戴：

1. **歌名匹配** —— 归一化后一致或包含（自动忽略大小写、标点、简繁，以及 `(Live)` / `伴奏` / `remix` / `HQ` 等版本噪声）
2. **歌手匹配** —— 主链路严格比对，并做**简繁统一 + 别名归一**
   （如 `陳奕迅=陈奕迅`、`G.E.M.邓紫棋=邓紫棋`、`Jay Chou=周杰伦`）
3. **时长匹配** —— 实际时长与候选相差 ≤ 5 秒（`--tol` 可调）

**任何一关不过 → 拒绝写入。**

严格匹配失败后，还有一层**宽松二次匹配**：用纯歌名重搜，改以「歌名 + 时长」为硬约束、
歌手作为加分项再试一次（命中会标注「宽松匹配」），用于解决"歌手写法不同 / 字段有误"的情况。

## 🔧 工作原理

```
[文件] ──(标签/文件名)──> (歌手, 歌名) ──(实际时长)──> 多源联网搜索
                                                          │
        ┌─────────── 酷狗搜歌曲 ───────────┐
        │                                   │
        网易云搜歌曲 ── 交叉印证 ──> 选定曲目（严格 → 宽松重搜）
                                                          │
        封面：酷狗 union_cover / 网易云 ──> 内嵌
        歌词：酷狗 / 网易云 / 酷我 ──> 清洗 ──> 内嵌 + .lrc
```

- 写入字段：MP3 用 ID3v2.4（`APIC`/`USLT`/`TDRC`/`TRCK`…）；
  FLAC、OGG/OPUS 用 VorbisComment（`PICTURE` + `LYRICS`/`UNSYNCEDLYRICS` 双写）；
  M4A 用 `covr`/`©lyr`/`©day`/`trkn`
- 歌词语言标签按内容自动判断（中/日/韩 → `chi`/`jpn`/`kor`）
- 歌词会清洗掉酷狗私有标签行（`[id:]` `[hash:]` …），播放器显示更干净

## ❓ 常见问题

**Q：搜不到怎么办？**
冷门歌、网易云无版权的歌可能搜不到。程序会明确提示"搜索匹配失败"，此时该文件**不会输出**，避免写错。

**Q：为什么有的歌没补上年份？**
年份来自网易云，且只在**能可靠匹配**时才写。若该曲在网易云无版权或存在多个版本，宁可留空也不乱填。

**Q：会不会改坏我的原文件？**
不会。所有结果都输出到 `output/`，原文件一个字节都不动。

**Q：歌词在车载上乱码？**
加 `--lrc-encoding gbk`，多数车载/老播放器只认 GBK。

## 📄 更新日志

见 [CHANGELOG.md](CHANGELOG.md)。

## 📜 License

[MIT](LICENSE) © 2026 Oceaniat
