#!/usr/bin/env python3
"""
Generates the SVG cards for a GitHub profile README, with no external stats services:

  assets/header.svg          animated typing header
  assets/github-stats.svg    repos, contributions, commits, stars, PRs, followers
  assets/top-languages.svg   most used languages across your own public repos
  assets/streak.svg          total contributions, current streak, longest streak
  assets/contributions.svg   green contribution heatmap for the last year
  assets/leetcode.svg        LeetCode solved problems (easy / medium / hard)

Runs daily in GitHub Actions with the built-in GITHUB_TOKEN, or locally. Standard library only.
If a source is temporarily unavailable, the previous card is kept instead of breaking.
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

USER = os.environ.get("STATS_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "sonu2002"
LEETCODE_USER = os.environ.get("LEETCODE_USER", "sonuphogat0015")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = os.environ.get("GITHUB_API", "https://api.github.com").rstrip("/")
OUT = Path(os.environ.get("STATS_OUT", "assets"))

# Lines shown in the animated header; edit freely.
HEADER_LINES = [
    "Data Science & AI student in Berlin",
    "Ex-MIS Associate · 3+ years in reporting & BI",
    "Python · SQL · Power BI · Excel · Java",
    "1,185+ LeetCode problems solved",
    "Open to Werkstudent & entry-level roles",
]

TOP_N = 6
CARD_W, CARD_H = 420, 180
IGNORE_LANGS = {"Procfile", "Batchfile", "Shell", "Makefile", "Dockerfile"}
LANG_COLORS = {
    "Jupyter Notebook": "#DA5B0B", "Python": "#3572A5", "Java": "#b07219", "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6", "HTML": "#e34c26", "CSS": "#663399", "SCSS": "#c6538c", "SQL": "#e38c00",
    "Scala": "#c22d40", "C++": "#f34b7d", "C": "#555555", "Kotlin": "#A97BFF", "Go": "#00ADD8", "R": "#198CE7",
}
FONT = "'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif"


# ------------------------------------------------------------------ data
def request(url, body=None, headers=None, auth=True):
    h = {"Accept": "application/vnd.github+json", "User-Agent": "profile-stats-generator"}
    if auth and TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def github_graphql():
    query = """
    query($login: String!) {
      user(login: $login) {
        name login
        followers { totalCount }
        pullRequests { totalCount }
        contributionsCollection {
          totalCommitContributions
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount contributionLevel } }
          }
        }
        repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
          totalCount
          nodes { stargazerCount languages(first: 20) { edges { size node { name color } } } }
        }
      }
    }"""
    res = request(API + "/graphql", {"query": query, "variables": {"login": USER}})
    if res.get("errors") or not (res.get("data") or {}).get("user"):
        raise RuntimeError(res.get("errors"))
    u = res["data"]["user"]
    langs, colors, counts = {}, {}, {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            name = e["node"]["name"]
            langs[name] = langs.get(name, 0) + e["size"]
            counts[name] = counts.get(name, 0) + 1
            if e["node"]["color"]:
                colors[name] = e["node"]["color"]
    level_map = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
    cal = u["contributionsCollection"]["contributionCalendar"]
    days = [(d["date"], d["contributionCount"], level_map.get(d["contributionLevel"], 0))
            for w in cal["weeks"] for d in w["contributionDays"]]
    return {
        "name": u["name"] or u["login"], "repos": u["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in u["repositories"]["nodes"]),
        "followers": u["followers"]["totalCount"], "prs": u["pullRequests"]["totalCount"],
        "contributions": cal["totalContributions"],
        "commits": u["contributionsCollection"]["totalCommitContributions"],
        "langs": langs, "colors": colors, "counts": counts, "days": days,
    }


def public_calendar():
    """Contribution calendar from the public profile page (no token needed)."""
    req = urllib.request.Request(f"https://github.com/users/{USER}/contributions",
                                 headers={"User-Agent": "Mozilla/5.0 profile-stats-generator"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    cells = re.findall(r'data-date="([\d-]+)"\s+id="([^"]+)"\s+data-level="(\d)"', html)
    tips = dict(re.findall(r'for="([^"]+)"[^>]*>([^<]*)</tool-tip>', html))
    days = []
    for date, cid, level in cells:
        m = re.match(r"(\d[\d,]*) contribution", tips.get(cid, ""))
        days.append((date, int(m.group(1).replace(",", "")) if m else 0, int(level)))
    days.sort()
    return days


def github_rest():
    user = request(f"{API}/users/{USER}")
    repos = [r for r in request(f"{API}/users/{USER}/repos?per_page=100&type=owner") if not r["fork"]]
    langs, counts = {}, {}
    for r in repos:
        for name, size in request(r["languages_url"]).items():
            langs[name] = langs.get(name, 0) + size
            counts[name] = counts.get(name, 0) + 1
    try:
        days = public_calendar()
    except Exception:
        days = []
    return {
        "name": user.get("name") or USER, "repos": len(repos),
        "stars": sum(r["stargazers_count"] for r in repos), "followers": user["followers"],
        "prs": None, "contributions": sum(c for _, c, _ in days) if days else None, "commits": None,
        "langs": langs, "colors": {}, "counts": counts, "days": days,
    }


def leetcode():
    query = """query($u: String!) {
      allQuestionsCount { difficulty count }
      matchedUser(username: $u) {
        username
        profile { ranking }
        submitStatsGlobal { acSubmissionNum { difficulty count } }
      }
    }"""
    res = request("https://leetcode.com/graphql", {"query": query, "variables": {"u": LEETCODE_USER}},
                  headers={"Content-Type": "application/json", "Referer": "https://leetcode.com",
                           "User-Agent": "Mozilla/5.0"}, auth=False)
    mu = (res.get("data") or {}).get("matchedUser")
    if not mu:
        raise RuntimeError("LeetCode user not found")
    solved = {x["difficulty"]: x["count"] for x in mu["submitStatsGlobal"]["acSubmissionNum"]}
    total = {x["difficulty"]: x["count"] for x in res["data"]["allQuestionsCount"]}
    return {"user": mu["username"], "ranking": mu["profile"]["ranking"], "solved": solved, "total": total}


def streaks(days):
    """days: sorted list of (date, count, level). Returns dict with streak info."""
    if not days:
        return None
    parsed = [(dt.date.fromisoformat(d), c) for d, c, _ in days]
    longest = cur = 0
    best_start = best_end = run_start = None
    for day, c in parsed:
        if c > 0:
            cur += 1
            run_start = run_start if cur > 1 else day
            if cur > longest:
                longest, best_start, best_end = cur, run_start, day
        else:
            cur = 0
    # current streak: count back from the last day (today may still be 0)
    current, i = 0, len(parsed) - 1
    if parsed[i][1] == 0:
        i -= 1
    end = parsed[i][0] if i >= 0 else None
    while i >= 0 and parsed[i][1] > 0:
        current += 1
        i -= 1
    start = parsed[i + 1][0] if current else None
    return {"total": sum(c for _, c in parsed), "first": parsed[0][0], "last": parsed[-1][0],
            "current": current, "current_start": start, "current_end": end if current else None,
            "longest": longest, "longest_start": best_start, "longest_end": best_end,
            "active": sum(1 for _, c in parsed if c > 0)}


# ------------------------------------------------------------------ drawing
STYLE = f"""
<style>
  .bg {{ fill: #ffffff; stroke: #d0d7de; }}
  .title {{ font: 600 17px {FONT}; fill: #4f46e5; }}
  .label {{ font: 400 13px {FONT}; fill: #57606a; }}
  .value {{ font: 700 15px {FONT}; fill: #1f2328; }}
  .big {{ font: 700 28px {FONT}; fill: #1f2328; }}
  .small {{ font: 400 11px {FONT}; fill: #8c959f; }}
  .accent {{ fill: #2da44e; }}
  .icon {{ fill: #4f46e5; }}
  .track {{ fill: #eaeef2; }}
  .ring-track {{ stroke: #eaeef2; }}
  .divider {{ stroke: #d0d7de; }}
  .l0 {{ fill: #ebedf0; }} .l1 {{ fill: #9be9a8; }} .l2 {{ fill: #40c463; }} .l3 {{ fill: #30a14e; }} .l4 {{ fill: #216e39; }}
  @media (prefers-color-scheme: dark) {{
    .bg {{ fill: #0d1117; stroke: #30363d; }}
    .title {{ fill: #a5b4fc; }}
    .label {{ fill: #9198a1; }}
    .value, .big {{ fill: #f0f6fc; }}
    .small {{ fill: #6e7681; }}
    .accent {{ fill: #3fb950; }}
    .icon {{ fill: #a5b4fc; }}
    .track {{ fill: #21262d; }}
    .ring-track {{ stroke: #21262d; }}
    .divider {{ stroke: #30363d; }}
    .l0 {{ fill: #161b22; }} .l1 {{ fill: #0e4429; }} .l2 {{ fill: #006d32; }} .l3 {{ fill: #26a641; }} .l4 {{ fill: #39d353; }}
  }}
</style>"""

ICONS = {
    "repo": "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z",
    "star": "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z",
    "activity": "M6 2c.306 0 .582.187.696.471L10 10.731l1.304-3.26A.751.751 0 0 1 12 7h3.25a.75.75 0 0 1 0 1.5h-2.742l-1.812 4.528a.751.751 0 0 1-1.392 0L6 4.77 4.696 8.03A.75.75 0 0 1 4 8.5H.75a.75.75 0 0 1 0-1.5h2.742l1.812-4.529A.751.751 0 0 1 6 2Z",
    "commit": "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z",
    "pr": "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354Z",
    "people": "M2 5.5a3.5 3.5 0 1 1 5.898 2.549 5.508 5.508 0 0 1 3.034 4.084.75.75 0 1 1-1.482.235 4 4 0 0 0-7.9 0 .75.75 0 0 1-1.482-.236A5.507 5.507 0 0 1 3.102 8.05 3.493 3.493 0 0 1 2 5.5ZM11 4a3.001 3.001 0 0 1 2.22 5.018 5.01 5.01 0 0 1 2.56 3.012.749.749 0 0 1-.885.954.752.752 0 0 1-.549-.514 3.507 3.507 0 0 0-2.522-2.372.75.75 0 0 1-.574-.73v-.352a.75.75 0 0 1 .416-.672A1.5 1.5 0 0 0 11 5.5.75.75 0 0 1 11 4Zm-5.5-.5a2 2 0 1 0-.001 3.999A2 2 0 0 0 5.5 3.5Z",
    "calendar": "M4.75 0a.75.75 0 0 1 .75.75V2h5V.75a.75.75 0 0 1 1.5 0V2h1.25c.966 0 1.75.784 1.75 1.75v10.5A1.75 1.75 0 0 1 13.25 16H2.75A1.75 1.75 0 0 1 1 14.25V3.75C1 2.784 1.784 2 2.75 2H4V.75A.75.75 0 0 1 4.75 0ZM2.5 7.5v6.75c0 .138.112.25.25.25h10.5a.25.25 0 0 0 .25-.25V7.5Zm10.75-4H2.75a.25.25 0 0 0-.25.25V6h11V3.75a.25.25 0 0 0-.25-.25Z",
}


def svg_open(w, h, label):
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label)}">',
            STYLE, f'<rect class="bg" x="0.5" y="0.5" rx="10" width="{w-1}" height="{h-1}"/>']


def fmt(n):
    if n is None:
        return "–"
    return f"{n/1000:.1f}k" if n >= 10000 else f"{n:,}"


def short_date(d):
    return d.strftime("%b %-d") if os.name != "nt" else d.strftime("%b %d").replace(" 0", " ")


def stats_card(s):
    rows = [("repo", "Public repositories", s["repos"]), ("activity", "Contributions (last year)", s["contributions"]),
            ("commit", "Commits (last year)", s["commits"]), ("calendar", "Active days (last year)", s.get("active")),
            ("star", "Stars earned", s["stars"]),
            ("pr", "Pull requests", s["prs"]), ("people", "Followers", s["followers"])]
    rows = [r for r in rows if r[2] is not None and not (r[2] == 0 and r[0] in ("star", "pr", "people"))][:4]
    top_y = 60 + max(0, (CARD_H - 60 - 30 * len(rows)) // 2) + 18
    parts = svg_open(CARD_W, CARD_H, "GitHub stats")
    parts.append(f'<text class="title" x="24" y="36">{escape(s["name"])}\'s GitHub stats</text>')
    for i, (icon, label, value) in enumerate(rows):
        y = top_y + 30 * i
        parts.append(f'<g transform="translate(24,{y-12})"><path class="icon" d="{ICONS[icon]}"/></g>')
        parts.append(f'<text class="label" x="50" y="{y}">{label}</text>')
        parts.append(f'<text class="value" x="{CARD_W-24}" y="{y}" text-anchor="end">{fmt(value)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def langs_card(s):
    langs = {k: (v ** 0.5) * (s["counts"].get(k, 1) ** 0.5) for k, v in s["langs"].items() if k not in IGNORE_LANGS}
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
    bar_w = CARD_W - 48
    parts = svg_open(CARD_W, CARD_H, "Most used languages")
    parts += ['<text class="title" x="24" y="36">Most used languages</text>',
              f'<clipPath id="bar"><rect x="24" y="52" width="{bar_w}" height="10" rx="5"/></clipPath>',
              f'<rect class="track" x="24" y="52" width="{bar_w}" height="10" rx="5"/>', '<g clip-path="url(#bar)">']
    top_total = sum(v for _, v in top) or 1
    x = 24.0
    for name, size in top:
        seg = bar_w * size / top_total
        parts.append(f'<rect x="{x:.2f}" y="52" width="{seg + 0.5:.2f}" height="10" fill="{s["colors"].get(name) or LANG_COLORS.get(name, "#8b949e")}"/>')
        x += seg
    parts.append("</g>")
    for i, (name, size) in enumerate(top):
        cx, cy = 24 + (i % 2) * (bar_w / 2), 100 + (i // 2) * 28
        color = s["colors"].get(name) or LANG_COLORS.get(name, "#8b949e")
        parts.append(f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{color}"/>')
        parts.append(f'<text class="label" x="{cx + 16}" y="{cy}">{escape(name)} <tspan class="small">{100 * size / total:.1f}%</tspan></text>')
    parts.append("</svg>")
    return "\n".join(parts)


def streak_card(st):
    parts = svg_open(CARD_W, CARD_H, "Contribution streak")
    parts.append('<text class="title" x="24" y="36">Contribution streak</text>')
    cols = [CARD_W / 6, CARD_W / 2, CARD_W * 5 / 6]
    for x in (CARD_W / 3, CARD_W * 2 / 3):
        parts.append(f'<line class="divider" x1="{x:.0f}" y1="62" x2="{x:.0f}" y2="152" stroke-width="1"/>')

    def rng(a, b):
        return f"{short_date(a)} – {short_date(b)}" if a and b else "–"
    # total
    parts.append(f'<text class="big" x="{cols[0]:.0f}" y="104" text-anchor="middle">{fmt(st["total"])}</text>')
    parts.append(f'<text class="label" x="{cols[0]:.0f}" y="128" text-anchor="middle">Contributions</text>')
    parts.append(f'<text class="small" x="{cols[0]:.0f}" y="146" text-anchor="middle">last 12 months</text>')
    # current streak with green ring
    cx, cy, r = cols[1], 96, 27
    parts.append(f'<circle class="ring-track" cx="{cx:.0f}" cy="{cy}" r="{r}" fill="none" stroke-width="5"/>')
    parts.append(f'<circle cx="{cx:.0f}" cy="{cy}" r="{r}" fill="none" stroke="#2da44e" stroke-width="5" stroke-linecap="round" '
                 f'stroke-dasharray="{2*3.1416*r*min(1, st["current"]/max(st["longest"],1)):.1f} 999" transform="rotate(-90 {cx:.0f} {cy})"/>')
    parts.append(f'<text class="big" x="{cx:.0f}" y="{cy+9}" text-anchor="middle">{st["current"]}</text>')
    parts.append(f'<text class="label" x="{cx:.0f}" y="146" text-anchor="middle" style="font-weight:600">Current streak</text>')
    # longest
    parts.append(f'<text class="big" x="{cols[2]:.0f}" y="104" text-anchor="middle">{st["longest"]}</text>')
    parts.append(f'<text class="label" x="{cols[2]:.0f}" y="128" text-anchor="middle">Longest streak</text>')
    parts.append(f'<text class="small" x="{cols[2]:.0f}" y="146" text-anchor="middle">{rng(st["longest_start"], st["longest_end"])}</text>')
    parts.append(f'<text class="small" x="{CARD_W-24}" y="36" text-anchor="end">{st["active"]} active days</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def heatmap_card(days, total):
    cell, gap = 11, 3
    step = cell + gap
    first = dt.date.fromisoformat(days[0][0])
    offset = (first.weekday() + 1) % 7  # GitHub weeks start on Sunday
    weeks = (offset + len(days) + 6) // 7
    left, top = 44, 62
    w = left + weeks * step + 20
    h = top + 7 * step + 40
    parts = svg_open(w, h, "Contribution graph")
    parts.append(f'<text class="title" x="24" y="34">{total:,} contributions in the last year</text>')
    for i, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        parts.append(f'<text class="small" x="{left-8}" y="{top + i*step + 9}" text-anchor="end">{label}</text>')
    last_month = None
    for idx, (date, count, level) in enumerate(days):
        pos = idx + offset
        col, row = pos // 7, pos % 7
        x, y = left + col * step, top + row * step
        d = dt.date.fromisoformat(date)
        if row == 0 or idx == 0:
            if d.month != last_month and col < weeks - 1:
                parts.append(f'<text class="small" x="{x}" y="{top-8}">{d.strftime("%b")}</text>')
                last_month = d.month
        parts.append(f'<rect class="l{level}" x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2"><title>{count} on {date}</title></rect>')
    ly = top + 7 * step + 16
    lx = w - 20 - 5 * step - 34
    parts.append(f'<text class="small" x="{lx - 6}" y="{ly + 9}" text-anchor="end">Less</text>')
    for i in range(5):
        parts.append(f'<rect class="l{i}" x="{lx + i*step}" y="{ly}" width="{cell}" height="{cell}" rx="2"/>')
    parts.append(f'<text class="small" x="{lx + 5*step + 4}" y="{ly + 9}">More</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def leetcode_card(lc):
    parts = svg_open(CARD_W, CARD_H, "LeetCode stats")
    parts.append('<text class="title" x="24" y="36">LeetCode</text>')
    if lc.get("ranking"):
        parts.append(f'<text class="small" x="{CARD_W-24}" y="36" text-anchor="end">Rank {lc["ranking"]:,} · {escape(lc["user"])}</text>')
    solved, total = lc["solved"].get("All", 0), lc["total"].get("All", 0) or 1
    cx, cy, r = 84, 108, 46
    circ = 2 * 3.1416 * r
    parts.append(f'<circle class="ring-track" cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke-width="7"/>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#ffa116" stroke-width="7" stroke-linecap="round" '
                 f'stroke-dasharray="{circ*solved/total:.1f} {circ:.1f}" transform="rotate(-90 {cx} {cy})"/>')
    parts.append(f'<text class="big" x="{cx}" y="{cy+6}" text-anchor="middle">{solved:,}</text>')
    parts.append(f'<text class="small" x="{cx}" y="{cy+24}" text-anchor="middle">solved</text>')
    bx, bw = 170, CARD_W - 170 - 24
    for i, (diff, color) in enumerate((("Easy", "#00b8a3"), ("Medium", "#ffc01e"), ("Hard", "#ef4743"))):
        y = 72 + i * 36
        s, t = lc["solved"].get(diff, 0), lc["total"].get(diff, 0) or 1
        parts.append(f'<text class="label" x="{bx}" y="{y}" style="fill:{color};font-weight:600">{diff}</text>')
        parts.append(f'<text class="label" x="{bx+bw}" y="{y}" text-anchor="end"><tspan class="value" style="font-size:13px">{s:,}</tspan> / {t:,}</text>')
        parts.append(f'<rect class="track" x="{bx}" y="{y+7}" width="{bw}" height="7" rx="3.5"/>')
        parts.append(f'<rect x="{bx}" y="{y+7}" width="{max(4, bw*s/t):.1f}" height="7" rx="3.5" fill="{color}"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def header_svg(lines=HEADER_LINES):
    """Animated 'typing' header: each line types out, stays, then the next one appears."""
    w, h, size = 820, 56, 24
    char_w = size * 0.6  # monospace
    per = 4.0
    total = per * len(lines)
    css = [f".t {{ font: 600 {size}px 'Fira Code', 'Cascadia Code', Consolas, 'Courier New', monospace; fill: #4f46e5; }}",
           ".cover { fill: #ffffff; }",
           "@media (prefers-color-scheme: dark) { .t { fill: #a5b4fc; } .cover { fill: #0d1117; } }"]
    body = []
    for i, text in enumerate(lines):
        tw = len(text) * char_w
        x0 = (w - tw) / 2
        show_end = 100 * (per - 0.25) / total
        type_end = 100 * 1.6 / total
        css.append(f"@keyframes s{i} {{ 0% {{ opacity: 1 }} {show_end:.2f}% {{ opacity: 1 }} {show_end + 0.01:.2f}% {{ opacity: 0 }} 100% {{ opacity: 0 }} }}")
        css.append(f"@keyframes c{i} {{ 0% {{ transform: translateX(0); animation-timing-function: steps({len(text)}, end) }} "
                   f"{type_end:.2f}% {{ transform: translateX({tw + char_w:.1f}px) }} 100% {{ transform: translateX({tw + char_w:.1f}px) }} }}")
        css.append(f"#g{i} {{ opacity: 0; animation: s{i} {total}s linear {i*per}s infinite; }}")
        css.append(f"#c{i} {{ animation: c{i} {total}s linear {i*per}s infinite; }}")
        body.append(f'<g id="g{i}"><text class="t" x="{x0:.1f}" y="{h/2 + size*0.35:.1f}">{escape(text)}</text>'
                    f'<rect id="c{i}" class="cover" x="{x0 - 2:.1f}" y="0" width="{tw + char_w + 4:.1f}" height="{h}"/></g>')
    # first line visible immediately for viewers without animation
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{escape(" | ".join(lines))}"><style>{" ".join(css)}</style>{"".join(body)}</svg>')


# ------------------------------------------------------------------ main
def write(name, content):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(content, encoding="utf-8")


def generate():
    """Builds all cards. Returns a summary dict. Keeps old files when a source fails."""
    summary = {}
    stats = None
    if TOKEN:
        try:
            stats = github_graphql()
        except Exception as exc:
            print(f"GraphQL failed ({exc}); using REST", file=sys.stderr)
    if stats is None:
        stats = github_rest()
    st = streaks(stats["days"])
    stats["active"] = st["active"] if st else None
    write("header.svg", header_svg())
    write("github-stats.svg", stats_card(stats))
    write("top-languages.svg", langs_card(stats))
    summary.update(repos=stats["repos"], contributions=stats["contributions"], commits=stats["commits"])
    if st:
        write("streak.svg", streak_card(st))
        write("contributions.svg", heatmap_card(stats["days"], st["total"]))
        summary.update(current_streak=st["current"], longest_streak=st["longest"], active_days=st["active"])
    else:
        print("No contribution calendar available; keeping old streak/heatmap", file=sys.stderr)
    try:
        lc = leetcode()
        write("leetcode.svg", leetcode_card(lc))
        summary.update(leetcode_solved=lc["solved"].get("All"))
    except Exception as exc:
        print(f"LeetCode unavailable ({exc}); keeping old card", file=sys.stderr)
    return summary


if __name__ == "__main__":
    print(json.dumps(generate(), default=str))
