#!/usr/bin/env python3
"""Rolling news feed: newest 25 stories (replies) in The Newsroom, category 36, on eurth.org."""
import json, os, re, time, datetime
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

SITE = "https://eurth.org"
CATEGORY = 36          # The Newsroom
LIMIT = 25
OUTDIR = "_site"

API_KEY = os.environ.get("DISCOURSE_API_KEY", "")
API_USER = os.environ.get("DISCOURSE_API_USERNAME", "system")

def get_json(url):
    headers = {"User-Agent": "Eurth-Newsroom-Feed/1.0", "Accept": "application/json"}
    if API_KEY:
        headers["Api-Key"] = API_KEY
        headers["Api-Username"] = API_USER
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as r:
        return json.load(r)

def fix_images(cooked):
    # 1) Discard Discourse's lightbox wrapper + meta row (filename, size, icon),
    #    keeping only the plain <img> so no empty space or meta text remains
    cooked = re.sub(
        r'<div class="lightbox-wrapper">\s*<a class="lightbox"[^>]*>\s*'
        r'(<img[^>]*>)\s*'
        r'<div class="meta">.*?</div>\s*</a>\s*</div>',
        r"\1",
        cooked,
        flags=re.DOTALL,
    )
    # 2) Bypass hotlink protection: no Referer header for remaining images
    cooked = re.sub(r"(<img\b)", r'\1 referrerpolicy="no-referrer"', cooked)
    return cooked

def fix_urls(cooked):
    # Discourse emits internal links as relative ("/u/orioni", "/t/...", "/c/...");
    # make them absolute so they work when served from GitHub Pages.
    SITE_URL = SITE  # "https://eurth.org"

    def repl(m):
        attr, quote, url = m.group(1), m.group(2), m.group(3)
        # Skip anything already absolute, protocol-relative, or non-http
        if url.startswith(("http:", "https:", "//", "mailto:", "tel:", "javascript:", "data:", "#")):
            return m.group(0)
        # Only rewrite real relative paths (e.g. "/u/orioni")
        if url.startswith("/"):
            return f'{attr}={quote}{SITE_URL}{url}{quote}'
        return m.group(0)

    return re.sub(r'\b(href|src)=(["\'])([^"\']*)\2', repl, cooked)

def fetch_stories():
    # 1) Find the 25 newest replies + snapshot of the topics they belong to
    q = quote(f"category:{CATEGORY} in:replies order:latest")
    data = get_json(f"{SITE}/search.json?q={q}")
    hits = data.get("posts", [])[:LIMIT]

    # topic_id -> title map straight from the search response
    titles = {t["id"]: t.get("title") for t in data.get("topics", [])}

    stories = []
    for p in hits:
        tid = p.get("topic_id", 0)

        # 2) Full post body + topic slug
        try:
            detail = get_json(f"{SITE}/posts/{p['id']}.json")
        except Exception:
            detail = {}

        agency = (
            titles.get(tid)
            or detail.get("topic_title")
            or p.get("topic_title")
            or (p.get("topic_slug") or "").replace("-", " ").title()
            or "News"
        )

        stories.append({
            "agency": agency,
            "author": detail.get("username") or p.get("username", ""),
            "date":   detail.get("created_at") or p.get("created_at", ""),
            "cooked": fix_urls(fix_images(detail.get("cooked") or p.get("cooked") or "")),
            "url":    f"{SITE}/t/{p.get('topic_slug')}/{tid}/{p.get('post_number')}",
        })
        time.sleep(0.3)   # be polite to eurth.org's API
    return stories

def rss_date(iso):
    dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

def build_rss(items):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0"><channel>']
    lines.append("<title>Eurth — The Newsroom</title>")
    lines.append(f"<link>{SITE}/c/affairs/the-newsroom/36</link>")
    lines.append("<description>25 newest news stories in The Newsroom</description>")
    for s in items:
        lines += [
            "<item>",
            f"<title>{escape(s['agency'])}</title>",
            f"<link>{escape(s['url'])}</link>",
            f'<guid isPermaLink="true">{escape(s["url"])}</guid>',
            f"<pubDate>{rss_date(s['date'])}</pubDate>",
            f"<author>{escape(s['author'])}</author>",
            f"<description>{escape(s['cooked'])}</description>",
            "</item>",
        ]
    lines += ["</channel></rss>"]
    return "\n".join(lines)

def build_html(items):
    cards = []
    for s in items:
        cards.append(
            f'<article class="story">'
            f'<h2 class="agency">{escape(s["agency"])}</h2>'
            f'<p class="meta">by <strong>{escape(s["author"])}</strong> &middot; {escape(s["date"])}</p>'
            f'<div class="body">{s["cooked"]}</div>'
            f'<a class="read" href="{escape(s["url"])}">Read the full post &rarr;</a>'
            f'</article>'
        )
    css = ("body{font-family:system-ui,sans-serif;max-width:820px;margin:auto;padding:1em;"
           "background:#f7f7f7;color:#222}"
           ".story{background:#fff;border:1px solid #ddd;border-radius:8px;padding:1em 1.2em;margin:1em 0}"
           ".agency{margin:0 0 .2em}.meta{color:#888;font-size:.85em;margin:0 0 .8em}"
           ".body{line-height:1.6}.body img{max-width:100%;height:auto;border-radius:4px}"
           ".body pre{background:#f4f4f4;padding:1em;overflow:auto;border-radius:4px}"
           ".body blockquote{border-left:4px solid #ddd;margin:1em 0;padding:0 1em;color:#555}"
           ".body code{background:#eee;padding:.1em .3em;border-radius:3px}"
           ".body .lightbox-wrapper .meta{display:none!important}"
           ".read{display:inline-block;margin-top:1em;color:#08c}")
    return (f"<!doctype html><meta charset='utf-8'>"
            f"<meta name='referrer' content='no-referrer'>"  # global no-referrer -> images load
            f"<title>The Newsroom - Live</title>"
            f"<style>{css}</style><h1>The Newsroom &mdash; live feed</h1>"
            f"<p>Newest {LIMIT} stories, updated every 5 minutes.</p>"
            f"{''.join(cards)}")

if __name__ == "__main__":
    os.makedirs(OUTDIR, exist_ok=True)
    open(f"{OUTDIR}/.nojekyll", "w").close()
    items = fetch_stories()
    with open(f"{OUTDIR}/index.html", "w") as f:
        f.write(build_html(items))
    with open(f"{OUTDIR}/news.rss", "w") as f:
        f.write(build_rss(items))
    print(f"Updated {len(items)} stories -> {OUTDIR}/")
