#!/usr/bin/env python3
"""Build a rolling feed of the newest 25 stories (replies) in The Newsroom."""
import json, os, datetime
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

SITE = "https://eurth.org"
CATEGORY = 36            # The Newsroom
LIMIT = 25
OUTDIR = "_site"

API_KEY = os.environ.get("DISCOURSE_API_KEY", "")
API_USER = os.environ.get("DISCOURSE_API_USERNAME", "system")

def fetch():
    q = quote(f"category:{CATEGORY} in:replies order:latest")
    headers = {"User-Agent": "Eurth-Newsroom-Feed/1.0", "Accept": "application/json"}
    if API_KEY:
        headers["Api-Key"] = API_KEY
        headers["Api-Username"] = API_USER
    req = Request(f"{SITE}/search.json?q={q}", headers=headers)
    with urlopen(req, timeout=30) as r:
        return json.load(r)["posts"][:LIMIT]

def rss_date(iso):
    dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

def build_rss(items):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0"><channel>']
    lines.append("<title>Eurth — The Newsroom</title>")
    lines.append(f"<link>{SITE}/c/affairs/the-newsroom/36</link>")
    lines.append("<description>25 newest news stories in The Newsroom</description>")
    for p in items:
        url = f"{SITE}/t/{p.get('topic_slug')}/{p['topic_id']}/{p.get('post_number')}"
        lines += [
            "<item>",
            f"<title>{escape(p.get('topic_title', 'News story'))}</title>",
            f"<link>{escape(url)}</link>",
            f'<guid isPermaLink="true">{escape(url)}</guid>',
            f"<pubDate>{rss_date(p['created_at'])}</pubDate>",
            f"<author>{escape(p.get('username', ''))}</author>",
            f"<description>{escape(p.get('cooked', '') or '')}</description>",
            "</item>",
        ]
    lines += ["</channel></rss>"]
    return "\n".join(lines)

def build_html(items):
    cards = []
    for p in items:
        url = f"{SITE}/t/{p.get('topic_slug')}/{p['topic_id']}/{p.get('post_number')}"
        cards.append(
            f'<article class="story">'
            f'<h2>{escape(p.get("topic_title", "News"))} <span class="by">by {escape(p.get("username", ""))}</span></h2>'
            f'<div class="body">{p.get("cooked", "") or ""}</div>'
            f'<a class="read" href="{escape(url)}">Read the full post &rarr;</a>'
            f'</article>'
        )
    css = ("body{font-family:system-ui,sans-serif;max-width:800px;margin:auto;padding:1em;"
           "background:#f7f7f7;color:#222}.story{background:#fff;border:1px solid #ddd;"
           "border-radius:8px;padding:1em 1.2em;margin:1em 0}.by{color:#888;font-size:.8em;font-weight:normal}"
           ".body{line-height:1.5}.read{display:inline-block;margin-top:.5em;color:#08c}")
    return (f"<!doctype html><meta charset='utf-8'><title>The Newsroom — Live</title>"
            f"<style>{css}</style><h1>The Newsroom — live feed</h1>"
            f"<p>Newest 25 stories, updated every 5 minutes.</p>"
            f"{''.join(cards)}")

if __name__ == "__main__":
    os.makedirs(OUTDIR, exist_ok=True)
    items = fetch()
    with open(f"{OUTDIR}/index.html", "w") as f:
        f.write(build_html(items))
    with open(f"{OUTDIR}/news.rss", "w") as f:
        f.write(build_rss(items))
    print(f"Updated: {len(items)} items -> {OUTDIR}/")
