# Eurth News Network

A rolling news feed for **The Newsroom** on [Eurth](https://eurth.org): a paper-style homepage plus an RSS feed of the 25 newest news stories (replies) posted in the category, updated automatically every 5 minutes.

Live page: https://eurth-org.github.io/eurth-news/
RSS feed:  https://eurth-org.github.io/eurth-news/news.rss

## How it works

- `newsroom.py` queries the Discourse search API for the newest 25 replies in the Newsroom category (`category:36 in:replies order:latest`), fetches each post's full content, then renders:
  - `_site/index.html` - a newspaper-styled homepage (masonry layout, numbered stories, expandable teasers)
  - `_site/news.rss` - an RSS 2.0 feed with the full story content
- The GitHub Actions workflow (`.github/workflows/newsroom.yml`) runs the script on a cron schedule (every 5 minutes) and deploys `_site/` to GitHub Pages.

## Local development

```bash
python3 -m py_compile newsroom.py   # sanity check
python3 newsroom.py                 # generates _site/index.html + _site/news.rss
```

Then open `_site/index.html` in a browser.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `SITE` | Base URL of the Discourse site | `https://eurth.org` |
| `CATEGORY` | Category ID to pull stories from | `36` |
| `LIMIT` | Number of newest stories | `25` |
| `DISCOURSE_API_KEY` | Optional read-only API key (env / repo secret) | empty |
| `DISCOURSE_API_USERNAME` | API username | `system` |

If the site disallows anonymous API access, add `DISCOURSE_API_KEY` as a  GitHub Actions repository secret; the script picks it up automatically.

## Deployment

The workflow handles everything: push to `main` (or `Run workflow` manually) builds and publishes the latest feed to GitHub Pages. Enable Pages with  **Source: GitHub Actions** in the repo settings.

## License

MIT
