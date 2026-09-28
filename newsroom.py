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
    """Strip Discourse's lightbox wrapper and meta row, keep bare <img>, no hotlink referer."""
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
    """Rewrite Discourse's relative /u/, /t/, /c/, /uploads/ URLs to absolute."""
    def repl(m):
        attr, q, url = m.group(1), m.group(2), m.group(3)
        if url.startswith(("http:", "https:", "//", "mailto:", "tel:", "javascript:", "data:", "#")):
            return m.group(0)
        if url.startswith("/"):
            return f"{attr}={q}{SITE}{url}{q}"
        return m.group(0)

    return re.sub(r'\b(href|src)=(["\'])([^"\']*)\2', repl, cooked)


def fetch_stories():
    q = quote(f"category:{CATEGORY} in:replies order:latest")
    data = get_json(f"{SITE}/search.json?q={q}")
    hits = data.get("posts", [])[:LIMIT]
    titles = {t["id"]: t.get("title") for t in data.get("topics", [])}

    stories = []
    for p in hits:
        tid = p.get("topic_id", 0)

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
        time.sleep(0.3)
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
    lines.append("<title>Eurth News Network - Yesterday's News Today</title>")
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
    for i, s in enumerate(items):
        rank = str(i + 1).zfill(2)
        cards.append(
            f'<article class="story">'
            f'<div class="story-head">'
            f'<span class="rank">{rank}</span>'
            f'<span class="kicker">{escape(s["agency"])}</span>'
            f'</div>'
            f'<div class="byline">By <strong>{escape(s["author"])}</strong> &middot; {escape(fmt_date(s["date"]))}</div>'
            f'<div class="body">{s["cooked"]}</div>'
            f'<button class="toggle" type="button">Read full story &darr;</button>'
            f'<a class="read" href="{escape(s["url"])}">Open the exact post &rarr;</a>'
            f'</article>'
        )
    last = fmt_date(items[0]["date"]) if items else ""
    today = datetime.datetime.utcnow().strftime("%d %b %Y")

    css = (
        "body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;"
        "max-width:90%;margin:auto;padding:0 1.5em 2em;background:#f7f4ec;color:#111}"
        ".paper{background:#fffdf7;border:1px solid #ddd;padding:0 1.6em 2em;margin-top:1.5em}"
        ".topbar{display:flex;justify-content:space-between;align-items:center;"
        "font-size:.75em;letter-spacing:.12em;text-transform:uppercase;color:#555;"
        "border-bottom:1px solid #444;padding:.8em 0}"
        ".topbar a{color:#111;text-decoration:none;border-bottom:1px solid #111}"
        ".masthead{text-align:center;padding:1.6em .5em 1.1em;"
        "border-bottom:4px double #111}"
        ".masthead h1{font-family:Georgia,'Times New Roman',serif;font-size:3.2em;"
        "margin:0;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#111}"
        ".masthead .tagline{font-family:Georgia,serif;font-style:italic;color:#333;"
        "margin:.35em 0 0;font-size:1.15em}"
        ".nav-strip{display:flex;justify-content:center;gap:1.6em;flex-wrap:wrap;"
        "font-size:.8em;letter-spacing:.1em;text-transform:uppercase;color:#333;"
        "border-bottom:1px solid #111;padding:.7em .5em}"
        ".nav-strip a{color:#333;text-decoration:none}"
        ".nav-strip a:hover{text-decoration:underline}"
        ".masonry{columns:3 300px;column-gap:2em;column-rule:1px solid #cfc9ba;margin-top:1.8em}"
        ".story{break-inside:avoid;margin:0 0 1.6em;padding-bottom:1.6em;"
        "border-bottom:1px solid #cfc9ba}"
        ".story-head{display:flex;align-items:baseline;gap:.7em;margin-bottom:.25em}"
        ".rank{font-family:Georgia,serif;font-size:2.2em;font-weight:700;color:#b9b3a2;line-height:1}"
        ".kicker{font-family:Georgia,serif;font-weight:700;text-transform:uppercase;"
        "letter-spacing:.09em;font-size:1.05em;color:#111}"
        ".byline{color:#555;font-size:.8em;font-style:italic;margin-bottom:.7em;"
        "letter-spacing:.03em}"
        ".body{font-size:1em;line-height:1.6;color:#222;display:-webkit-box;"
        "-webkit-line-clamp:8;-webkit-box-orient:vertical;overflow:hidden}"
        ".story.expanded .body{-webkit-line-clamp:unset;overflow:visible}"
        ".body img{max-width:100%;height:auto;margin:.4em 0}"
        ".body pre{background:#f1ede2;padding:.8em;overflow:auto;border:1px solid #d8d2c2}"
        ".body blockquote{border-left:3px solid #888;margin:.7em 0;padding:0 .9em;color:#444}"
        ".body code{background:#efeade;padding:.15em .35em}"
        ".toggle{font-family:Georgia,serif;margin-top:1em;padding:.45em 1em;background:transparent;"
        "color:#111;border:1px solid #111;cursor:pointer;font-size:.82em;letter-spacing:.08em;"
        "text-transform:uppercase}"
        ".toggle:hover{background:#111;color:#fffdf7}"
        ".read{display:inline-block;margin-top:.9em;color:#111;font-size:.82em;"
        "letter-spacing:.08em;text-transform:uppercase;text-decoration:underline}"
        ".sitefoot{text-align:center;border-top:4px double #111;margin-top:2em;padding-top:1.4em}"
        ".sitefoot .logo{font-family:Georgia,serif;font-weight:700;font-size:1.8em;"
        "text-transform:uppercase;letter-spacing:.06em;color:#111;margin:0 0 .3em}"
        ".sitefoot .links{font-size:.8em;color:#555}.sitefoot .links a{color:#111;"
        "margin:0 .5em;text-decoration:underline}"
        "@media(max-width:800px){.masonry{columns:1}.masthead h1{font-size:2.2em}}"
    )

    script = """
<script>
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".story").forEach(function (card) {
    var btn = card.querySelector(".toggle");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var open = card.classList.toggle("expanded");
      btn.textContent = open ? "Show less &uarr;" : "Read full story &darr;";
    });
  });
});
</script>
"""

    return (
        f"<!doctype html><meta charset='utf-8'>"
        f"<meta name='referrer' content='no-referrer'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Eurth News Network - Yesterday's News Today</title>"
        f"<style>{css}</style>"
        f"<div class='paper'>"
        f"  <div class='topbar'>"
        f"    <span>Updated {today}</span>"
        f"    <a href='news.rss'>Subscribe</a>"
        f"  </div>"
        f"  <header class='masthead'>"
        f"    <h1>Eurth News Network</h1>"
        f"    <p class='tagline'>Yesterday's News Today</p>"
        f"  </header>"
        f"  <nav class='nav-strip'>"
        f"    <a href='{SITE}/c/affairs/17'>Affairs</a> &middot;"
        f"    <a href='{SITE}/c/business/18'>Business</a> &middot;"
        f"    <a href='{SITE}/c/conflict/19'>Confict</a> &middot;"
        f"    <a href='{SITE}/c/diplomacy/20'>Diplomacy</a> &middot;"
        f"    <a href='{SITE}/c/entertainment/21'>Entertainment</a>&middot;"
        f"    <a href='{SITE}/c/affairs/the-newsroom/36'>The Newsroom</a>&middot;"
        f"    <a href='news.rss'>RSS Feed</a>"
        f"  </nav>"
        f"  <div class='masonry'>"
        f"    {''.join(cards)}"
        f"  </div>"
        f"  <footer class='sitefoot'>"
        f"    <p class='logo'>Eurth News Network</p>"
        f"    <p class='links'><a href='news.rss'>RSS</a> &middot; "
        f"<a href='{SITE}'>Eurth.org</a> &middot; Navigation &middot; Terms</p>"
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
