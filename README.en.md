<p align="center">
  <img src="assets/cover_named.jpg" width="320" alt="SleeveLiner cover">
</p>

<h1 align="center">SleeveLiner</h1>

<p align="center">
  <b>Auto-fill cover art and lyrics for your local music files — straight from the internet.</b>
</p>

<p align="center">
  <a href="README.md">简体中文</a> · <b>English</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-3DA639" alt="License">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/Formats-MP3%20%7C%20FLAC%20%7C%20M4A%20%7C%20OPUS%20%7C%20OGG-orange" alt="Formats">
</p>

---

Music downloaded from the web often comes with **no cover art, no embedded lyrics, and no `.lrc` file**.
**SleeveLiner** searches online and automatically fills in the cover art, lyrics and metadata — writing
everything to an `output/` folder while **leaving your original files untouched**.

> The name comes from vinyl records: **sleeve** (the record sleeve) + **liner notes** —
> exactly the two things it does: **fill cover art** and **fill lyrics**.

## ✨ Features

| | |
|---|---|
| 🎵 **Multi-format** | MP3 / FLAC / M4A / OPUS / OGG |
| 🌐 **Multi-source** | Kugou (real covers + lyrics) + NetEase Cloud (HD covers, year/track) + Kuwo (lyrics fallback) |
| 🖼️ **Cover art** | Picks the clearest image (Kugou 400/800, NetEase 800×800) and embeds it |
| 📝 **Lyrics** | Matched online → embedded + saved as `.lrc` (UTF-8 or GBK) |
| 🏷️ **Metadata** | Fills missing title / artist / album / year / track number |
| 🛡️ **Anti-mismatch** | Triple check on title + artist + duration; Simplified/Traditional & artist aliases normalized |
| 🔁 **Relaxed retry** | On a strict-match miss, re-searches by title only with title/duration as hard constraints |
| 📂 **Non-destructive** | Results go to `output/`; your originals never change |
| ⚡ **Batch + concurrency** | Multi-threaded with local caching |
| 🧩 **Zero config** | One command — no manual cover/lyric URLs needed |

## 📦 Install

```bash
pip install mutagen          # required
pip install zhconv           # optional but recommended: Simplified/Traditional matching
```

## 🚀 Quick start

```bash
# Single file
python sleeve_liner.py 周杰伦-晴天.mp3

# A whole folder (recursive)
python sleeve_liner.py "D:/Music/" -r

# Recursive + 6 threads + normalize filenames to "Title - Artist"
python sleeve_liner.py "D:/Music/" -r --jobs 6 --rename

# Preview only, write nothing
python sleeve_liner.py x.mp3 --dry-run

# GBK-encoded lyrics (for car stereos / old players)
python sleeve_liner.py "D:/Music/" -r --lrc-encoding gbk

# No usable filename: specify artist/title manually
python sleeve_liner.py unknown.flac --artist 陈奕迅 --title 十年
```

## 📂 Output

- **Originals are never modified**
- Results (**completed audio copy + `.lrc`**) go into an **`output/`** folder under each input root
- With `-r`, the original sub-directory structure is preserved inside `output/`
- The folder name can be changed with `--outdir NAME`

```
D:/Music/                      ← your originals, untouched
├─ 周杰伦-晴天.mp3
└─ output/                     ← everything lands here
    ├─ 周杰伦-晴天.mp3          (cover + lyrics + metadata embedded)
    └─ 周杰伦-晴天.lrc
```

## ⚙️ CLI options

| Option | Description | Default |
|---|---|---|
| `paths` | One or more files / folders | required |
| `-r, --recursive` | Recurse into folders | off |
| `--artist` / `--title` | Specify artist / title manually | auto |
| `--tol` | Duration tolerance (seconds) | 5 |
| `--jobs` | Worker threads | 4 |
| `--rename` | Rename result to "Title - Artist" | off |
| `--outdir` | Output folder name | `output` |
| `--lrc-encoding` | `.lrc` encoding (`gbk` for car stereos) | `utf-8` |
| `--no-cover` / `--no-lyric` | Do only one of the two | both |
| `--no-meta` | Don't fill year / track number | fill |
| `--no-lrc-file` | Embed lyrics only, no `.lrc` | write |
| `--no-cache` | Disable local search / cover cache | enabled |
| `--force` | Overwrite existing cover / lyrics | skip existing |
| `--dry-run` | Preview only, write nothing | off |

## 🛡️ Matching: better nothing than wrong

The same song exists in countless versions, so the tool uses a **triple check** to avoid mismatches:

1. **Title** — equal or contained after normalization (ignores case, punctuation, Simplified/Traditional, and version noise like `(Live)` / `remix` / `HQ`)
2. **Artist** — strictly compared on the main path, with **Simplified/Traditional + alias normalization**
   (e.g. `陳奕迅 = 陈奕迅`, `G.E.M.邓紫棋 = 邓紫棋`, `Jay Chou = 周杰伦`)
3. **Duration** — within 5 s of the candidate (`--tol` to tune)

**Failing any check → nothing is written.**

If the strict match fails, a **relaxed retry** kicks in: it re-searches by title only and treats
title + duration as hard constraints with artist as a bonus (hits are marked "relaxed").

## 🔧 How it works

```
[file] ──(tags/filename)──> (artist, title) ──(duration)──> multi-source search
                                                              │
        ┌──────────────  Kugou search  ──────────────┐
        │                                             │
        NetEase search ── cross-check ──> pick a track (strict → relaxed retry)
                                                              │
        cover: Kugou union_cover / NetEase ──> embed
        lyrics: Kugou / NetEase / Kuwo ──> clean ──> embed + .lrc
```

- Tag fields: MP3 uses ID3v2.4 (`APIC`/`USLT`/`TDRC`/`TRCK`…);
  FLAC & OGG/OPUS use VorbisComment (`PICTURE` + `LYRICS`/`UNSYNCEDLYRICS`);
  M4A uses `covr`/`©lyr`/`©day`/`trkn`
- Lyric language tag is auto-detected (Chinese / Japanese / Korean → `chi` / `jpn` / `kor`)
- Kugou's private tag lines (`[id:]`, `[hash:]`, …) are stripped for cleaner playback

## ❓ FAQ

**Nothing found — what now?**
Obscure tracks or ones missing from the sources simply won't match. The tool says so and
**does not output** that file, to avoid writing wrong data.

**Why is the year missing on some tracks?**
The year comes from NetEase and is only written when the match is **reliable**. If the track is
unavailable or has multiple versions, the field is left blank rather than guessed.

**Will it damage my originals?**
No. Everything is written to `output/`; originals stay byte-for-byte identical.

**Lyrics are garbled on my car stereo?**
Add `--lrc-encoding gbk` — many car stereos / old players only accept GBK.

## 📄 Changelog

See [CHANGELOG.md](CHANGELOG.md).

## 📜 License

[MIT](LICENSE) © 2026 Oceaniat
