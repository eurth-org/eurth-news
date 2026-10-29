# Eurth News Network

A rolling front page for **The Newsroom** on [Eurth](https://eurth.org): the 25 newest news stories (replies) posted in the category, presented side by side, plus an RSS feed. Rebuilt automatically every 2 hours.

Live page: https://news.eurth.org/
RSS feed:  https://news.eurth.org/news.rss

## How it works

- `newsroom.py` queries the Discourse search API for the newest 25 replies in the Newsroom category (`category:36 in:replies order:latest`) and fetches each post's full content.
- Every agency formats its posts differently (banners, mock menus, tickers, datelines), so the script reads each post and pulls out a real headline, section label, standfirst, lead photo and reading time. The page then shows every agency the same way; the original post is kept intact for reading.
- It renders into `_site/`:
  - `index.html`: the front page. Lead story, "Also new" column, a "More stories" grid in reading order, Most read, a nation filter and full-text search. A sticky section bar keeps search and the sections in reach (a menu button on phones); the top bar shows the reader's local date and time. Stories open in a reader with newer/older navigation, deep-linkable as `#story-<post id>`. "New" markers since your last visit, read stories dimmed, light and dark themes.
  - `story/<post id>/index.html`: one page per story, readable without JavaScript, with its own social card.
  - `oembed.json` next to every page, advertised with `<link rel="alternate" type="application/json+oembed">`, plus Open Graph and X card tags, so links unfurl on Discourse, Discord, Slack, Bluesky, Mastodon and X.
  - `news.rss`: an RSS 2.0 feed with real headlines and the full story content.
  - `static/`: copied from the repo (favicon, rotating globe and its still frame, Apple touch icon, share card).
- The GitHub Actions workflow (`.github/workflows/newsroom.yml`) runs the script every 2 hours, on every push to `main`, and on demand, and deploys `_site/` to GitHub Pages.

## Design

The page follows the **Eurth** design system (Claude Design): forum light and Solarized "Night" themes, Libre Baskerville for headlines, Helvetica for labels and text, JetBrains Mono for dates, the forum's rotating globe in the corner (a still frame when the reader prefers reduced motion). The page frame is Eurth's own (out of character); the stories inside keep their agencies' words but not their banners or colours, and the Eurth logo never sits on a story. Navigation stays on the site; links to eurth.org are in the reader, on story pages and in the footer. `static/share-card.jpg` is the system's 1200 x 800 ShareCard layout with the satellite map of Eurth.

## Local development

```bash
python3 -m py_compile newsroom.py   # sanity check
python3 newsroom.py                 # generates _site/
python3 -m http.server -d _site     # then open http://localhost:8000
```

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `SITE` | Base URL of the Discourse site | `https://eurth.org` |
| `PAGE_URL` | Public URL of this site (canonical links, social cards, oEmbed) | `https://news.eurth.org/` |
| `CATEGORY` | Category ID to pull stories from | `36` |
| `LIMIT` | Number of newest stories | `25` |
| `DISCOURSE_API_KEY` | Optional read-only API key (env / repo secret) | empty |
| `DISCOURSE_API_USERNAME` | API username | `system` |
| `EMBED_COMMENTS` | `1` adds the Discourse discussion under each story page (env / repo variable) | off |

If the site disallows anonymous API access, add `DISCOURSE_API_KEY` as a GitHub Actions repository secret; the script picks it up automatically.

## Comments

Story pages can show a live Discourse discussion underneath, using Discourse's embedding. It stays off until eurth.org is set up for it, because once it is on, the first visit to each story page creates a topic on eurth.org for that page.

1. On eurth.org, **Admin > Advanced > Embedding**: add `news.eurth.org` as an allowed host and pick the category the discussion topics go to. Consider "full app mode", loading comments only near the bottom, letting the frame grow with the thread, and keeping new topics unlisted until someone replies.
2. In this repo, **Settings > Secrets and variables > Actions > Variables**: add `EMBED_COMMENTS` = `1`, then run the workflow.

Each story page sets `discourse-username` to the posting nation, so the topic is credited to them.

## Deployment

The workflow handles everything: push to `main` (or `Run workflow` manually) builds and publishes the latest feed to GitHub Pages. Enable Pages with **Source: GitHub Actions** in the repo settings; `news.eurth.org` is set as the Pages custom domain.

## License

MIT
