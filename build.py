#!/usr/bin/env python3
"""Builds a static site from folders like 0001-two-sum/{README.md,solution*.ext}."""
import datetime as dt
import html
import os
import re
import shutil
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name

# ---- settings you may want to change ---------------------------------------
SITE_TITLE = "LeetCode Journal"
SITE_TAGLINE = "Problems I've solved, how I thought about them, and what they cost."
TIMEZONE = "Asia/Kolkata"  # decides which calendar day a solve counts for
# -----------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "site"

LANGS = {  # ext: (display name, pygments lexer)
    "py": ("Python", "python"), "cpp": ("C++", "cpp"), "c": ("C", "c"),
    "java": ("Java", "java"), "js": ("JavaScript", "javascript"),
    "ts": ("TypeScript", "typescript"), "go": ("Go", "go"),
    "cs": ("C#", "csharp"), "rs": ("Rust", "rust"), "kt": ("Kotlin", "kotlin"),
    "swift": ("Swift", "swift"), "rb": ("Ruby", "ruby"), "php": ("PHP", "php"),
    "scala": ("Scala", "scala"), "dart": ("Dart", "dart"), "sql": ("SQL", "sql"),
    "txt": ("Text", "text"),
}

REPO = os.environ.get("GITHUB_REPOSITORY", "")  # "owner/repo" inside Actions
REPO_URL = f"https://github.com/{REPO}" if REPO else ""
OWNER = REPO.split("/")[0] if REPO else ""

THEME_BOOT = (
    "<script>(function(){var d=document.documentElement;d.classList.add('js');"
    "var t=null;try{t=localStorage.getItem('theme')}catch(e){}"
    "d.dataset.theme=t||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');"
    "})()</script>"
)


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- parsing ----
def clean_complexity(v):
    if not v:
        return None
    v = v.strip().strip("`")
    if not v or re.search(r"O\(\s*\)", v):
        return None
    return v


def parse_problem(folder: Path):
    m = re.match(r"^(\d+)-(.+)$", folder.name)
    if not m:
        return None
    number, slug = int(m.group(1)), m.group(2)

    readme_path = folder / "README.md"
    text = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

    title = slug.replace("-", " ").title()
    t = re.search(r"^#\s+\d+\.\s*(.+)$", text, re.M)
    if t:
        title = t.group(1).strip()

    d = re.search(r"\*\*Difficulty:\*\*\s*(\w+)", text)
    difficulty = d.group(1).capitalize() if d else "Unknown"
    if difficulty not in ("Easy", "Medium", "Hard"):
        difficulty = "Unknown"

    l = re.search(r"\*\*Link:\*\*\s*(\S+)", text)
    link = l.group(1) if l else f"https://leetcode.com/problems/{slug}/"

    tm = re.search(r"\*\*Time:\*\*\s*(.+)", text)
    sp = re.search(r"\*\*Space:\*\*\s*(.+)", text)

    # Strip the H1 + Difficulty/Link lines; the page header already shows them.
    body = re.sub(r"^#\s+\d+\..*$", "", text, count=1, flags=re.M)
    body = re.sub(r"^\*\*(Difficulty|Link):\*\*.*$", "", body, flags=re.M)
    readme_html = markdown.markdown(
        body.strip(),
        extensions=["fenced_code", "tables", "sane_lists", "codehilite"],
        extension_configs={"codehilite": {"css_class": "hl", "guess_lang": False}},
    )

    solutions = []
    for f in folder.iterdir():
        sm = re.match(r"^solution(?:_(\d+))?\.(\w+)$", f.name)
        if not sm:
            continue
        n = int(sm.group(1) or 1)
        ext = sm.group(2)
        lang_name, lexer_name = LANGS.get(ext, (ext.upper(), "text"))
        code = f.read_text(encoding="utf-8", errors="replace")
        code_html = highlight(
            code, get_lexer_by_name(lexer_name), HtmlFormatter(cssclass="hl")
        )
        solutions.append(
            {"file": f.name, "n": n, "lang": lang_name, "code_html": code_html}
        )
    solutions.sort(key=lambda s: (s["lang"], s["n"]))

    return {
        "folder": folder.name, "number": number, "slug": slug, "title": title,
        "difficulty": difficulty, "link": link,
        "time": clean_complexity(tm.group(1) if tm else None),
        "space": clean_complexity(sp.group(1) if sp else None),
        "readme_html": readme_html, "solutions": solutions,
        "langs": sorted({s["lang"] for s in solutions}),
    }



# --------------------------------------------------------------- activity ----
SOLUTION_RE = re.compile(r"^\d{4,}-[^/]+/solution(?:_\d+)?\.\w+$")

PALETTES = {
    "light": dict(empty="#ebedf0", levels=["#9be9a8", "#40c463", "#30a14e", "#216e39"],
                  text="#57606a", strong="#1f2328", ring="#1f2328"),
    "dark": dict(empty="#212b3d", levels=["#0e4429", "#006d32", "#26a641", "#39d353"],
                 text="#8b949e", strong="#e6edf3", ring="#e6edf3"),
}


def solution_counts():
    """{date: number of solution files added that day}, from git history."""
    tz = ZoneInfo(TIMEZONE)
    try:
        out = subprocess.run(
            ["git", "log", "--diff-filter=A", "--name-only", "--format=@@%aI"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except Exception:
        return {}
    counts, day = {}, None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("@@"):
            day = dt.datetime.fromisoformat(line[2:]).astimezone(tz).date()
        elif line and day and SOLUTION_RE.match(line):
            counts[day] = counts.get(day, 0) + 1
    return counts


def streaks(counts, today):
    one = dt.timedelta(days=1)
    d = today if counts.get(today) else today - one  # today not over yet
    current = 0
    while counts.get(d):
        current += 1
        d -= one
    longest = run = 0
    prev = None
    for d in sorted(counts):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d
    return current, longest


def heatmap_svg(counts, today, theme, standalone=True):
    P = PALETTES[theme]
    CELL, STEP, LEFT, TOP, WEEKS = 11, 14, 34, 68, 53
    W = LEFT + WEEKS * STEP + 14
    H = TOP + 7 * STEP + 40
    start = today - dt.timedelta(days=(today.weekday() + 1) % 7) - dt.timedelta(weeks=WEEKS - 1)
    first = start

    total = sum(n for d, n in counts.items() if first <= d <= today)
    cur, longest = streaks(counts, today)
    solved_today = bool(counts.get(today))
    font = "font-family=\"-apple-system,Segoe UI,Helvetica,Arial,sans-serif\""

    o = []
    if standalone:
        o.append('<?xml version="1.0" encoding="UTF-8"?>')
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
             f'aria-label="LeetCode solving activity">')
    plural = "" if total == 1 else "s"
    o.append(f'<text x="{LEFT}" y="20" {font} font-size="15" font-weight="600" fill="{P["strong"]}">'
             f'{total} solution{plural} in the last year</text>')
    sd = "day" if cur == 1 else "days"
    ld = "day" if longest == 1 else "days"
    o.append(f'<text x="{LEFT}" y="39" {font} font-size="12" fill="{P["text"]}">'
             f'Current streak: {cur} {sd}  ·  Longest streak: {longest} {ld}</text>')
    dot = P["levels"][2] if solved_today else P["empty"]
    label = "Solved today" if solved_today else "Not solved yet today"
    o.append(f'<circle cx="{W - 150}" cy="15" r="5" fill="{dot}" stroke="{P["text"]}" stroke-width="0.6"/>')
    o.append(f'<text x="{W - 140}" y="19" {font} font-size="12" fill="{P["text"]}">{label}</text>')

    # month labels
    last_m, last_x = None, -99
    for w in range(WEEKS):
        d = start + dt.timedelta(weeks=w)
        if d.month != last_m:
            x = LEFT + w * STEP
            if x - last_x >= 36:
                o.append(f'<text x="{x}" y="{TOP - 8}" {font} font-size="10" fill="{P["text"]}">{d.strftime("%b")}</text>')
                last_x = x
            last_m = d.month
    # weekday labels
    for r, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        o.append(f'<text x="0" y="{TOP + r * STEP + 9}" {font} font-size="10" fill="{P["text"]}">{name}</text>')

    # cells
    for w in range(WEEKS):
        for r in range(7):
            d = start + dt.timedelta(weeks=w, days=r)
            if d > today:
                continue
            n = counts.get(d, 0)
            fill = P["empty"] if n == 0 else P["levels"][min(n, 4) - 1]
            ring = f' stroke="{P["ring"]}" stroke-width="1.5"' if d == today else ""
            tip = f'{n} solution{"" if n == 1 else "s"} on {d.strftime("%b %d, %Y")}'
            o.append(f'<rect x="{LEFT + w * STEP}" y="{TOP + r * STEP}" width="{CELL}" height="{CELL}" rx="2" '
                     f'fill="{fill}"{ring}><title>{tip}</title></rect>')

    # legend
    ly = TOP + 7 * STEP + 18
    lx = W - 14 - 190
    o.append(f'<text x="{lx}" y="{ly + 9}" {font} font-size="10" fill="{P["text"]}">Less</text>')
    for i, c in enumerate([P["empty"]] + P["levels"]):
        o.append(f'<rect x="{lx + 30 + i * STEP}" y="{ly}" width="{CELL}" height="{CELL}" rx="2" fill="{c}"/>')
    o.append(f'<text x="{lx + 30 + 5 * STEP + 4}" y="{ly + 9}" {font} font-size="10" fill="{P["text"]}">More</text>')
    o.append("</svg>")
    return "".join(o)


# ------------------------------------------------------------- templating ----
def head(title, rel):
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)}</title>{THEME_BOOT}"
        f'<link rel="stylesheet" href="{rel}style.css"></head>'
    )


def topbar(rel):
    gh = (
        f'<a class="icon-btn" href="{esc(REPO_URL)}" target="_blank" rel="noopener" '
        'aria-label="Repository">Repo ↗</a>' if REPO_URL else ""
    )
    return (
        '<header class="topbar"><div class="wrap bar">'
        f'<a class="brand" href="{rel}index.html"><span class="logo">{{ }}</span>{esc(SITE_TITLE)}</a>'
        f'<div class="bar-actions">{gh}'
        '<button class="icon-btn" id="theme" aria-label="Toggle theme">◐</button>'
        "</div></div></header>"
    )


def footer():
    src = f' · <a href="{esc(REPO_URL)}">Source on GitHub</a>' if REPO_URL else ""
    return f'<footer class="wrap foot">Built automatically from the repository{src}</footer>'


def badge(diff):
    return f'<span class="badge {diff.lower()}">{esc(diff)}</span>'


def render_index(problems, activity_html=""):
    total = len(problems)
    counts = {d: sum(1 for p in problems if p["difficulty"] == d) for d in ("Easy", "Medium", "Hard")}

    cards = []
    for p in problems:
        chips = ""
        if p["time"]:
            chips += f'<span class="chip">⏱ {esc(p["time"])}</span>'
        if p["space"]:
            chips += f'<span class="chip">▤ {esc(p["space"])}</span>'
        n = len(p["solutions"])
        meta = " · ".join(p["langs"]) if p["langs"] else "No code yet"
        approaches = f"{n} solution{'s' if n != 1 else ''}"
        cards.append(
            f'<a class="card" href="p/{esc(p["folder"])}/index.html" '
            f'data-diff="{p["difficulty"].lower()}" '
            f'data-search="{esc((str(p["number"]) + " " + p["title"]).lower())}">'
            f'<div class="card-top"><span class="num">#{p["number"]}</span>{badge(p["difficulty"])}</div>'
            f'<h3>{esc(p["title"])}</h3>'
            f'<div class="chips">{chips}</div>'
            f'<div class="card-foot"><span>{esc(meta)}</span><span>{approaches}</span></div></a>'
        )
    empty = (
        '<p class="empty" id="empty-all">No problems yet. Solve one on LeetCode and it will show up here.</p>'
        if not problems else ""
    )

    return (
        head(SITE_TITLE, "")
        + "<body>" + topbar("")
        + '<main class="wrap">'
        f'<section class="hero"><h1>{esc(SITE_TITLE)}</h1><p>{esc(SITE_TAGLINE)}</p>'
        '<div class="stats">'
        f'<div class="stat"><b>{total}</b><span>Solved</span></div>'
        f'<div class="stat easy"><b>{counts["Easy"]}</b><span>Easy</span></div>'
        f'<div class="stat medium"><b>{counts["Medium"]}</b><span>Medium</span></div>'
        f'<div class="stat hard"><b>{counts["Hard"]}</b><span>Hard</span></div>'
        "</div></section>"
        + activity_html +
        '<section class="controls">'
        '<input id="q" type="search" placeholder="Search by name or number…" autocomplete="off">'
        '<div class="filters" id="filters">'
        '<button class="on" data-f="all">All</button>'
        '<button data-f="easy">Easy</button><button data-f="medium">Medium</button>'
        '<button data-f="hard">Hard</button></div></section>'
        f'<section class="grid" id="grid">{"".join(cards)}</section>'
        f'{empty}<p class="empty" id="empty" hidden>Nothing matches that search.</p>'
        "</main>" + footer()
        + '<script src="app.js"></script></body></html>'
    )


def render_problem(p, prev_p, next_p):
    chips = ""
    if p["time"]:
        chips += f'<span class="chip big">⏱ Time {esc(p["time"])}</span>'
    if p["space"]:
        chips += f'<span class="chip big">▤ Space {esc(p["space"])}</span>'

    sols = p["solutions"]
    if sols:
        multi_lang = len(p["langs"]) > 1
        tabs, panels = "", ""
        for i, s in enumerate(sols):
            label = f'{s["lang"]} · Approach {s["n"]}' if multi_lang else f'Approach {s["n"]}'
            on = " active" if i == 0 else ""
            tabs += f'<button class="tab{on}" data-tab="{i}">{esc(label)}</button>'
            panels += (
                f'<div class="panel{on}" data-panel="{i}">'
                f'<div class="panel-bar"><span>{esc(s["file"])}</span>'
                '<button class="copy">Copy</button></div>'
                f'{s["code_html"]}</div>'
            )
        solutions = (
            '<section class="block"><h2>Solutions</h2>'
            f'<div class="tabs">{tabs}</div>{panels}</section>'
        )
    else:
        solutions = '<section class="block"><h2>Solutions</h2><p class="empty">No code saved for this problem yet.</p></section>'

    src = f"{REPO_URL}/tree/main/{p['folder']}" if REPO_URL else ""
    src_btn = f'<a class="btn ghost" href="{esc(src)}" target="_blank" rel="noopener">View on GitHub ↗</a>' if src else ""

    pn = ""
    if prev_p:
        pn += f'<a class="pn" href="../{esc(prev_p["folder"])}/index.html"><small>← Previous</small>#{prev_p["number"]} {esc(prev_p["title"])}</a>'
    else:
        pn += "<span></span>"
    if next_p:
        pn += f'<a class="pn right" href="../{esc(next_p["folder"])}/index.html"><small>Next →</small>#{next_p["number"]} {esc(next_p["title"])}</a>'

    return (
        head(f'{p["number"]}. {p["title"]} · {SITE_TITLE}', "../../")
        + "<body>" + topbar("../../")
        + '<main class="wrap narrow">'
        '<a class="back" href="../../index.html">← All problems</a>'
        f'<header class="phead"><div class="card-top"><span class="num">#{p["number"]}</span>{badge(p["difficulty"])}</div>'
        f'<h1>{esc(p["title"])}</h1><div class="chips">{chips}</div>'
        f'<div class="actions"><a class="btn" href="{esc(p["link"])}" target="_blank" rel="noopener">Open on LeetCode ↗</a>{src_btn}</div></header>'
        f'<section class="block prose">{p["readme_html"]}</section>'
        f"{solutions}"
        f'<nav class="pager">{pn}</nav>'
        "</main>" + footer()
        + '<script src="../../app.js"></script></body></html>'
    )


# -------------------------------------------------------------- static ------
def build_css():
    dark = HtmlFormatter(style="github-dark").get_style_defs('[data-theme="dark"] .hl')
    light = HtmlFormatter(style="default").get_style_defs('[data-theme="light"] .hl')
    return STYLE + "\n" + dark + "\n" + light + "\n.hl{background:var(--code-bg)!important}\n"


STYLE = r"""
:root{--radius:14px;--font:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;--easy:#22c55e;--medium:#f59e0b;--hard:#ef4444}
[data-theme="dark"]{--bg:#0b0f17;--bg2:#111826;--card:#131b2b;--border:#222c40;--text:#e6ebf5;
--muted:#8b97b1;--accent:#7c9cff;--accent2:#b07cff;--code-bg:#0d1117;--shadow:0 8px 30px rgba(0,0,0,.35)}
[data-theme="light"]{--bg:#f5f7fb;--bg2:#eef1f8;--card:#fff;--border:#e1e6f0;--text:#18202f;
--muted:#667189;--accent:#4361ee;--accent2:#7b3fe4;--code-bg:#f6f8fa;--shadow:0 8px 30px rgba(30,40,80,.08)}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.65 var(--font);
background-image:radial-gradient(900px 400px at 85% -10%,color-mix(in srgb,var(--accent2) 18%,transparent),transparent),
radial-gradient(700px 380px at 0% 0%,color-mix(in srgb,var(--accent) 16%,transparent),transparent);background-repeat:no-repeat}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1100px;margin:0 auto;padding:0 20px}.narrow{max-width:820px}
.topbar{position:sticky;top:0;z-index:20;backdrop-filter:blur(12px);
background:color-mix(in srgb,var(--bg) 78%,transparent);border-bottom:1px solid var(--border)}
.bar{display:flex;align-items:center;justify-content:space-between;height:60px}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;color:var(--text)}.brand:hover{text-decoration:none}
.logo{display:grid;place-items:center;width:30px;height:30px;border-radius:9px;font:700 13px var(--mono);color:#fff;
background:linear-gradient(135deg,var(--accent),var(--accent2))}
.bar-actions{display:flex;gap:8px}
.icon-btn{border:1px solid var(--border);background:var(--card);color:var(--text);border-radius:10px;
padding:6px 12px;font:inherit;font-size:14px;cursor:pointer}.icon-btn:hover{border-color:var(--accent);text-decoration:none}
.hero{padding:56px 0 24px}
.hero h1{font-size:clamp(2rem,5vw,3.2rem);line-height:1.1;margin:0 0 10px;letter-spacing:-.02em;
background:linear-gradient(120deg,var(--text),var(--accent) 60%,var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
.hero p{margin:0;color:var(--muted);font-size:1.1rem;max-width:600px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:28px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow)}
.stat b{display:block;font-size:2rem;line-height:1.1}.stat span{color:var(--muted);font-size:.85rem;text-transform:uppercase;letter-spacing:.06em}
.stat.easy b{color:var(--easy)}.stat.medium b{color:var(--medium)}.stat.hard b{color:var(--hard)}
.controls{display:flex;gap:12px;flex-wrap:wrap;margin:28px 0 18px}
#q{flex:1;min-width:220px;padding:12px 16px;border-radius:12px;border:1px solid var(--border);background:var(--card);color:var(--text);font:inherit}
#q:focus{outline:2px solid var(--accent);border-color:transparent}
.filters{display:flex;gap:6px;flex-wrap:wrap}
.filters button{border:1px solid var(--border);background:var(--card);color:var(--muted);border-radius:999px;padding:8px 16px;font:inherit;font-size:14px;cursor:pointer}
.filters button.on{background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;border-color:transparent}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:16px;padding-bottom:40px}
.card{display:flex;flex-direction:column;gap:10px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
padding:18px;color:var(--text);transition:transform .15s,border-color .15s,box-shadow .15s}
.card:hover{transform:translateY(-3px);border-color:var(--accent);box-shadow:var(--shadow);text-decoration:none}
.card h3{margin:0;font-size:1.1rem;line-height:1.3}
.card-top{display:flex;align-items:center;justify-content:space-between;gap:10px}
.num{font:600 .9rem var(--mono);color:var(--muted)}
.card-foot{display:flex;justify-content:space-between;gap:8px;margin-top:auto;padding-top:10px;border-top:1px dashed var(--border);color:var(--muted);font-size:.8rem}
.badge{font-size:.72rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:3px 10px;border-radius:999px;
border:1px solid currentColor}
.badge.easy{color:var(--easy)}.badge.medium{color:var(--medium)}.badge.hard{color:var(--hard)}.badge.unknown{color:var(--muted)}
.chips{display:flex;gap:6px;flex-wrap:wrap;min-height:4px}
.chip{font:.78rem var(--mono);background:var(--bg2);border:1px solid var(--border);color:var(--muted);padding:3px 9px;border-radius:8px}
.chip.big{font-size:.9rem;padding:5px 12px;color:var(--text)}
.empty{color:var(--muted);text-align:center;padding:40px 0}
.back{display:inline-block;margin:28px 0 12px;color:var(--muted)}
.phead h1{font-size:clamp(1.8rem,4vw,2.6rem);line-height:1.15;margin:10px 0 14px;letter-spacing:-.02em}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
.btn{display:inline-block;padding:10px 18px;border-radius:10px;font-weight:600;font-size:.95rem;color:#fff;
background:linear-gradient(135deg,var(--accent),var(--accent2))}.btn:hover{text-decoration:none;filter:brightness(1.1)}
.btn.ghost{background:transparent;color:var(--text);border:1px solid var(--border)}.btn.ghost:hover{border-color:var(--accent)}
.block{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:24px 26px;margin:22px 0;box-shadow:var(--shadow)}
.block h2{margin:0 0 14px;font-size:1.3rem}
.prose h2{font-size:1.2rem;margin:1.6em 0 .5em;padding-bottom:.3em;border-bottom:1px solid var(--border)}
.prose h2:first-child{margin-top:0}.prose p,.prose li{color:var(--text)}.prose code{font:.9em var(--mono);background:var(--bg2);padding:2px 6px;border-radius:6px}
.prose pre code{background:none;padding:0}.prose table{border-collapse:collapse;width:100%;margin:1em 0}
.prose th,.prose td{border:1px solid var(--border);padding:8px 12px;text-align:left}.prose th{background:var(--bg2)}
.prose blockquote{margin:1em 0;padding:.2em 1em;border-left:3px solid var(--accent);color:var(--muted)}
.prose img{max-width:100%}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
.tab{border:1px solid var(--border);background:var(--bg2);color:var(--muted);border-radius:10px;padding:7px 14px;font:inherit;font-size:14px;cursor:pointer}
.tab.active{color:#fff;border-color:transparent;background:linear-gradient(135deg,var(--accent),var(--accent2))}
.js .panel{display:none}.js .panel.active{display:block}.panel{margin-bottom:14px}
.panel-bar{display:flex;justify-content:space-between;align-items:center;padding:8px 14px;background:var(--bg2);border:1px solid var(--border);
border-bottom:0;border-radius:12px 12px 0 0;font:.8rem var(--mono);color:var(--muted)}
.copy{border:1px solid var(--border);background:var(--card);color:var(--text);border-radius:8px;padding:3px 10px;font:inherit;font-size:12px;cursor:pointer}
.hl{overflow-x:auto;border:1px solid var(--border);border-radius:0 0 12px 12px;padding:14px 16px;margin:0}
.prose .hl{border-radius:12px;margin:1em 0}.hl pre{margin:0;font:.88rem/1.6 var(--mono)}
.pager{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:10px 0 40px}
.pn{display:block;padding:14px 16px;border:1px solid var(--border);border-radius:var(--radius);background:var(--card);color:var(--text)}
.pn small{display:block;color:var(--muted)}.pn.right{text-align:right}.pn:hover{border-color:var(--accent);text-decoration:none}
.activity{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 22px;margin-top:24px;box-shadow:var(--shadow)}
.activity h2{margin:0 0 6px;font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}
.hm-scroll{overflow-x:auto}.hm svg{display:block;width:100%;min-width:720px;height:auto}
[data-theme="dark"] .hm.light,[data-theme="light"] .hm.dark{display:none}
.foot{padding:30px 20px 50px;text-align:center;color:var(--muted);font-size:.85rem}
@media(max-width:640px){.stats{grid-template-columns:repeat(2,1fr)}.block{padding:18px}.pager{grid-template-columns:1fr}}
"""

APP_JS = r"""
(function(){
  var root=document.documentElement;
  var tb=document.getElementById('theme');
  if(tb)tb.onclick=function(){
    var n=root.dataset.theme==='dark'?'light':'dark';root.dataset.theme=n;
    try{localStorage.setItem('theme',n)}catch(e){}
  };

  var grid=document.getElementById('grid');
  if(grid){
    var q=document.getElementById('q'),cards=[].slice.call(grid.children),f='all';
    var empty=document.getElementById('empty');
    function apply(){
      var s=q.value.trim().toLowerCase(),shown=0;
      cards.forEach(function(c){
        var ok=(f==='all'||c.dataset.diff===f)&&(!s||c.dataset.search.indexOf(s)>-1);
        c.style.display=ok?'':'none';if(ok)shown++;
      });
      if(empty)empty.hidden=shown>0||cards.length===0;
    }
    q.addEventListener('input',apply);
    document.getElementById('filters').addEventListener('click',function(e){
      var b=e.target.closest('button');if(!b)return;
      [].forEach.call(this.children,function(x){x.classList.remove('on')});
      b.classList.add('on');f=b.dataset.f;apply();
    });
  }

  var tabs=document.querySelector('.tabs');
  if(tabs){
    tabs.addEventListener('click',function(e){
      var b=e.target.closest('.tab');if(!b)return;
      document.querySelectorAll('.tab,.panel').forEach(function(x){x.classList.remove('active')});
      b.classList.add('active');
      document.querySelector('.panel[data-panel="'+b.dataset.tab+'"]').classList.add('active');
    });
  }
  document.addEventListener('click',function(e){
    var b=e.target.closest('.copy');if(!b)return;
    var pre=b.closest('.panel').querySelector('pre');
    navigator.clipboard.writeText(pre.innerText).then(function(){
      b.textContent='Copied';setTimeout(function(){b.textContent='Copy'},1500);
    });
  });
})();
"""


# ------------------------------------------------------------------ main ----
def main():
    problems = []
    for d in sorted(ROOT.iterdir()):
        if d.is_dir() and not d.name.startswith((".", "_")) and d.name != "site":
            p = parse_problem(d)
            if p:
                problems.append(p)
    problems.sort(key=lambda p: p["number"])

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "p").mkdir(parents=True)
    (OUT / "style.css").write_text(build_css(), encoding="utf-8")
    (OUT / "app.js").write_text(APP_JS, encoding="utf-8")
    (OUT / ".nojekyll").write_text("")
    counts = solution_counts()
    today = dt.datetime.now(ZoneInfo(TIMEZONE)).date()
    for theme in ("light", "dark"):
        (OUT / f"activity-{theme}.svg").write_text(heatmap_svg(counts, today, theme), encoding="utf-8")
    activity_html = (
        '<section class="activity"><h2>Activity</h2><div class="hm-scroll">'
        f'<div class="hm light">{heatmap_svg(counts, today, "light", standalone=False)}</div>'
        f'<div class="hm dark">{heatmap_svg(counts, today, "dark", standalone=False)}</div>'
        "</div></section>"
    )
    (OUT / "index.html").write_text(render_index(problems, activity_html), encoding="utf-8")

    for i, p in enumerate(problems):
        prev_p = problems[i - 1] if i > 0 else None
        next_p = problems[i + 1] if i < len(problems) - 1 else None
        pdir = OUT / "p" / p["folder"]
        pdir.mkdir(parents=True)
        (pdir / "index.html").write_text(render_problem(p, prev_p, next_p), encoding="utf-8")

    print(f"Built {len(problems)} problem page(s) into {OUT}")


if __name__ == "__main__":
    main()
