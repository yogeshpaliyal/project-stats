# project-stats

One dashboard for all your GitHub projects: release downloads, stars, page views and
where visitors come from. No server, no tracking code in your apps. A GitHub Action
reads GitHub's own APIs every 6 hours and publishes a static site on GitHub Pages.

**Live example:** https://yogeshpaliyal.github.io/project-stats/

- Every repo you own is picked up automatically, new ones included.
- Filter by project and date range (7, 30, 90 days, all).
- New downloads per day, stacked by project, or by version when you pick one project.
- Downloads by version, by file type (APK, AAB, ZIP…), running totals, stars over time.
- Page views, unique visitors and top referrers (with an optional token).
- Light and dark mode, works on phones. Filters live in the URL, so views are shareable.

## Use it for your own projects

1. Click **Use this template** → **Create a new repository**. Make it **public**
   (GitHub Pages needs a public repo on the free plan).
2. In the new repo, open **Settings → Pages** and set **Source** to **GitHub Actions**.
3. Open **Actions → Collect stats → Run workflow**.

That's it. Your site appears at `https://<you>.github.io/<repo>/` after the first run,
and updates every 6 hours.

### Optional: views, visitors, referrers and private repos

GitHub only shares traffic with people who can administer a repo, so the built-in
Actions token can't read it. To add it:

1. Create a [fine-grained token](https://github.com/settings/personal-access-tokens/new):
   - **Repository access:** All repositories
   - **Permissions:** Administration → Read-only, Contents → Read-only (Metadata is added automatically)
2. In this repo: **Settings → Secrets and variables → Actions → New repository secret**,
   name it `STATS_TOKEN`, paste the token.

With the token, private repos are included too. Their names and numbers will show on
your public site, so add any you'd rather hide to `exclude` below.

GitHub keeps only 14 days of traffic, so the workflow stores every day it sees. History
starts the day you add the token.

## Settings: `projects.json`

```json
{
  "owner": "",
  "exclude": ["dotfiles", "my-secret-thing"],
  "extra": ["some-org/project-i-maintain"],
  "include_forks": false
}
```

- `owner`: leave empty to use whoever owns this repo.
- `exclude`: repo names to skip.
- `extra`: repos owned by someone else (e.g. an organization) to add.
- `include_forks`: count your forks too.

## How it works

- **`main`** holds the code: `index.html` (the site), `.github/scripts/collect.py`
  (the collector), `.github/scripts/render.py` (charts for the data branch README).
- **`data`** holds the numbers as CSV files, plus a README with charts, handy if you
  keep the repo private and skip Pages. Only this branch changes on each run.
- Download counters on GitHub restart at 0 when a release file is replaced (for
  example a rolling nightly build). The collector keeps the highest count seen for
  each file, so totals never go backwards. Downloads made between two snapshots of a
  file that then gets replaced can still be missed.
- Downloads before you first ran it only show up in the totals, not in the per-day charts.

## Data files (`data` branch)

| File | One row per |
| --- | --- |
| `daily.csv` | day, repo: total downloads, stars, forks, open issues |
| `releases_daily.csv` | day, repo, release: downloads |
| `assets.csv` | release file: highest download count seen |
| `traffic.csv` | day, repo: views, unique visitors, clones |
| `referrers.csv` | day, repo, site: views, unique visitors |
| `repos.csv` | repo: latest release, description, link |

## License

MIT
