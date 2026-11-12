#!/usr/bin/env python3
"""Collect GitHub stats for every repo you own into CSV files under data/.

Downloads: GitHub only reports each release asset's current counter, and the counter
starts again at 0 when an asset is replaced (e.g. a rolling "latest" build). So
data/assets.csv keeps the highest count ever seen per asset id, and a repo's total is
the sum of those. data/daily.csv then stores one row per repo per day.

Env:
  STATS_TOKEN  optional fine-grained token (all repos; Administration: read,
               Contents: read). Adds private repos and views/clones/referrers.
  GITHUB_TOKEN fallback, public repos only, no traffic.
"""
import csv
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
# collect.py <projects.json> <data dir>
CONFIG = sys.argv[1] if len(sys.argv) > 1 else "projects.json"
DATA = sys.argv[2] if len(sys.argv) > 2 else "data"


class Api:
    def __init__(self, token):
        self.token = token
        self.calls = 0

    def request(self, path, accept):
        return urllib.request.Request(API + path, headers={
            "Accept": accept,
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "project-stats",
        })

    def get(self, path, accept="application/vnd.github+json"):
        for attempt in range(4):
            self.calls += 1
            try:
                with urllib.request.urlopen(self.request(path, accept), timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:300]
                limited = e.code in (403, 429) and ("rate limit" in body.lower() or e.headers.get("Retry-After"))
                if limited and attempt < 3:
                    wait = int(e.headers.get("Retry-After") or 0) or 60 * (attempt + 1)
                    reset = e.headers.get("X-RateLimit-Reset")
                    if e.headers.get("X-RateLimit-Remaining") == "0" and reset:
                        wait = max(wait, int(reset) - int(time.time()) + 2)
                    if wait <= 600:
                        print(f"Rate limited on {path}, waiting {wait}s")
                        time.sleep(wait)
                        continue
                e.msg = f"{e.msg}: {body}"
                raise

    def paged(self, path, accept="application/vnd.github+json"):
        out, page = [], 1
        while True:
            sep = "&" if "?" in path else "?"
            items = self.get(f"{path}{sep}per_page=100&page={page}", accept)
            out += items
            if len(items) < 100:
                return out
            page += 1


def read_rows(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def write_rows(name, fields, rows):
    with open(os.path.join(DATA, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def upsert(name, fields, keys, new_rows):
    rows = {tuple(r[k] for k in keys): r for r in read_rows(name)}
    for r in new_rows:
        rows[tuple(str(r[k]) for k in keys)] = {k: str(r.get(k, "")) for k in fields}
    write_rows(name, fields, [rows[k] for k in sorted(rows)])


def discover(api, cfg, has_pat):
    owner = cfg["owner"]
    if has_pat:
        # The authenticated user's own repos, private included.
        repos = api.paged("/user/repos?affiliation=owner&visibility=all")
    else:
        repos = api.paged(f"/users/{owner}/repos?type=owner")
    out = {}
    for r in repos:
        if r["owner"]["login"].lower() != owner.lower():
            continue
        if r.get("fork") and not cfg.get("include_forks"):
            continue
        if r["name"] in cfg.get("exclude", []) or r["full_name"] in cfg.get("exclude", []):
            continue
        out[r["full_name"]] = r
    for full in cfg.get("extra", []):
        if full not in out:
            try:
                out[full] = api.get(f"/repos/{full}")
            except urllib.error.HTTPError as e:
                print(f"::warning::Can't read {full} ({e.code})")
    return out


def main():
    cfg = json.load(open(CONFIG))
    # Empty owner = whoever owns this repo, so the template works for anyone as-is.
    cfg["owner"] = (cfg.get("owner") or os.environ.get("OWNER", "")).strip()
    if not cfg["owner"]:
        sys.exit("Set owner in projects.json or the OWNER env var")
    pat = os.environ.get("STATS_TOKEN", "").strip()
    api = Api(pat or os.environ["GITHUB_TOKEN"])
    os.makedirs(DATA, exist_ok=True)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()

    repos = discover(api, cfg, bool(pat))
    print(f"Tracking {len(repos)} repos")

    assets = {r["asset_id"]: r for r in read_rows("assets.csv")}
    daily, traffic, refs, latest, rel_rows = [], [], [], [], []
    star_hist = read_rows("stars_history.csv")
    backfilled = {r["repo"] for r in star_hist}
    traffic_ok = bool(pat)

    for full, info in sorted(repos.items()):
        try:
            releases = api.paged(f"/repos/{full}/releases")
        except urllib.error.HTTPError as e:
            print(f"::warning::{full}: releases failed ({e.code})")
            releases = []
        for rel in releases:
            for a in rel.get("assets", []):
                aid = str(a["id"])
                prev = int(assets.get(aid, {}).get("max_count", 0))
                assets[aid] = {
                    "asset_id": aid, "repo": full, "tag": rel["tag_name"], "name": a["name"],
                    "prerelease": str(bool(rel.get("prerelease"))).lower(),
                    "max_count": max(prev, a["download_count"]),
                }
        for rel in releases:
            if rel.get("draft"):
                continue
            rel_rows.append({"repo": full, "tag": rel["tag_name"],
                             "published_at": (rel.get("published_at") or rel.get("created_at") or "")[:10],
                             "prerelease": str(bool(rel.get("prerelease"))).lower()})

        # Full star history, once per repo: GitHub dates every current star. Later days come
        # from daily.csv. (Stars that were removed can't be seen, so old counts may be a bit low.)
        # The Actions token isn't allowed to list stargazers of other repos, so this needs STATS_TOKEN.
        if pat and full not in backfilled and info["stargazers_count"] > 0:
            try:
                stars = api.paged(f"/repos/{full}/stargazers", "application/vnd.github.star+json")
                per_day = {}
                for st in stars:
                    d = (st.get("starred_at") or "")[:10]
                    if d:
                        per_day[d] = per_day.get(d, 0) + 1
                total = 0
                for d in sorted(per_day):
                    total += per_day[d]
                    star_hist.append({"repo": full, "date": d, "stars": total})
                backfilled.add(full)
            except urllib.error.HTTPError as e:
                print(f"::warning::{full}: star history failed ({e.code} {e.msg})")

        stable = [r for r in releases if not r.get("draft") and not r.get("prerelease")]
        latest.append({
            "repo": full,
            "latest_release": stable[0]["tag_name"] if stable else "",
            "released_at": stable[0]["published_at"][:10] if stable else "",
            "private": str(info.get("private", False)).lower(),
            "description": (info.get("description") or "").replace("\n", " "),
            "url": info["html_url"],
        })
        daily.append({
            "date": today, "repo": full,
            "stars": info["stargazers_count"], "forks": info["forks_count"],
            "open_issues": info["open_issues_count"],
        })

        if traffic_ok:
            try:
                v = api.get(f"/repos/{full}/traffic/views")
                c = api.get(f"/repos/{full}/traffic/clones")
                days = {}
                for d in v["views"]:
                    days.setdefault(d["timestamp"][:10], {})["views"] = d["count"]
                    days[d["timestamp"][:10]]["visitors"] = d["uniques"]
                for d in c["clones"]:
                    days.setdefault(d["timestamp"][:10], {})["clones"] = d["count"]
                for day, vals in days.items():
                    traffic.append({"date": day, "repo": full, "views": vals.get("views", 0),
                                    "visitors": vals.get("visitors", 0), "clones": vals.get("clones", 0)})
                for r in api.get(f"/repos/{full}/traffic/popular/referrers"):
                    refs.append({"date": today, "repo": full, "referrer": r["referrer"],
                                 "views": r["count"], "visitors": r["uniques"]})
            except urllib.error.HTTPError as e:
                print(f"::warning::{full}: traffic failed ({e.code}). Does STATS_TOKEN have Administration: read?")

    write_rows("assets.csv", ["asset_id", "repo", "tag", "name", "prerelease", "max_count"],
               sorted(assets.values(), key=lambda r: (r["repo"], r["tag"], r["name"], int(r["asset_id"]))))

    totals = {}
    for a in assets.values():
        totals[a["repo"]] = totals.get(a["repo"], 0) + int(a["max_count"])
    for d in daily:
        d["downloads"] = totals.get(d["repo"], 0)
    upsert("daily.csv", ["date", "repo", "downloads", "stars", "forks", "open_issues"], ["date", "repo"], daily)

    # Per release, per day: powers the version split and per-version trends.
    per_tag = {}
    for a in assets.values():
        k = (a["repo"], a["tag"])
        per_tag[k] = per_tag.get(k, 0) + int(a["max_count"])
    upsert("releases_daily.csv", ["date", "repo", "tag", "downloads"], ["date", "repo", "tag"],
           [{"date": today, "repo": r, "tag": t, "downloads": n} for (r, t), n in per_tag.items()])
    write_rows("releases.csv", ["repo", "tag", "published_at", "prerelease"], rel_rows)
    write_rows("stars_history.csv", ["repo", "date", "stars"],
               sorted(star_hist, key=lambda r: (r["repo"], r["date"])))
    write_rows("repos.csv", ["repo", "latest_release", "released_at", "private", "description", "url"], latest)
    if traffic:
        # GitHub keeps only 14 days of traffic, so every day seen is stored.
        upsert("traffic.csv", ["date", "repo", "views", "visitors", "clones"], ["date", "repo"], traffic)
    if refs:
        upsert("referrers.csv", ["date", "repo", "referrer", "views", "visitors"], ["date", "repo", "referrer"], refs)
    if not pat:
        print("::notice::Add a STATS_TOKEN secret to backfill full star history and collect traffic")
    print(f"Done, {api.calls} API calls")


if __name__ == "__main__":
    main()
