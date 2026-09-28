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
    """Strip Discourse's lightbox wrapper+meta row, keep bare <img>, no hotlink Referer."""
    cooked = re.sub(
        r'<div class="lightbox-wrapper">\s*<a class="lightbox"[^>]*>\s*'
        r'(<img[^>]*>)\s*'
        r'<div class="meta">.*?</div>\s*</a>\s*</div>',
        r"\1",
        cooked,
        flags=re.DOTALL,
    )
    cooked = re.sub(r"(<img\b)", r'\1 referrerpolicy="no-referrer"', cooked)
    return cooked


def fix_urls(cooked):
    """Make Discourse's relative /u/, /t/, /c/, /uploads/ URLs absolute (eurth.org)."""
    def repl(m):
        attr, q, url = m.group(1), m.group(2), m.group(3)
        if url.startswith(("http:", "https:", "//", "mailto:", "tel:", "javascript:", "data:", "#")):
            return m.group(0)
        if url.startswith("/"):
            return f"{attr}={q}{SITE}{url}{q}"
        return m.group(0)

    return re.sub(r'\b(href|src)=(["\'])([^"\']*)\2', repl, cooked)


def fetch_stories():
    # 1) 25 newest replies in the category + topic-title map from the same response
    q = quote(f"category:{CATEGORY} in:replies order:latest")
    data = get_json(f"{SITE}/search.json?q={q}")
    hits = data.get("posts", [])[:LIMIT]
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

        cooked = fix_urls(fix_images(detail.get("cooked") or p.get("cooked") or ""))

        stories.append({
            "agency": agency,
            "author": detail.get("username") or p.get("username", ""),
            "date":   detail.get("created_at") or p.get("created_at", ""),
            "cooked": cooked,
            "url":    f"{SITE}/t/{p.get('topic_slug')}/{tid}/{p.get('post_number')}",
        })
        time.sleep(0.3)   # be polite to eurth.org's API
    return stories


def fmt_date(iso):
    try:
        dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%d %B %Y")
    except Exception:
        return iso


def rss_date(iso):
    dt = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.astimezone(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def build_rss(items):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0"><channel>']
    lines.append("<title>Eurth News Network — Yesterday's News Today</title>")
    lines.append(f"<link>{SITE}/c/affairs/the-newsroom/36</link>")
    lines.append("<description>Rolling feed of the 25 newest news stories in The Newsroom</description>")
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
            f'<div class="kicker">{escape(s["agency"])}</div>'
            f'<div class="byline">By <strong>{escape(s["author"])}</strong> &middot; {escape(fmt_date(s["date"]))}</div>'
            f'<div class="body">{s["cooked"]}</div>'
            f'<button class="toggle" type="button">Read full story</button>'
            f'<a class="read" href="{escape(s["url"])}">Open the exact post &rarr;</a>'
            f'</article>'
        )
    last = fmt_date(items[0]["date"]) if items else ""

    css = (
        /* base */
        "body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;"
        "max-width:1100px;margin:auto;padding:0 1em;background:#f4f4f4;color:#222}"
        /* masthead — Georgia headers */
        ".masthead{font-family:Georgia,'Times New Roman',serif;text-align:center;"
        "border-bottom:4px double #222;background:#fff;padding:1.6em 1em .9em;margin-bottom:1.4em}"
        ".masthead h1{font-size:3em;margin:0;font-weight:700;letter-spacing:.02em;text-transform:uppercase}"
        ".masthead .tagline{font-style:italic;color:#555;margin:.3em 0 0;font-size:1.1em}"
        ".masthead .dateline{color:#777;font-size:.8em;margin-top:.7em;letter-spacing:.06em;"
        "font-family:system-ui,sans-serif}"
        /* masonry grid */
        ".masonry{columns:2 340px;column-gap:1.4em}"
        ".wrap{padding:0 0 1.5em}"
        /* story cards */
        ".story{break-inside:avoid;margin:0 0 1.4em;background:#fff;border:1px solid #e5e5e5;"
        "border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.10);padding:1.1em 1.2em}"
        ".kicker{font-family:Georgia,serif;font-weight:700;text-transform:uppercase;"
        "letter-spacing:.07em;font-size:.95em;color:#b00;margin-bottom:.35em}"
        ".byline{color:#666;font-size:.85em;font-style:italic;margin-bottom:.7em}"
        /* body: sans-serif, clamped to ~6 lines until expanded */
        ".body{font-size:1em;line-height:1.55;display:-webkit-box;-webkit-line-clamp:6;"
        "-webkit-box-orient:vertical;overflow:hidden}"
        ".story.expanded .body{-webkit-line-clamp:unset;overflow:visible}"
        ".body img{max-width:100%;height:auto;border-radius:6px}"
        ".body pre{background:#f5f5f5;padding:.8em;overflow:auto;border-radius:4px}"
        ".body blockquote{border-left:3px solid #b00;margin:.7em 0;padding:0 .9em;color:#444}"
        ".body code{background:#f0f0f0;padding:.15em .35em;border-radius:3px}"
        /* buttons + link */
        ".toggle{font-family:system-ui,sans-serif;margin-top:.8em;padding:.5em 1em;border:none;"
        "border-radius:6px;background:#b00;color:#fff;font-weight:600;cursor:pointer;font-size:.85em}"
        ".toggle:hover{background:#900}"
        ".toggle.expanded-open{background:#555}"
        ".read{display:inline-block;margin-top:.8em;color:#08c;font-weight:600;font-size:.85em}"
        ".sitefoot{text-align:center;color:#888;font-size:.85em;padding:1.2em 0 2em}"
        ".sitefoot a{color:#b00}"
        "@media(max-width:700px){.masonry{columns:1}}"
    )

    script = """
<script>
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".story").forEach(function (card) {
    var btn = card.querySelector(".toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var open = card.classList.toggle("expanded");
      btn.textContent = open ? "Show less" : "Read full story";
    });
  });
});
</script>
"""

    return (
        f"<!doctype html><meta charset='utf-8'>"
        f"<meta name='referrer' content='no-referrer'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Eurth News Network — Yesterday's News Today</title>"
        f"<style>{css}</style>"
        f"<header class='masthead'>"
        f"  <h1>Eurth News Network</h1>"
        f"  <p class='tagline'>Yesterday's News Today</p>"
        f"  <p class='dateline'>LATEST STORIES &middot; UPDATED {escape(last)}</p>"
        f"</header>"
        f"<div class='wrap'><div class='masonry'>"
        f"{''.join(cards)}"
        f"</div>"
        f"  <footer class='sitefoot'>"
        f"    Subscribe: <a href='news.rss'>RSS feed</a>"
        f"  </footer>"
        f"</div>"
        f"{script}"
    )


if __name__ == "__main__":
    os.makedirs(OUTDIR, exist_ok=True)
    open(f"{OUTDIR}/.nojekyll", "w").close()
    items = fetch_stories()
    with open(f"{OUTDIR}/index.html", "w") as f:
        f.write(build_html(items))
    with open(f"{OUTDIR}/news.rss", "w") as f:
        f.write(build_rss(items))
    print(f"Updated {len(items)} stories -> {OUTDIR}/")
