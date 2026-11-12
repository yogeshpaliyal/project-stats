#!/usr/bin/env python3
"""Draw charts (light + dark SVGs) and write README.md from data/*.csv."""
import csv
import datetime as dt
import os
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, FuncFormatter

# render.py <data dir>: writes README.md and charts/ into the data dir (the `data` branch).
ROOT = sys.argv[1] if len(sys.argv) > 1 else "data"
DATA, CHARTS = ROOT, os.path.join(ROOT, "charts")

THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", grid="#e6e5e1",
                  series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"],
                  other="#a3a29c", bar="#2a78d6"),
    "dark": dict(surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", grid="#383835",
                 series=["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9"],
                 other="#6f6e69", bar="#3987e5"),
}
MAX_SERIES = 7  # more folds into "Other"


def rows(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def short(repo):
    return repo.split("/", 1)[1]


def fmt(n):
    n = int(n)
    return f"{n/1000:.1f}k".replace(".0k", "k") if n >= 10000 else f"{n:,}"


def style(ax, t, title):
    ax.set_facecolor(t["surface"])
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(t["grid"])
    ax.tick_params(colors=t["ink2"], labelsize=9, length=0)
    ax.grid(axis="y", color=t["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", color=t["ink"], fontsize=12, fontweight="bold", pad=12)


def save(fig, name, mode):
    os.makedirs(CHARTS, exist_ok=True)
    fig.savefig(os.path.join(CHARTS, f"{name}-{mode}.svg"), facecolor=fig.get_facecolor(),
                bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)


def picture(name, alt):
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="charts/{name}-dark.svg">'
            f'<img alt="{alt}" src="charts/{name}-light.svg" width="100%"></picture>')


def main():
    plt.rcParams["font.family"] = "DejaVu Sans"
    plt.rcParams["svg.fonttype"] = "none"
    daily = rows("daily.csv")
    traffic = rows("traffic.csv")
    meta = {r["repo"]: r for r in rows("repos.csv")}
    if not daily:
        print("No data yet")
        return

    # downloads[repo][date] = cumulative total
    dl = defaultdict(dict)
    stars = {}
    for r in daily:
        dl[r["repo"]][r["date"]] = int(r["downloads"])
    last_date = max(r["date"] for r in daily)
    for r in daily:
        if r["date"] == last_date:
            stars[r["repo"]] = int(r["stars"])
    totals = {repo: max(v.values()) for repo, v in dl.items()}
    with_dl = sorted([r for r in totals if totals[r] > 0], key=lambda r: -totals[r])

    def at(repo, day):
        """Cumulative downloads on or before day (0 before the first record)."""
        best = 0
        for d, n in dl[repo].items():
            if d <= day:
                best = max(best, n)
        return best

    today = dt.date.fromisoformat(last_date)
    week_ago = (today - dt.timedelta(days=7)).isoformat()
    first_seen = {repo: min(v) for repo, v in dl.items()}

    def last7(repo):
        if first_seen[repo] > week_ago:
            return None  # not tracked long enough
        return totals[repo] - at(repo, week_ago)

    dates = sorted({r["date"] for r in daily})
    top = with_dl[:MAX_SERIES]
    rest = with_dl[MAX_SERIES:]

    views14 = defaultdict(int)
    start14 = (today - dt.timedelta(days=13)).isoformat()
    for r in traffic:
        if r["date"] >= start14:
            views14[r["repo"]] += int(r["views"])

    charts = []
    for mode, t in THEMES.items():
        # 1. Cumulative downloads over time, one line per project.
        if len(dates) >= 2 and top:
            fig, ax = plt.subplots(figsize=(9, 4.2), facecolor=t["surface"])
            style(ax, t, "Total downloads over time")
            xs = [dt.date.fromisoformat(d) for d in dates]
            series = [(short(r), [at(r, d) for d in dates], t["series"][i]) for i, r in enumerate(top)]
            if rest:
                series.append(("Other", [sum(at(r, d) for r in rest) for d in dates], t["other"]))
            for name, ys, color in series:
                ax.plot(xs, ys, color=color, linewidth=2, solid_capstyle="round")
                ax.annotate(name, (xs[-1], ys[-1]), xytext=(6, 0), textcoords="offset points",
                            va="center", fontsize=9, color=t["ink2"])
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
            ax.yaxis.set_major_locator(MaxNLocator(5, integer=True))
            ax.set_ylim(bottom=0)
            fig.autofmt_xdate(rotation=0, ha="center")
            save(fig, "downloads-over-time", mode)
            if mode == "light":
                charts.append(("downloads-over-time", "Total downloads over time per project"))

        # 2. Downloads per day, all projects together, last 30 days.
        if len(dates) >= 2:
            days = [today - dt.timedelta(days=i) for i in range(29, -1, -1)]
            per_day = []
            for d in days:
                ds, prev = d.isoformat(), (d - dt.timedelta(days=1)).isoformat()
                n = sum(max(0, at(r, ds) - at(r, prev)) for r in with_dl if first_seen[r] <= prev)
                per_day.append(n)
            fig, ax = plt.subplots(figsize=(9, 3.2), facecolor=t["surface"])
            style(ax, t, "New downloads per day, all projects (last 30 days)")
            ax.bar(days, per_day, width=0.8, color=t["bar"])
            ax.yaxis.set_major_locator(MaxNLocator(4, integer=True))
            fig.autofmt_xdate(rotation=0, ha="center")
            save(fig, "downloads-per-day", mode)
            if mode == "light":
                charts.append(("downloads-per-day", "New downloads per day across all projects"))

        # 3. Downloads by project (bar).
        if with_dl:
            shown = with_dl[:12]
            fig, ax = plt.subplots(figsize=(9, 0.42 * len(shown) + 1), facecolor=t["surface"])
            style(ax, t, "Downloads by project")
            ax.grid(axis="y", visible=False)
            ax.grid(axis="x", color=t["grid"], linewidth=0.8)
            ys = list(range(len(shown)))[::-1]
            ax.barh(ys, [totals[r] for r in shown], height=0.62, color=t["bar"])
            ax.set_yticks(ys, [short(r) for r in shown], color=t["ink"])
            for y, r in zip(ys, shown):
                ax.annotate(fmt(totals[r]), (totals[r], y), xytext=(5, 0), textcoords="offset points",
                            va="center", fontsize=9, color=t["ink2"])
            ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: fmt(v)))
            ax.spines["bottom"].set_visible(False)
            save(fig, "downloads-by-project", mode)
            if mode == "light":
                charts.append(("downloads-by-project", "Downloads by project"))

        # 4. Repo page views per day, all projects (needs STATS_TOKEN).
        if traffic:
            vday = defaultdict(int)
            for r in traffic:
                vday[r["date"]] += int(r["views"])
            days = [today - dt.timedelta(days=i) for i in range(29, -1, -1)]
            fig, ax = plt.subplots(figsize=(9, 3.2), facecolor=t["surface"])
            style(ax, t, "GitHub page views per day, all repos (last 30 days)")
            ax.bar(days, [vday.get(d.isoformat(), 0) for d in days], width=0.8, color=t["bar"])
            ax.yaxis.set_major_locator(MaxNLocator(4, integer=True))
            fig.autofmt_xdate(rotation=0, ha="center")
            save(fig, "views-per-day", mode)
            if mode == "light":
                charts.append(("views-per-day", "GitHub page views per day across all repos"))

    # README
    total_all = sum(totals.values())
    l7 = [last7(r) for r in with_dl]
    l7_known = [n for n in l7 if n is not None]
    lines = [
        "# Project stats",
        "",
        f"Downloads, stars and traffic for all of my GitHub projects. Updated {last_date} (UTC) "
        "by the `Collect stats` workflow from GitHub's APIs.",
        "",
        "| Total downloads | Last 7 days | Stars | Page views, last 14 days |",
        "| --- | --- | --- | --- |",
        f"| **{fmt(total_all)}** | {('+' + fmt(sum(l7_known))) if l7_known else '–'} | "
        f"{fmt(sum(stars.values()))} | {fmt(sum(views14.values())) if traffic else 'needs `STATS_TOKEN`'} |",
        "",
    ]
    for name, alt in charts:
        lines += [picture(name, alt), ""]

    lines += ["## Projects", "",
              "| Project | Latest release | Downloads | Last 7 days | Stars | Views (14 d) |",
              "| --- | --- | --: | --: | --: | --: |"]
    order = sorted(dl, key=lambda r: (-totals[r], -stars.get(r, 0), r.lower()))
    for r in order:
        m = meta.get(r, {})
        if not totals[r] and not stars.get(r) and not views14.get(r):
            continue
        lock = " 🔒" if m.get("private") == "true" else ""
        n7 = last7(r) if totals[r] else None
        lines.append(
            f"| [{short(r)}]({m.get('url', 'https://github.com/' + r)}){lock} | {m.get('latest_release') or '–'} | "
            f"{fmt(totals[r]) if totals[r] else '–'} | {('+' + fmt(n7)) if n7 else '–'} | "
            f"{stars.get(r, 0)} | {views14.get(r, 0) if traffic else '–'} |")
    quiet = [r for r in order if not totals[r] and not stars.get(r) and not views14.get(r)]
    if quiet:
        lines += ["", f"<sub>Also tracked, no activity yet: {', '.join(short(r) for r in quiet)}.</sub>"]
    lines += ["", "<sub>Downloads count every file attached to GitHub releases. A rolling build that "
              "gets replaced keeps its earlier downloads, but downloads between two snapshots of a "
              "replaced file can be missed. Raw data is in the CSV files next to this README.</sub>", ""]
    with open(os.path.join(ROOT, "README.md"), "w") as f:
        f.write("\n".join(lines))
    print("README written,", len(charts), "charts")


if __name__ == "__main__":
    main()
