#!/usr/bin/env python3
"""
Generates two SVG cards for a GitHub profile README, with no external services:
  assets/github-stats.svg    – repos, stars, contributions, commits, PRs, followers
  assets/top-languages.svg   – top languages across your own public repos

Runs in GitHub Actions (daily) using the built-in GITHUB_TOKEN, or locally.
Standard library only.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

USER = os.environ.get("STATS_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "sonu2002"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = os.environ.get("GITHUB_API", "https://api.github.com").rstrip("/")
OUT = Path(os.environ.get("STATS_OUT", "assets"))
TOP_N = 6
CARD_H = 180  # both cards share one size so they sit neatly side by side
# Languages that are not really "skills" (generated / data / markup noise)
IGNORE_LANGS = {"Procfile", "Batchfile", "Shell", "Makefile", "Dockerfile"}

LANG_COLORS = {
    "Jupyter Notebook": "#DA5B0B", "Python": "#3572A5", "Java": "#b07219", "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6", "HTML": "#e34c26", "CSS": "#663399", "SCSS": "#c6538c", "SQL": "#e38c00",
    "PLpgSQL": "#336790", "Scala": "#c22d40", "C++": "#f34b7d", "C": "#555555", "Kotlin": "#A97BFF",
    "Go": "#00ADD8", "R": "#198CE7", "PHP": "#4F5D95", "Vue": "#41b883", "Svelte": "#ff3e00",
}


def request(url, body=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-stats-generator"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def via_graphql():
    query = """
    query($login: String!) {
      user(login: $login) {
        name login
        followers { totalCount }
        pullRequests { totalCount }
        contributionsCollection {
          totalCommitContributions
          contributionCalendar { totalContributions }
        }
        repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
          totalCount
          nodes { stargazerCount languages(first: 20) { edges { size node { name color } } } }
        }
      }
    }"""
    res = request(API + "/graphql", {"query": query, "variables": {"login": USER}})
    if res.get("errors") or not res.get("data", {}).get("user"):
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
    return {
        "name": u["name"] or u["login"],
        "repos": u["repositories"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in u["repositories"]["nodes"]),
        "followers": u["followers"]["totalCount"],
        "prs": u["pullRequests"]["totalCount"],
        "contributions": u["contributionsCollection"]["contributionCalendar"]["totalContributions"],
        "commits": u["contributionsCollection"]["totalCommitContributions"],
        "langs": langs, "colors": colors, "counts": counts,
    }


def public_contributions():
    """Contributions in the last year from the public profile calendar (no token needed)."""
    import re
    try:
        req = urllib.request.Request(f"https://github.com/users/{USER}/contributions",
                                     headers={"User-Agent": "profile-stats-generator"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
        m = re.search(r"([\d,]+)\s+contributions?\s+in the last year", html)
        return int(m.group(1).replace(",", "")) if m else None
    except Exception:
        return None


def via_rest():
    user = request(f"{API}/users/{USER}")
    repos = [r for r in request(f"{API}/users/{USER}/repos?per_page=100&type=owner") if not r["fork"]]
    langs, counts = {}, {}
    for r in repos:
        for name, size in request(r["languages_url"]).items():
            langs[name] = langs.get(name, 0) + size
            counts[name] = counts.get(name, 0) + 1
    return {
        "name": user.get("name") or USER, "repos": len(repos),
        "stars": sum(r["stargazers_count"] for r in repos), "followers": user["followers"],
        "prs": None, "contributions": public_contributions(), "commits": None, "langs": langs, "colors": {}, "counts": counts,
    }


STYLE = """
<style>
  .bg { fill: #ffffff; stroke: #d0d7de; }
  .title { font: 600 17px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #4f46e5; }
  .label { font: 400 13px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #57606a; }
  .value { font: 700 15px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #1f2328; }
  .small { font: 400 11px 'Segoe UI', Ubuntu, Helvetica, Arial, sans-serif; fill: #8c959f; }
  .icon { fill: #4f46e5; }
  .track { fill: #eaeef2; }
  @media (prefers-color-scheme: dark) {
    .bg { fill: #0d1117; stroke: #30363d; }
    .title { fill: #a5b4fc; }
    .label { fill: #9198a1; }
    .value { fill: #f0f6fc; }
    .small { fill: #6e7681; }
    .icon { fill: #a5b4fc; }
    .track { fill: #21262d; }
  }
</style>"""

ICONS = {  # 16x16 octicon-style paths
    "repo": "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z",
    "star": "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z",
    "activity": "M6 2c.306 0 .582.187.696.471L10 10.731l1.304-3.26A.751.751 0 0 1 12 7h3.25a.75.75 0 0 1 0 1.5h-2.742l-1.812 4.528a.751.751 0 0 1-1.392 0L6 4.77 4.696 8.03A.75.75 0 0 1 4 8.5H.75a.75.75 0 0 1 0-1.5h2.742l1.812-4.529A.751.751 0 0 1 6 2Z",
    "commit": "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z",
    "pr": "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354Z",
    "people": "M2 5.5a3.5 3.5 0 1 1 5.898 2.549 5.508 5.508 0 0 1 3.034 4.084.75.75 0 1 1-1.482.235 4 4 0 0 0-7.9 0 .75.75 0 0 1-1.482-.236A5.507 5.507 0 0 1 3.102 8.05 3.493 3.493 0 0 1 2 5.5ZM11 4a3.001 3.001 0 0 1 2.22 5.018 5.01 5.01 0 0 1 2.56 3.012.749.749 0 0 1-.885.954.752.752 0 0 1-.549-.514 3.507 3.507 0 0 0-2.522-2.372.75.75 0 0 1-.574-.73v-.352a.75.75 0 0 1 .416-.672A1.5 1.5 0 0 0 11 5.5.75.75 0 0 1 11 4Zm-5.5-.5a2 2 0 1 0-.001 3.999A2 2 0 0 0 5.5 3.5Z",
}


def fmt(n):
    if n is None:
        return "–"
    return f"{n/1000:.1f}k" if n >= 10000 else f"{n:,}"


def stats_card(s):
    rows = [("repo", "Public repositories", s["repos"]), ("activity", "Contributions (last year)", s["contributions"]),
            ("commit", "Commits (last year)", s["commits"]), ("star", "Stars earned", s["stars"]),
            ("pr", "Pull requests", s["prs"]), ("people", "Followers", s["followers"])]
    # hide unknown values, and hide stars/PRs/followers while they are still 0
    rows = [r for r in rows if r[2] is not None and not (r[2] == 0 and r[0] in ("star", "pr", "people"))]
    w, h = 420, CARD_H
    top_y = 60 + max(0, (h - 60 - 30 * len(rows)) // 2) + 18
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="GitHub stats">',
             STYLE, f'<rect class="bg" x="0.5" y="0.5" rx="10" width="{w-1}" height="{h-1}"/>',
             f'<text class="title" x="24" y="36">{escape(s["name"])}\'s GitHub stats</text>']
    for i, (icon, label, value) in enumerate(rows):
        y = top_y + 30 * i
        parts.append(f'<g transform="translate(24,{y-12})"><path class="icon" d="{ICONS[icon]}"/></g>')
        parts.append(f'<text class="label" x="50" y="{y}">{label}</text>')
        parts.append(f'<text class="value" x="{w-24}" y="{y}" text-anchor="end">{fmt(value)}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def langs_card(s):
    # score = sqrt(bytes) x sqrt(number of repos), so one huge file can't dominate
    langs = {k: (v ** 0.5) * (s["counts"].get(k, 1) ** 0.5) for k, v in s["langs"].items() if k not in IGNORE_LANGS}
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
    w, h = 420, CARD_H
    bar_w = w - 48
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Top languages">',
             STYLE, f'<rect class="bg" x="0.5" y="0.5" rx="10" width="{w-1}" height="{h-1}"/>',
             '<text class="title" x="24" y="36">Most used languages</text>',
             f'<clipPath id="bar"><rect x="24" y="52" width="{bar_w}" height="10" rx="5"/></clipPath>',
             f'<rect class="track" x="24" y="52" width="{bar_w}" height="10" rx="5"/>', '<g clip-path="url(#bar)">']
    top_total = sum(v for _, v in top) or 1
    x = 24.0
    for name, size in top:
        seg = bar_w * size / top_total
        color = s["colors"].get(name) or LANG_COLORS.get(name, "#8b949e")
        parts.append(f'<rect x="{x:.2f}" y="52" width="{seg + 0.5:.2f}" height="10" fill="{color}"/>')
        x += seg
    parts.append("</g>")
    for i, (name, size) in enumerate(top):
        col, row = i % 2, i // 2
        cx, cy = 24 + col * (bar_w / 2), 100 + row * 28
        color = s["colors"].get(name) or LANG_COLORS.get(name, "#8b949e")
        parts.append(f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{color}"/>')
        parts.append(f'<text class="label" x="{cx + 16}" y="{cy}">{escape(name)} <tspan class="small">{100 * size / total:.1f}%</tspan></text>')
    parts.append("</svg>")
    return "\n".join(parts)


def generate():
    """Builds both SVG files; returns the stats dict."""
    stats = None
    if TOKEN:
        try:
            stats = via_graphql()
        except Exception as exc:  # GraphQL unavailable -> REST fallback
            print(f"GraphQL failed ({exc}); using REST", file=sys.stderr)
    if stats is None:
        stats = via_rest()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "github-stats.svg").write_text(stats_card(stats), encoding="utf-8")
    (OUT / "top-languages.svg").write_text(langs_card(stats), encoding="utf-8")
    return stats


def main():
    stats = generate()
    print(json.dumps({k: v for k, v in stats.items() if k not in ("langs", "colors")}))
    print("languages by repo count:", sorted(stats["counts"].items(), key=lambda kv: kv[1], reverse=True)[:8])


if __name__ == "__main__":
    main()
