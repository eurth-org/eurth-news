# Eurth News Network

A rolling news feed for **The Newsroom** on [Eurth](https://eurth.org): a
paper-style homepage plus an RSS feed of the 25 newest news stories (replies)
posted in the category, updated automatically every 5 minutes.

Live page: https://eurth-org.github.io/eurth-news/
RSS feed:  https://eurth-org.github.io/eurth-news/news.rss

## How it works

- `newsroom.py` queries the Discourse search API for the newest 25 replies in
  the Newsroom category (`category:36 in:replies order:latest`), fetches each
  post's full content, then renders:
  - `_site/index.html` - a newspaper-styled homepage (masonry layout,
    numbered stories, expandable teasers)
  - `_site/news.rss` - an RSS 2.0 feed with the full story content
- The GitHub Actions workflow (`.github/workflows/newsroom.yml`) runs the
  script on a cron schedule (every 5 minutes) and deploys `_site/` to
  GitHub Pages.

## Local development

```bash
python3 -m py_compile newsroom.py   # sanity check
python3 newsroom.py                 # generates _site/index.html + _site/news.rss
