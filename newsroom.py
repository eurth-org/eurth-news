#!/usr/bin/env python3
"""Rolling news feed: newest 25 stories (replies) in The Newsroom, category 36, on eurth.org.

Copyright © 2026 Eurth. All rights reserved. See LICENSE.
"""
import json, os, re, shutil, time, datetime
from html import escape as esc
from html.parser import HTMLParser
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

SITE = "https://eurth.org"
PAGE_URL = "https://news.eurth.org/"
CATEGORY = 36          # The Newsroom
LIMIT = 25
FRONT = 4              # lead story + "Also new" column
OUTDIR = "_site"

API_KEY = os.environ.get("DISCOURSE_API_KEY", "")
API_USER = os.environ.get("DISCOURSE_API_USERNAME", "system")
# Embedded Discourse discussion under each story page; needs news.eurth.org allowed in
# Admin > Advanced > Embedding on eurth.org first (see README).
EMBED_COMMENTS = os.environ.get("EMBED_COMMENTS") == "1"


def get_json(url):
    headers = {"User-Agent": "Eurth-Newsroom-Feed/1.0", "Accept": "application/json"}
    if API_KEY:
        headers["Api-Key"] = API_KEY
        headers["Api-Username"] = API_USER
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as r:
        return json.load(r)


def fix_images(cooked):
    """Strip Discourse's lightbox wrapper and meta row, keep bare <img>, lazy-load, no hotlink referer."""
    cooked = re.sub(
        r'<div class="lightbox-wrapper">\s*<a class="lightbox"[^>]*>\s*'
        r'(<img[^>]*>)\s*'
        r'<div class="meta">.*?</div>\s*</a>\s*</div>',
        r"\1",
        cooked,
        flags=re.DOTALL,
    )
    cooked = re.sub(r"<img\b(?![^>]*\bloading=)", '<img loading="lazy"', cooked)
    cooked = re.sub(r"(<img\b)", r'\1 referrerpolicy="no-referrer"', cooked)
    return cooked


def fix_urls(cooked):
    """Rewrite Discourse's relative /u/, /t/, /c/, /uploads/ URLs to absolute; links open in the same tab."""
    def repl(m):
        attr, q, url = m.group(1), m.group(2), m.group(3)
        if url.startswith(("http:", "https:", "//", "mailto:", "tel:", "javascript:", "data:", "#")):
            return m.group(0)
        if url.startswith("/"):
            return f"{attr}={q}{SITE}{url}{q}"
        return m.group(0)

    cooked = re.sub(r'\s+target=(["\'])_blank\1', "", cooked)
    return re.sub(r'\b(href|src)=(["\'])([^"\']*)\2', repl, cooked)


# --- Reading a story ---------------------------------------------------------
# Every agency formats its posts differently: banners, fake "Home | Politics |" menus,
# weather tickers, datelines. These helpers find the actual headline, standfirst and
# photo so the front page can present every agency the same way.

VOID = {"br", "img", "hr", "wbr", "input", "source", "meta", "link", "col", "area"}
BLOCK = {"p", "div", "li", "blockquote", "summary", "details", "h1", "h2", "h3", "h4", "h5", "h6",
         "td", "th", "tr", "table", "ul", "ol", "figcaption", "pre", "section", "center"}
SKIP = {"aside", "svg", "script", "style", "noscript"}

NAV = re.compile(r"^(home|menu)\b", re.I)
DATE_ONLY = re.compile(r"^[\W\d]*\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}[\W\d]*$")
BYLINE = re.compile(r"^(by|written by|words by|reporting by|photo|image|source|first published|"
                    r"last updated|published|updated|posted)\b[:\s]", re.I)
MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
DATELINE = re.compile(rf"\b\d{{1,2}}\s+{MONTH}\s+\d{{4}}\b|\b{MONTH}\s+\d{{1,2}},?\s+\d{{4}}\b", re.I)
STAMP = re.compile(r"\b(posted|updated|published)\s*(on)?\s*:|\bUTC\b", re.I)
GREETING = re.compile(r"^(hello|hi|good (morning|afternoon|evening|day)|welcome|greetings)\b", re.I)
RUNDOWN = re.compile(r"^((in|on|to|for)\s+)?(today|tonight|this)[^:]{0,25}:\s+", re.I)
SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[A-Z“\"‘'(])")
NOISE = {"text version", "summary", "advertisement", "latest news", "top stories", "read more"}
SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "of", "on",
               "or", "over", "the", "to", "vs", "with"}


class Lines(HTMLParser):
    """Flatten cooked HTML into text lines (with emphasis flags) and images, in reading order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.images, self.stack, self.buf, self.skip = [], [], [], [], 0

    def handle_starttag(self, tag, attrs):
        a = {k: v or "" for k, v in attrs}
        if tag in VOID:
            if tag in ("br", "hr"):
                self.flush()
            elif tag == "img" and not self.skip and "emoji" not in a.get("class", ""):
                try:
                    w, h = int(a.get("width") or 0), int(a.get("height") or 0)
                except ValueError:
                    w = h = 0
                self.images.append({"src": a.get("src", ""), "srcset": a.get("srcset", ""), "w": w, "h": h,
                                    "hint": a.get("alt", "") + " " + a.get("title", ""), "line": len(self.lines)})
            return
        cls, style = a.get("class", "").split(), a.get("style", "").replace(" ", "")
        flags = set()
        if tag in ("strong", "b") or "bbcode-b" in cls:
            flags.add("b")
        if tag in ("em", "i") or "bbcode-i" in cls:
            flags.add("em")
        if tag in ("small", "sub", "sup"):
            flags.add("small")
        if re.fullmatch(r"h[1-6]", tag):
            flags.add(tag)
        if tag == "a" and "mention" in cls:
            flags.add("mention")
        size = re.search(r"font-size:(\d+)%", style)
        if size and int(size.group(1)) >= 120:
            flags.add("big")
        elif size and int(size.group(1)) <= 90:
            flags.add("small")
        if tag in BLOCK:
            self.flush()
        skip = tag in SKIP or (tag == "div" and "meta" in cls)
        self.stack.append((tag, frozenset(flags), skip))
        self.skip += skip

    def handle_endtag(self, tag):
        if tag in VOID or all(t != tag for t, _, _ in self.stack):
            return
        while self.stack:
            t, _, skip = self.stack.pop()
            self.skip -= skip
            if t == tag:
                break
        if tag in BLOCK:
            self.flush()

    def handle_data(self, data):
        if self.skip or not data:
            return
        flags = frozenset().union(*(f for _, f, _ in self.stack))
        if "mention" in flags:
            data = data.lstrip("@").replace("_", " ")
        self.buf.append((data, flags))

    def flush(self):
        text = re.sub(r"\s+", " ", "".join(d for d, _ in self.buf)).strip()
        if text:
            sized = [(len(d.strip()), f) for d, f in self.buf if d.strip()]
            total = sum(n for n, _ in sized)
            share = lambda k: sum(n for n, f in sized if k in f) / total
            levels = [int(k[1]) for _, f in sized for k in f if re.fullmatch(r"h[1-6]", k)]
            self.lines.append({
                "text": text,
                "heading": min(levels) if levels else 0,
                "bold": share("b") > .85,
                "em": share("em") > .85,
                "big": share("big") > .5,
                "small": share("small") > .85,
            })
        self.buf = []


def norm(s):
    return re.sub(r"[\W_]", "", s.lower())


def is_noise(text, agency):
    """Menus, tickers, datelines, bylines and the agency's own name repeated as a banner."""
    t = text.strip(" |•·*-–—:✪⁕")
    n, a = norm(t), norm(agency)
    return (len(n) < 3 or text.count("|") >= 2 or bool(NAV.match(t)) or bool(DATE_ONLY.match(t))
            or bool(BYLINE.match(t)) or t.lower() in NOISE
            or bool(a) and (n == a or (len(n) > 4 and n in a) or (a in n and len(n) - len(a) <= 3)))


def title_case(t):
    out = []
    for i, w in enumerate(t.lower().split(" ")):
        small = i and w in SMALL_WORDS and not out[-1].endswith(":")
        out.append(w if small else re.sub(r"[^\W\d_]", lambda m: m.group(0).upper(), w, count=1))
    return " ".join(out)


def tidy(t):
    """Trim decoration and calm down ALL-CAPS headlines."""
    t = re.sub(r"\s+", " ", t).strip(" |•·*-–—:✪⁕")
    letters = [c for c in t if c.isalpha()]
    if len(letters) >= 6 and sum(c.isupper() for c in letters) / len(letters) > .8:
        t = title_case(t)
    return t


def clip(t, n):
    if len(t) <= n:
        return t
    return t[:n].rsplit(" ", 1)[0].rstrip(" ,;:–—-") + "…"


def is_photo(im):
    w, h = im["w"], im["h"]
    return (w >= 280 and h > 0 and .6 <= w / h <= 2.05 and im["src"].startswith("http")
            and not re.search(r"logo|banner|header|masthead", im["hint"] + im["src"], re.I))


def extract(cooked, agency):
    """Find a story's headline, section label, standfirst, lead photo and reading time."""
    p = Lines()
    p.feed(cooked)
    p.close()
    p.flush()
    lines = p.lines

    # Headline: the first prominent line (heading, bold or enlarged) that isn't decoration.
    # A one- or two-word line before it ("BREAKING", "Politics") becomes the section label.
    label, head, at, body = "", "", None, 0
    for i, ln in enumerate(lines):
        t = ln["text"]
        if is_noise(t, agency):
            continue
        if ln["heading"] or (ln["bold"] or ln["big"]) and not ln["small"]:
            if not label and len(t.split()) <= 2 and len(t) <= 30:
                label, at = t, i
                continue
            head, at = t, i
            break
        if len(t) >= 100:
            body += 1
            if body == 2:      # two paragraphs in: anything bold after this is a subheading
                break
    if not head and label:
        head, label = label, ""

    # No headline styling at all: lead with the first sentence of the first real paragraph,
    # skipping broadcast greetings and keeping a speaker line ("Edric Kageni:") in front.
    rest, fallback = "", False
    if not head:
        speaker = ""
        for i, ln in enumerate(lines):
            t = ln["text"]
            if is_noise(t, agency):
                continue
            if t.endswith(":") and len(t.split()) <= 4:
                speaker = t
                continue
            if len(t) >= 40 and not GREETING.match(t):
                head, *more = SENTENCE.split(RUNDOWN.sub("", t), maxsplit=1)
                head, rest, at, fallback = f"{speaker} {head}".strip(), (more[0] if more else ""), i, True
                break
            speaker = ""

    # Standfirst: an italic line right under the headline, else the first real paragraph.
    dek = rest if len(rest) >= 40 else ""
    if not dek and at is not None:
        first = True
        for ln in lines[at + 1:]:
            t = ln["text"]
            if is_noise(t, agency) or t == head or STAMP.search(t) or (len(t) < 90 and DATELINE.search(t)):
                continue
            if (len(t) >= 60 and not ln["heading"]) or (first and ln["em"] and len(t) >= 20):
                dek = t
                break
            first = False

    # Lead photo: photo-shaped, not a logo or banner, ideally below the headline.
    photos = [im for im in p.images if is_photo(im)]
    below = [im for im in photos if at is None or im["line"] > at]
    image = (below or photos or [None])[0]
    if image and not all(u.strip().startswith("http") for u in image["srcset"].split(",") if u.strip()):
        image["srcset"] = ""

    words = sum(len(ln["text"].split()) for ln in lines)
    return {
        "headline": clip(tidy(head), 110 if fallback else 140),
        "label": clip(tidy(label), 30),
        "dek": clip(re.sub(r"\s+", " ", dek).strip(), 260),
        "image": image,
        "minutes": max(1, round(words / 230)),
    }


def short_agency(t):
    """'[CNA] Charkov News Agency' -> 'Charkov News Agency', 'Roiters » Know. Now' -> 'Roiters'."""
    s = re.sub(r"^\s*\[[^\]]*\]\s*", "", t)
    s = re.split(r"\s+[|»–—-]\s+", s)[0]
    return re.sub(r"^[^\w(]+", "", s).strip() or t


def avatar_url(template):
    if not template:
        return ""
    url = template.replace("{size}", "48")
    return SITE + url if url.startswith("/") else url


def fetch_stories():
    q = quote(f"category:{CATEGORY} in:replies order:latest")
    data = get_json(f"{SITE}/search.json?q={q}")
    hits = data.get("posts", [])[:LIMIT]
    topics = {t["id"]: t for t in data.get("topics", [])}

    stories = []
    for p in hits:
        tid = p.get("topic_id", 0)
        topic = topics.get(tid, {})

        try:
            detail = get_json(f"{SITE}/posts/{p['id']}.json")
        except Exception:
            detail = {}

        slug = detail.get("topic_slug") or topic.get("slug") or "-"
        agency = (
            topic.get("title")
            or detail.get("topic_title")
            or p.get("topic_title")
            or slug.replace("-", " ").title()
            or "News"
        )

        cooked = fix_urls(fix_images(detail.get("cooked") or p.get("cooked") or ""))
        story = extract(cooked, agency)
        if not story["headline"]:
            story["headline"] = clip(p.get("blurb") or agency, 140)
        author = detail.get("username") or p.get("username", "")

        stories.append({
            **story,
            "id":      p["id"],
            "agency":  agency,
            "author":  author,
            "nation":  "eurth.org" if author == "system" else author.replace("_", " "),
            "avatar":  avatar_url(detail.get("avatar_template") or p.get("avatar_template")),
            "readers": detail.get("readers_count") or 0,
            "date":    detail.get("created_at") or p.get("created_at", ""),
            "cooked":  cooked,
            "url":     f"{SITE}/t/{slug}/{tid}/{p.get('post_number')}",
        })
        time.sleep(0.3)
    return stories


def parse_date(iso):
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def fmt_date(iso):
    try:
        dt = parse_date(iso)
        return f"{dt.day} {dt:%b %Y}"
    except Exception:
        return iso


def rss_date(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def build_rss(items):
    now = datetime.datetime.now(datetime.timezone.utc)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>',
        "<title>Eurth News Network - Yesterday's News Today</title>",
        f"<link>{SITE}/c/affairs/the-newsroom/36</link>",
        f'<atom:link href="{PAGE_URL}news.rss" rel="self" type="application/rss+xml"/>',
        "<description>Rolling feed of the 25 newest news stories in The Newsroom</description>",
        "<language>en</language>",
        f"<copyright>{escape(RIGHTS)} Stories © their authors.</copyright>",
        f"<lastBuildDate>{rss_date(now)}</lastBuildDate>",
    ]
    for s in items:
        lines += [
            "<item>",
            f"<title>{escape(s['headline'])}</title>",
            f"<link>{escape(s['url'])}</link>",
            f'<guid isPermaLink="true">{escape(s["url"])}</guid>',
            f"<pubDate>{rss_date(parse_date(s['date']))}</pubDate>",
            f"<dc:creator>{escape(s['nation'])}</dc:creator>",
            f"<category>{escape(s['agency'])}</category>",
            f"<description>{escape(s['cooked'])}</description>",
            "</item>",
        ]
    lines += ["</channel></rss>"]
    return "\n".join(lines)


# --- Pages -------------------------------------------------------------------
# Styled after the Eurth design system: forum light and Solarized night themes, plus "Orioni mode"
# newsprint; Libre Baskerville for headlines, Helvetica for labels and text, JetBrains Mono for dates.
# The page frame is Eurth's own (OOC); the stories inside keep their agencies' words, never their
# branding. Built to WCAG 2.2 AAA: 7:1 text contrast in every theme and state, 44px targets, motion
# that stops by itself and never runs for visitors who ask for reduced motion.

FONTS = ("https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400"
         "&family=JetBrains+Mono:wght@400;700&display=swap")

MENU = [("Top stories", "top"), ("More stories", "more"), ("Most read", "most-read"), ("Nations", "nations")]

ICONS = (  # Font Awesome "bars" and "xmark", the forum's icon set
    "<svg class='i-bars' viewBox='0 0 448 512' aria-hidden='true'><path d='M0 96C0 78.3 14.3 64 32 64H416c17.7 0 32 "
    "14.3 32 32s-14.3 32-32 32H32C14.3 128 0 113.7 0 96zM0 256c0-17.7 14.3-32 32-32H416c17.7 0 32 14.3 32 32s-14.3 32-32 "
    "32H32c-17.7 0-32-14.3-32-32zM448 416c0 17.7-14.3 32-32 32H32c-17.7 0-32-14.3-32-32s14.3-32 32-32H416c17.7 0 32 14.3 "
    "32 32z'/></svg>"
    "<svg class='i-close' viewBox='0 0 384 512' aria-hidden='true'><path d='M342.6 150.6c12.5-12.5 12.5-32.8 0-45.3s-32.8"
    "-12.5-45.3 0L192 210.7 86.6 105.4c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3L146.7 256 41.4 361.4c-12.5 12.5-12.5 "
    "32.8 0 45.3s32.8 12.5 45.3 0L192 301.3 297.4 406.6c12.5 12.5 32.8 12.5 45.3 0s12.5-32.8 0-45.3L237.3 256 342.6 "
    "150.6z'/></svg>"
)

# Sun and moon from line-md by Vjacheslav Trushkin (MIT), as in Deluminator: they draw themselves once
# per switch (no endless spinning or twinkling); the "-still" versions are for reduced motion.
CRESCENT = ("M7 6 C7 12.08 11.92 17 18 17 C18.53 17 19.05 16.96 19.56 16.89 C17.95 19.36 15.17 21 12 21 "
            "C7.03 21 3 16.97 3 12 C3 8.83 4.64 6.05 7.11 4.44 C7.04 4.95 7 5.47 7 6 Z")
STARS = ("m15.22 6.03l2.53-1.94L14.56 4L13.5 1l-1.06 3l-3.19.09l2.53 1.94l-.91 3.06l2.63-1.81l2.63 1.81z",
         "M19.61 12.25L21.25 11l-2.06-.05L18.5 9l-.69 1.95l-2.06.05l1.64 1.25l-.59 1.98l1.7-1.17l1.7 1.17z")
RAYS = ("M12 21v1M21 12h1M12 3v-1M3 12h-1", "M18.5 18.5l0.5 0.5M18.5 5.5l0.5 -0.5M5.5 5.5l-0.5 -0.5M5.5 18.5l-0.5 0.5")
SVG = "<svg viewBox='0 0 24 24' aria-hidden='true' focusable='false'>"
THEME_ICONS = (
    "<template id='i-sun'>" + SVG +
    "<g fill='none' stroke='currentColor' stroke-linecap='round' stroke-width='2'>"
    "<path stroke-dasharray='34' stroke-dashoffset='34' d='M12 7C14.76 7 17 9.24 17 12C17 14.76 14.76 17 12 17C9.24 17 7 "
    "14.76 7 12C7 9.24 9.24 7 12 7'><animate fill='freeze' attributeName='stroke-dashoffset' dur='0.4s' values='34;0'/></path>"
    "<g stroke-dasharray='2' stroke-dashoffset='2'><path d='M0 0'><animate fill='freeze' attributeName='d' begin='0.5s' "
    f"dur='0.2s' values='M12 19v1M19 12h1M12 5v-1M5 12h-1;{RAYS[0]}'/><animate fill='freeze' "
    "attributeName='stroke-dashoffset' begin='0.5s' dur='0.2s' values='2;0'/></path><path d='M0 0'><animate fill='freeze' "
    "attributeName='d' begin='0.7s' dur='0.2s' values='M17 17l0.5 0.5M17 7l0.5 -0.5M7 7l-0.5 -0.5M7 17l-0.5 0.5;"
    f"{RAYS[1]}'/><animate fill='freeze' attributeName='stroke-dashoffset' begin='0.7s' dur='0.2s' values='2;0'/></path>"
    "</g></g></svg></template>"
    "<template id='i-moon'>" + SVG +
    "<g fill='none' stroke='currentColor' stroke-linecap='round' stroke-linejoin='round' stroke-width='2'>"
    f"<g stroke-dasharray='2'><path d='{RAYS[0]}'><animate fill='freeze' attributeName='stroke-dashoffset' dur='0.2s' "
    f"values='4;2'/></path><path d='{RAYS[1]}'><animate fill='freeze' attributeName='stroke-dashoffset' begin='0.2s' "
    f"dur='0.2s' values='4;2'/></path></g><path d='{CRESCENT}' opacity='0'><set attributeName='opacity' begin='0.5s' "
    "to='1'/></path></g><g fill='currentColor' fill-opacity='0'>"
    f"<path d='{STARS[0]}'><animate fill='freeze' attributeName='fill-opacity' begin='0.6s' dur='0.4s' values='0;1'/></path>"
    f"<path d='{STARS[1]}'><animate fill='freeze' attributeName='fill-opacity' begin='0.9s' dur='0.4s' values='0;1'/></path>"
    "</g><mask id='enn-moon'><circle cx='12' cy='12' r='12' fill='#fff'/><circle cx='12' cy='12' r='4'><animate "
    "fill='freeze' attributeName='r' begin='0.1s' dur='0.4s' values='4;8'/></circle><circle cx='22' cy='2' r='3' "
    "fill='#fff'><animate fill='freeze' attributeName='cx' begin='0.1s' dur='0.4s' values='22;18'/><animate fill='freeze' "
    "attributeName='cy' begin='0.1s' dur='0.4s' values='2;6'/><animate fill='freeze' attributeName='r' begin='0.1s' "
    "dur='0.4s' values='3;12'/></circle><circle cx='22' cy='2' r='1'><animate fill='freeze' attributeName='cx' "
    "begin='0.1s' dur='0.4s' values='22;18'/><animate fill='freeze' attributeName='cy' begin='0.1s' dur='0.4s' "
    "values='2;6'/><animate fill='freeze' attributeName='r' begin='0.1s' dur='0.4s' values='1;10'/></circle></mask>"
    "<circle cx='12' cy='12' r='6' fill='currentColor' mask='url(#enn-moon)'><set attributeName='opacity' begin='0.5s' "
    "to='0'/><animate fill='freeze' attributeName='r' begin='0.1s' dur='0.4s' values='6;10'/></circle></svg></template>"
    "<template id='i-auto'>" + SVG +
    "<circle cx='12' cy='12' r='9' fill='none' stroke='currentColor' stroke-width='2' stroke-dasharray='57' "
    "stroke-dashoffset='57'><animate fill='freeze' attributeName='stroke-dashoffset' dur='0.4s' values='57;0'/></circle>"
    "<path d='M12 3a9 9 0 0 0 0 18z' fill='currentColor' opacity='0'><animate fill='freeze' attributeName='opacity' "
    "begin='0.4s' dur='0.25s' values='0;1'/></path></svg></template>"
    "<template id='i-auto-still'>" + SVG +
    "<circle cx='12' cy='12' r='9' fill='none' stroke='currentColor' stroke-width='2'/>"
    "<path d='M12 3a9 9 0 0 0 0 18z' fill='currentColor'/></svg></template>"
    "<template id='i-sun-still'>" + SVG +
    "<g fill='none' stroke='currentColor' stroke-linecap='round' stroke-width='2'><circle cx='12' cy='12' r='5'/>"
    f"<path d='{RAYS[0]}{RAYS[1]}'/></g></svg></template>"
    "<template id='i-moon-still'>" + SVG +
    f"<path d='{CRESCENT}' fill='none' stroke='currentColor' stroke-linecap='round' stroke-linejoin='round' "
    f"stroke-width='2'/><g fill='currentColor'><path d='{STARS[0]}'/><path d='{STARS[1]}'/></g></svg></template>"
)

THEME_BUTTON = ("<button type='button' class='theme-btn js-only' id='theme' aria-label='Theme' title='Theme'>"
                "<span class='theme-icon' aria-hidden='true'></span></button>")

SECONDS_BUTTON = ("<button type='button' class='secs-btn js-only' id='secs' aria-pressed='true' aria-label='Show seconds' "
                  "title='Show seconds'>" + SVG + "<g fill='none' stroke='currentColor' stroke-width='2' "
                  "stroke-linecap='round'><circle cx='12' cy='13' r='8'/><path d='M12 9v4l2.5 2M10 2h4M19 6l1.5-1.5'/></g>"
                  "</svg></button>")

SEARCH = ("<div class='search js-only' role='search'><label class='sr' for='q'>Search stories</label>"
          "<svg class='search-i' viewBox='0 0 512 512' aria-hidden='true' focusable='false'><path d='M416 208c0 45.9-14.9 "
          "88.3-40 122.7L502.6 457.4c12.5 12.5 12.5 32.8 0 45.3s-32.8 12.5-45.3 0L330.7 376c-34.4 25.2-76.8 40-122.7 40C93.1 "
          "416 0 322.9 0 208S93.1 0 208 0S416 93.1 416 208zM208 352a144 144 0 1 0 0-288 144 144 0 1 0 0 288z'/></svg>"
          "<input id='q' type='search' placeholder='Search headlines, agencies, nations' autocomplete='off'>"
          "<kbd aria-hidden='true'>/</kbd></div>")

SHARE_CARD = (f"{PAGE_URL}static/share-card.jpg", 1200, 800,
              "Eurth News Network: yesterday's news today, from the nations of Eurth")
DESCRIPTION = ("Yesterday's news today: the newest stories from the nations of Eurth, the Worldbuilding & "
               "Roleplay Writing Community. Every story is fiction, written by its members.")

OWNER, SINCE = "Eurth", 2026
YEARS = str(SINCE) if datetime.date.today().year <= SINCE else f"{SINCE}–{datetime.date.today().year}"
RIGHTS = f"© {YEARS} {OWNER}. All rights reserved."

FOOTER_NAV = [  # (name, where it lives, link)
    ("Forums", "eurth.org", f"{SITE}/"),
    ("Map", "map.eurth.org", "https://map.eurth.org/"),
    ("Governmint", "gov.eurth.org", "https://gov.eurth.org/"),
    ("Uptime", "status.eurth.org", "https://status.eurth.org/"),
    ("The Newsroom", "eurth.org", f"{SITE}/c/affairs/the-newsroom/36"),
    ("Guidelines", "eurth.org", f"{SITE}/guidelines"),
]

# Theme surfaces for the browser's own chrome (address bar), set before the page paints.
CHROME = {"light": "#ffffff", "paper": "#fcf6e1", "dark": "#002b36"}

HEAD_SCRIPT = """(function(){var d=document.documentElement,m=window.matchMedia,t=null,p=null;
try{t=localStorage.getItem("enn:theme");p=localStorage.getItem("enn:paper")}catch(e){}
var dark=t==="dark"||(t!=="light"&&!!m&&m("(prefers-color-scheme: dark)").matches);
d.setAttribute("data-theme",dark?"dark":"light");if(p==="1")d.setAttribute("data-paper","");
d.className+=" js"+(m&&m("(prefers-reduced-motion: reduce)").matches?"":" anim");
var c=document.getElementById("theme-color");if(c)c.setAttribute("content",dark?"%s":p==="1"?"%s":"%s")})();""" % (
    CHROME["dark"], CHROME["paper"], CHROME["light"])

DARK = ("color-scheme:dark;--surface:#002b36;--surface-raised:#0a3a46;--line:#1f4a55;--line-strong:#8fa29d;"
        "--ink:#fcf6e1;--ink-muted:#c6d1cb;--accent-text:#a3d8f5;--highlight:#f2f481;--on-highlight:#002b36;"
        "--shade:rgba(0,0,0,.65)")

CSS = """
:root{color-scheme:light;
  --eurth-blue:#2698d4;--night:#002b36;--parchment:#fcf6e1;
  --surface:#ffffff;--surface-raised:#f6f6f6;--line:#e4e4e4;--line-strong:#6b6b6b;--ink:#222222;--ink-muted:#4f4f4f;
  --accent-text:#0a4b74;--highlight:#ffff4d;--on-highlight:#222222;--shade:rgba(0,43,54,.6);
  --radius-sm:2px;--radius-md:12px;--radius-avatar:10%;--bar-h:60px;--ease:cubic-bezier(.2,.7,.2,1);
  --serif:"Libre Baskerville",Baskerville,Georgia,serif;
  --sans:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,Menlo,monospace}
/* Orioni mode: newsprint parchment, in the light theme only */
:root[data-paper]:not([data-theme=dark]){--surface:#fcf6e1;--surface-raised:#f2e9cf;--line:#e2d6b5;--line-strong:#7a705c;
  --ink-muted:#4d473d}
:root[data-theme=dark]{@@DARK@@}
@media (prefers-color-scheme:dark){:root:not([data-theme]){@@DARK@@}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-top:calc(var(--bar-h) + 16px)}
body{margin:0;background:var(--surface);color:var(--ink);font:16px/1.5 var(--sans)}
[hidden]{display:none!important}
html:not(.js) .js-only{display:none!important}
a{color:inherit}
abbr[title]{text-decoration:none}
:focus-visible{outline:2px solid var(--accent-text);outline-offset:2px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.skip{position:absolute;left:-999px;top:.5em;z-index:5;background:var(--ink);color:var(--surface);padding:12px 16px}
.skip:focus{left:.5em}
.paper{max-width:1280px;margin:0 auto;padding:0 2em 2.5em}
.tap{display:inline-flex;align-items:center;justify-content:center;min-width:44px;min-height:44px}

/* The globe: a 240-frame strip that turns for a few seconds, then rests; hover or focus turns it again */
.orb{display:block;flex:none;width:var(--s);height:var(--s);background:0 0/var(--s) auto no-repeat;
  animation:orb 9.6s steps(240) infinite paused}
.spin .orb,.orb-link:hover .orb,.orb-link:focus-visible .orb{animation-play-state:running}
@keyframes orb{to{background-position:0 calc(var(--s) * -240)}}

.topbar{display:flex;justify-content:space-between;align-items:center;gap:0 16px;flex-wrap:wrap;border-bottom:1px solid var(--line);
  font:13px/20px var(--mono);color:var(--ink-muted)}
.topbar>div{display:flex;align-items:center;gap:0 12px;flex-wrap:wrap}
.topbar a{color:var(--ink);text-underline-offset:3px}
#clock{display:inline-block;font-variant-numeric:tabular-nums}
#clock.dim .sep{visibility:hidden}
.secs-btn{display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;margin:0 -8px 0 -4px;padding:0;
  border:0;border-radius:999px;background:transparent;color:var(--ink-muted);cursor:pointer}
.secs-btn svg{width:18px;height:18px}
.secs-btn[aria-pressed=true]{color:var(--ink)}
.secs-btn[aria-pressed=true] svg{background:var(--surface-raised);border-radius:999px;box-shadow:0 0 0 4px var(--surface-raised)}
.secs-btn:hover{color:var(--ink)}
.toast{position:fixed;left:50%;bottom:24px;z-index:6;max-width:calc(100vw - 32px);margin:0;padding:10px 16px;
  font:15px/22px var(--sans);color:var(--surface);background:var(--ink);border-radius:var(--radius-md);
  opacity:0;transform:translate(-50%,8px);pointer-events:none;transition:opacity .25s,transform .25s var(--ease)}
.toast.show{opacity:1;transform:translate(-50%,0)}
.theme-btn{display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;margin:4px 0;padding:0;
  border:1px solid var(--line-strong);border-radius:999px;background:transparent;color:var(--ink);cursor:pointer;
  transition:background-color .2s,transform .15s}
.theme-btn:hover{background:var(--surface-raised)}
.theme-btn:active{transform:scale(.92)}
.theme-icon,.theme-icon svg{display:block;width:22px;height:22px}
.masthead{position:relative;text-align:center;padding:1.2em .5em 1.1em}
.masthead::after{content:"";position:absolute;left:0;right:0;bottom:0;border-bottom:4px double var(--ink)}
.masthead .title{display:block;margin:0;font:400 clamp(2em,6.4vw,4em)/1.08 var(--serif);letter-spacing:-.01em;
  text-decoration:none;text-wrap:balance}
.tagline{font:italic 1.05em/1.4 var(--serif);color:var(--ink-muted);margin:.5em 0 0}
.masthead.slim{padding:.9em .5em .8em}
.masthead.slim .title{font-size:clamp(1.5em,4vw,2.25em)}

.bar{position:sticky;top:0;z-index:4;background:var(--surface);border-bottom:1px solid var(--ink)}
html:not(.js) .bar{position:static}
.bar-in{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);align-items:center;gap:16px;min-height:var(--bar-h)}
.brand{justify-self:start;display:inline-flex;align-items:center;gap:10px;min-height:44px;font:400 1.15em/1.2 var(--serif);
  text-decoration:none;white-space:nowrap;visibility:hidden;opacity:0;transform:translateX(-8px);
  transition:opacity .3s,transform .3s var(--ease),visibility .3s}
.bar.stuck .brand{visibility:visible;opacity:1;transform:none}
.panel{display:contents}
.menu{display:flex;justify-content:center;flex-wrap:wrap;gap:0 26px}
.menu a{position:relative;display:inline-flex;align-items:center;min-height:44px;font:700 14px/20px var(--sans);text-decoration:none}
.menu a::after{content:"";position:absolute;left:0;right:0;bottom:8px;height:2px;background:var(--accent-text);
  transform:scaleX(0);transform-origin:left;transition:transform .25s var(--ease)}
.menu a:hover::after,.menu a:focus-visible::after{transform:scaleX(1)}
.menu-btn{display:none}
.search{position:relative;justify-self:end;width:100%;max-width:340px}
.search-i{position:absolute;left:13px;top:50%;width:16px;height:16px;transform:translateY(-50%);fill:var(--ink-muted);
  pointer-events:none}
.search input{width:100%;min-height:44px;font:15px/20px var(--sans);padding:10px 44px 10px 38px;background:var(--surface);
  color:var(--ink);border:1px solid var(--line-strong);border-radius:var(--radius-sm);-webkit-appearance:none;appearance:none}
.search input::placeholder{color:var(--ink-muted);opacity:1}
.search kbd{position:absolute;right:10px;top:50%;transform:translateY(-50%);font:12px/1 var(--mono);color:var(--ink-muted);
  border:1px solid var(--line-strong);border-radius:var(--radius-sm);padding:3px 6px;pointer-events:none}
.search input:focus+kbd,.search input:not(:placeholder-shown)+kbd{display:none}

.toolbar{padding:12px 0;border-bottom:1px solid var(--line)}
.edition{margin:0;font-size:14px;line-height:20px;color:var(--ink-muted)}
.edition strong,.new-count{color:var(--ink)}
.filter-note{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:20px 0 0;font-size:15px}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:44px;font:700 14px/20px var(--sans);color:var(--ink);
  background:transparent;border:1px solid var(--line-strong);border-radius:var(--radius-sm);padding:10px 16px;cursor:pointer;
  text-decoration:none;transition:background-color .15s,border-color .15s,transform .15s}
.btn:hover:not(:disabled){background:var(--surface-raised);border-color:var(--ink)}
.btn:active:not(:disabled){transform:scale(.97)}
.btn:disabled{opacity:.45;cursor:default}
.cta{display:inline-flex;align-items:center;min-height:44px;font:700 19px/24px var(--sans);color:var(--night);
  background:var(--eurth-blue);border-radius:var(--radius-md);padding:10px 20px;text-decoration:none;white-space:nowrap;
  transition:background-color .15s,color .15s,transform .15s}
.cta:hover{background:#0a4b74;color:#fff}
.cta:active{transform:scale(.97)}

.kicker{margin:0 0 8px;font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink-muted)}
.kicker .label{color:var(--ink)}
.is-new .kicker::before,.is-read .kicker::before{display:inline-block;margin-right:8px;padding:1px 6px;border-radius:var(--radius-sm)}
.is-new .kicker::before{content:"New" / "New: ";background:var(--highlight);color:var(--on-highlight)}
.is-read .kicker::before{content:"Read" / "Already read: ";padding:0 5px;border:1px solid var(--line-strong)}
.hl{font:400 1.15em/1.35 var(--serif);margin:0 0 8px;text-wrap:balance}
.hl a{text-decoration:none}
.hl a:hover,.card:hover .hl a,.side:hover .hl a{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:.18em}
.is-read .hl a{color:var(--ink-muted)}
.dek{margin:0 0 12px;font-size:15px;line-height:22px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;
  overflow:hidden}
.meta{margin:auto 0 0;font:13px/20px var(--mono);color:var(--ink-muted);display:flex;align-items:center;flex-wrap:wrap;gap:2px 8px}
.av{width:18px;height:18px;border-radius:var(--radius-avatar);object-fit:cover;background:var(--surface-raised);flex:none}
.nation{color:var(--ink);font-weight:700}
.thumb{aspect-ratio:3/2;overflow:hidden;background:var(--surface-raised);border-radius:var(--radius-sm);margin:0 0 12px}
.thumb img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .6s var(--ease)}

.front{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:0 36px;padding:32px 0;border-bottom:4px double var(--ink)}
.lead{position:relative}
.lead .thumb{aspect-ratio:2/1;margin-bottom:16px}
.lead .kicker{font-size:14px;line-height:20px}
.lead .hl{font-size:clamp(1.75em,3.1vw,2.5em);line-height:1.2;margin-bottom:12px}
.lead .dek{font:400 1.1em/1.65 var(--serif);-webkit-line-clamp:5;margin-bottom:16px}
.lead .meta{margin-bottom:20px}
.latest{border-left:1px solid var(--line);padding-left:36px}
.col-h{font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;margin:0 0 16px;padding-bottom:10px;
  border-bottom:1px solid var(--ink)}
.side{position:relative;display:grid;grid-template-columns:minmax(0,1fr);column-gap:16px;padding:0 0 16px;margin:0 0 16px;
  border-bottom:1px solid var(--line)}
.side:last-child{border-bottom:0;margin-bottom:0;padding-bottom:0}
.side.has-thumb{grid-template-columns:minmax(0,1fr) 92px}
.side>*{grid-column:1}
.side .thumb{grid-column:2;grid-row:1/span 3;aspect-ratio:1;margin:0}
.side .hl{font-size:1.05em}
.side:hover .thumb img{transform:scale(1.05)}
.card .hl a::after,.side .hl a::after,.lead .hl a::after{content:"";position:absolute;inset:0}
.lead .btn{position:relative;z-index:1}
.lead:hover .hl a{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:.18em}
.lead:hover .thumb img{transform:scale(1.02)}

.body-grid{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:36px;margin-top:32px}
.group-h{display:flex;align-items:center;gap:12px;font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;
  margin:0 0 20px}
.group-h::after{content:"";flex:1;border-top:1px solid var(--ink)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(235px,1fr));gap:24px 36px;margin-bottom:40px}
.card{position:relative;display:flex;flex-direction:column;padding:16px;margin:0 -16px;border:1px solid transparent;
  border-top-color:var(--line);border-radius:var(--radius-sm);
  transition:background-color .2s ease,border-color .2s ease,box-shadow .2s ease}
.card:hover,.card:focus-within{background:var(--surface-raised);border-color:var(--line-strong);
  border-top-color:var(--accent-text);box-shadow:inset 0 2px 0 var(--accent-text)}
.card:hover .thumb img{transform:scale(1.04)}
.card:not(.has-thumb) .dek{-webkit-line-clamp:9}
.filtering .front,.filtering .group-h{display:none}
.empty{padding:32px 0;text-align:center;color:var(--ink-muted)}

.rail{border-left:1px solid var(--line);padding-left:36px;align-self:start;position:sticky;top:calc(var(--bar-h) + 16px)}
.rail section{margin-bottom:40px}
.mostread{list-style:none;margin:0;padding:0}
.mostread li{position:relative;display:grid;grid-template-columns:28px minmax(0,1fr);gap:8px;padding:12px 0;
  border-bottom:1px solid var(--line)}
.mostread li:first-child{padding-top:0}
.mostread .num{font:400 1.6em/1 var(--serif);color:var(--accent-text)}
.mostread a{font:400 1em/1.4 var(--serif);text-decoration:none}
.mostread a:hover{text-decoration:underline}
.mostread a::after{content:"";position:absolute;inset:0}
.mostread .sub{display:block;font:13px/20px var(--mono);color:var(--ink-muted);margin-top:6px}
.meter{display:block;height:3px;margin-top:8px;background:var(--line);border-radius:2px;overflow:hidden}
.meter i{display:block;width:var(--w);height:100%;background:var(--accent-text);transform-origin:left}
.nations{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:8px}
.nations button{display:inline-flex;align-items:center;gap:8px;min-height:44px;font:14px/20px var(--sans);color:var(--ink);
  padding:6px 12px 6px 8px;border:1px solid var(--line-strong);border-radius:var(--radius-sm);background:transparent;
  cursor:pointer;transition:background-color .15s,transform .15s}
.nations button:hover{border-color:var(--ink);background:var(--surface-raised)}
.nations button:active{transform:scale(.96)}
.nations button[aria-pressed=true]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.nations .n{font-family:var(--mono);color:var(--ink-muted)}
.nations button[aria-pressed=true] .n{color:inherit}

.sitefoot{text-align:center;border-top:4px double var(--ink);margin-top:16px;padding-top:24px}
.sitefoot .title{font:400 1.6em/1.2 var(--serif);margin:0 0 8px}
.sitefoot p{font-size:15px;line-height:24px;color:var(--ink-muted);margin:8px auto;max-width:46em}
.elsewhere ul{list-style:none;display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:4px 12px;
  max-width:980px;margin:20px auto;padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.elsewhere a{display:flex;flex-direction:column;justify-content:center;min-height:44px;padding:6px 8px;text-decoration:none;
  border-radius:var(--radius-sm);transition:background-color .15s}
.elsewhere a:hover{background:var(--surface-raised)}
.elsewhere .n{font:700 15px/20px var(--sans);color:var(--accent-text)}
.elsewhere a:hover .n{text-decoration:underline}
.elsewhere .d{font:13px/20px var(--mono);color:var(--ink-muted)}
.sitefoot .legal{font-size:13px;line-height:20px;margin-top:16px}
.paper-row{display:flex;justify-content:center;align-items:center;gap:8px 12px;flex-wrap:wrap}
.paper-btn::before{content:"";width:14px;height:14px;margin-right:10px;border-radius:var(--radius-sm);background:var(--parchment);
  border:1px solid var(--line-strong)}
.paper-btn[aria-pressed=true]{background:var(--ink);color:var(--surface);border-color:var(--ink)}

#reader{padding:0;border:0;width:min(800px,100vw);max-width:100vw;height:100vh;height:100dvh;max-height:100dvh;margin:0 auto;
  background:var(--surface);color:var(--ink)}
#reader::backdrop{background:var(--shade)}
.r-scroll{height:100%;overflow:auto;overscroll-behavior:contain}
.r-bar{position:sticky;top:0;z-index:1;display:flex;align-items:center;gap:8px;padding:8px clamp(16px,4vw,40px);
  background:var(--surface);border-bottom:1px solid var(--line)}
.r-pos{margin-left:auto;margin-right:6px;font:13px/20px var(--mono);color:var(--ink-muted)}
.r-article{padding:28px clamp(18px,6vw,56px) 48px}
.r-article .kicker{font-size:14px;line-height:20px}
.r-title{font:400 clamp(1.65em,4.2vw,2.5em)/1.22 var(--serif);margin:4px 0 14px;text-wrap:balance}
.r-meta{padding-bottom:16px;margin-bottom:12px;border-bottom:1px solid var(--line)}
.r-source{font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink-muted);margin:0 0 24px}
.r-foot{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:40px;padding-top:20px;border-top:4px double var(--ink)}
html.reading{overflow:hidden}
.prose{max-width:68ch;font:17px/1.6 var(--sans);overflow-wrap:anywhere}
.prose p,.prose ul,.prose ol,.prose blockquote,.prose table,.prose details,.prose pre{margin:0 0 2.4em}
.prose img{max-width:100%;height:auto}
.prose img.emoji{width:1.2em;height:1.2em;vertical-align:-.2em}
.prose h1,.prose h2,.prose h3,.prose h4,.prose h5{font-family:var(--serif);font-weight:400;line-height:1.3;margin:1.4em 0 .6em}
.prose h1{font-size:1.5em}.prose h2{font-size:1.3em}.prose h3{font-size:1.15em}
.prose .anchor{display:none}
.prose a{color:var(--accent-text);text-decoration:underline;text-underline-offset:.15em}
.prose blockquote{padding:0 0 0 1.1em;border-left:3px solid var(--line-strong)}
.prose hr{border:0;border-top:1px solid var(--line);margin:1.6em 0}
.prose table{border-collapse:collapse;display:block;max-width:100%;overflow-x:auto;font-size:.9em}
.prose td,.prose th{border:1px solid var(--line-strong);padding:6px 10px}
.prose pre{background:var(--surface-raised);padding:12px;overflow:auto;border-radius:var(--radius-sm)}
.prose code{font-family:var(--mono);font-size:.9em;background:var(--surface-raised);padding:1px 4px}
.prose details{border:1px solid var(--line-strong);border-radius:var(--radius-sm);padding:8px 14px}
.prose summary{min-height:44px;display:flex;align-items:center;cursor:pointer}
.prose aside.onebox{border:1px solid var(--line-strong);border-radius:var(--radius-sm);padding:12px;margin:0 0 1.6em;font-size:.85em}
/* Every agency is shown the same way, and every theme keeps 7:1: their own colours give way to ours */
.prose [style*=color]{color:inherit!important}
.prose [style*=background]{background:none!important}
.prose [style*=justify]{text-align:start!important}

.story-page{max-width:800px;margin:0 auto}
.story-page .r-article{padding:16px 0 8px}
.crumbs ol{list-style:none;display:flex;flex-wrap:wrap;align-items:center;gap:0 8px;margin:0 0 8px;padding:0;
  font:13px/20px var(--mono);color:var(--ink-muted)}
.crumbs li+li::before{content:"/";margin-right:8px}
.crumbs a{display:inline-flex;align-items:center;min-height:44px;color:var(--ink);text-underline-offset:3px}
.pager{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:32px 0 8px;padding-top:20px;border-top:1px solid var(--line)}
.pager a{display:block;min-height:44px;text-decoration:none}
.pager .k{display:block;font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink-muted);margin-bottom:6px}
.pager .t{font:400 1.05em/1.4 var(--serif)}
.pager a:hover .t{text-decoration:underline}
.pager .older{grid-column:2;text-align:right}
.comments{margin-top:40px}

/* Light and dark: the page is revealed from the switch in a circle (View Transitions, after Deluminator) */
::view-transition-old(root),::view-transition-new(root){animation:none;mix-blend-mode:normal}
html.vt-grow::view-transition-old(root){z-index:1}
html.vt-grow::view-transition-new(root){z-index:9999}
html.vt-shrink::view-transition-old(root){z-index:9999}
html.vt-shrink::view-transition-new(root){z-index:1}

/* Arrivals, once per visit and never for reduced motion: the masthead rule is drawn, the lead settles,
   stories rise into place as they scroll in, Most read fills its meters, the clock rolls over each minute */
@keyframes rise{from{opacity:0;transform:translateY(12px)}}
@keyframes draw{from{transform:scaleX(0)}}
@keyframes settle{from{opacity:.35;transform:scale(1.06)}}
@keyframes grow{from{transform:scaleX(0)}}
@keyframes pop{0%{opacity:0;transform:scale(.4)}70%{transform:scale(1.12)}100%{transform:none}}
@keyframes drop{from{opacity:0;transform:translateY(-6px)}}
.anim .masthead .title{animation:rise .8s var(--ease) both}
.anim .masthead .tagline{animation:rise .8s .15s var(--ease) both}
.anim .masthead::after{animation:draw 1s .2s var(--ease) both}
.anim .lead .thumb img{animation:settle 1.4s var(--ease) both}
.anim .lead .kicker,.anim .lead .hl,.anim .lead .dek,.anim .lead .meta,.anim .lead .btn{animation:rise .7s var(--ease) both}
.anim .lead .hl{animation-delay:.08s}.anim .lead .dek{animation-delay:.16s}
.anim .lead .meta{animation-delay:.24s}.anim .lead .btn{animation-delay:.32s}
.anim .reveal:not(.in){opacity:0}
.anim .reveal.in{animation:rise .65s var(--ease) both;animation-delay:calc(var(--d, 0) * 1ms)}
.anim .reveal.in .meter i{animation:grow 1.1s var(--ease) both;animation-delay:calc(var(--d, 0) * 1ms + 250ms)}
.anim .is-new .kicker::before{animation:pop .5s .4s var(--ease) both}
.anim .bar.open .panel{animation:drop .25s var(--ease)}
.anim #reader[open]{animation:rise .25s var(--ease)}
.anim #reader[open]::backdrop{animation:fade .25s ease}
@keyframes fade{from{opacity:0}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms!important;animation-iteration-count:1!important;
  transition-duration:.001ms!important}.orb{animation:none!important}}

@media (min-width:860px){#reader{height:calc(100dvh - 48px);margin:24px auto;border:1px solid var(--line-strong)}}
@media (max-width:1000px){.body-grid{grid-template-columns:minmax(0,1fr) 240px}}
@media (max-width:860px){
  .paper{padding:0 16px 32px}
  .front,.body-grid{grid-template-columns:minmax(0,1fr)}
  .latest{border-left:0;padding-left:0;margin-top:32px}
  .lead .thumb{margin-left:-16px;margin-right:-16px;border-radius:0}
  .rail{border-left:0;padding-left:0;position:static;border-top:4px double var(--ink);padding-top:24px}
  .bar-in{display:flex;flex-wrap:wrap;align-items:center;gap:0 12px}
  .menu-btn{display:inline-flex;align-items:center;gap:8px;min-height:44px;margin-left:auto;font:700 14px/20px var(--sans);
    color:var(--ink);background:transparent;border:1px solid var(--line-strong);border-radius:var(--radius-sm);padding:10px 14px;
    cursor:pointer}
  .menu-btn svg{width:14px;height:16px;fill:currentColor}
  .menu-btn .i-close,.bar.open .menu-btn .i-bars{display:none}
  .bar.open .menu-btn .i-close{display:block}
  .panel{display:flex;flex-direction:column;gap:16px;width:100%;padding:0 0 16px}
  html.js .bar:not(.open) .panel{display:none}
  .menu{flex-direction:column;gap:0}
  .menu a{border-bottom:1px solid var(--line)}
  .menu a::after{display:none}
  html:not(.js) .menu{flex-direction:row;gap:0 20px}
  html:not(.js) .menu a{border:0}
  .bar .search{max-width:none}
  .search kbd{display:none}
  .c-wd{display:none}
}
@media (max-width:560px){
  .cards{grid-template-columns:minmax(0,1fr);gap:20px}
  .card.has-thumb{display:grid;grid-template-columns:minmax(0,1fr) 92px;column-gap:16px;align-content:start}
  .card.has-thumb>*{grid-column:1}
  .card.has-thumb .thumb{grid-column:2;grid-row:1/span 4;aspect-ratio:1;margin:0}
  .card .dek,.card:not(.has-thumb) .dek{-webkit-line-clamp:3}
  .pager{grid-template-columns:1fr}.pager .older{grid-column:1;text-align:left}
}
main:not(.filtering) .card.dup{display:none}
@media print{.bar,.rail,#reader,.skip,.comments,.theme-btn,.paper-row{display:none!important}
  .reveal{opacity:1!important;animation:none!important}}
""".replace("@@DARK@@", DARK)

BASE_SCRIPT = """
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var root = document.documentElement;
  var lessMotion = window.matchMedia ? matchMedia("(prefers-reduced-motion: reduce)") : null;
  function still() { return !!(lessMotion && lessMotion.matches); }

  // Relative times, refreshed every minute; the full date, in the reader's own time zone, stays in the tooltip.
  var day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
  var dayYear = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
  var full = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "short", year: "numeric",
                                                hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  function count(n, unit) { return n + " " + unit + (n === 1 ? "" : "s") + " ago"; }
  function ago(t) {
    var s = (Date.now() - t) / 1000, d = Math.floor(s / 86400);
    if (s < 60) return "just now";
    if (s < 3600) return count(Math.floor(s / 60), "minute");
    if (s < 86400) return count(Math.floor(s / 3600), "hour");
    if (d < 2) return "yesterday";
    if (d < 7) return d + " days ago";
    return (new Date(t).getFullYear() === new Date().getFullYear() ? day : dayYear).format(t);
  }
  function tick() {
    $$("time[data-rel]").forEach(function (el) {
      var t = Date.parse(el.getAttribute("datetime"));
      if (!isNaN(t)) { el.textContent = ago(t); el.title = full.format(t); }
    });
  }

  // Today's date and the reader's local time, to the second, with the separators blinking every other second as on
  // a Mac. The seconds button stops both (WCAG 2.2.2); reduced motion keeps the separators still.
  var clock = $("#clock"), secsBtn = $("#secs"), secs = stored("enn:secs") !== "off", lastMinute = -1, clockTimer = 0;
  var today = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "short", year: "numeric" });
  var withSecs = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short" });
  var noSecs = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZoneName: "short" });
  var zone = new Intl.DateTimeFormat(undefined, { timeZoneName: "long" });
  function part(p, d) {
    var v = p.value.replace(/&/g, "&amp;").replace(/</g, "&lt;");
    if (p.type === "literal" && /^[:.]$/.test(p.value)) return '<span class="sep">' + v + "</span>";
    if (p.type === "timeZoneName") {
      var z = zone.formatToParts(d).filter(function (q) { return q.type === "timeZoneName"; })[0];
      return '<abbr title="' + (z ? z.value.replace(/"/g, "") : v) + '">' + v + "</abbr>";
    }
    return v;
  }
  function render() {
    var d = new Date();
    if (clock) {
      var dp = today.formatToParts(d), wd = dp[0].type === "weekday" ? dp[0].value + dp[1].value : "";
      clock.innerHTML = '<span class="c-wd">' + wd + "</span>" + dp.slice(wd ? 2 : 0).map(function (p) { return p.value; }).join("") +
        " \\u00b7 " + (secs ? withSecs : noSecs).formatToParts(d).map(function (p) { return part(p, d); }).join("");
      clock.setAttribute("datetime", d.toISOString());
      clock.title = "Your local time";
      clock.classList.toggle("dim", secs && !still() && d.getSeconds() % 2 === 1);
    }
    if (d.getMinutes() !== lastMinute) { lastMinute = d.getMinutes(); tick(); }
    var t = Date.now();
    clockTimer = setTimeout(render, secs ? 1000 - t % 1000 : 60000 - t % 60000);
  }
  function showSecs() { if (secsBtn) secsBtn.setAttribute("aria-pressed", String(secs)); }
  if (secsBtn) secsBtn.addEventListener("click", function () {
    secs = !secs;
    save("enn:secs", secs ? null : "off");
    showSecs();
    clearTimeout(clockTimer);
    render();
  });

  // The globe turns for a few seconds and then rests, so nothing on the page moves for long (WCAG 2.2.2).
  function spin(el, ms) {
    if (!el || still()) return;
    el.classList.add("spin");
    clearTimeout(el.spinning);
    el.spinning = setTimeout(function () { el.classList.remove("spin"); }, ms);
  }
  spin($(".topbar .orb-link"), 5000);

  // Section bar: sticks to the top, brings in the globe and title once the masthead has scrolled away,
  // folds into a menu on phones.
  var bar = $("#bar"), menuBtn = $("#menu-btn"), mast = $(".masthead");
  if (mast && "IntersectionObserver" in window) {
    new IntersectionObserver(function (e) {
      var stuck = !e[0].isIntersecting;
      if (stuck && !bar.classList.contains("stuck")) spin($(".brand"), 3000);
      bar.classList.toggle("stuck", stuck);
    }).observe(mast);
  }
  function menu(open) { bar.classList.toggle("open", open); menuBtn.setAttribute("aria-expanded", String(open)); }
  menuBtn.addEventListener("click", function () { menu(!bar.classList.contains("open")); });
  $$("#panel a").forEach(function (a) { a.addEventListener("click", function () { menu(false); }); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && bar.classList.contains("open") && e.target.id !== "q") { menu(false); menuBtn.focus(); }
  });

  // Auto, light, dark and Orioni mode (after github.com/stijn/deluminator and gov.eurth.org). Auto follows the
  // device and is remembered by forgetting the choice; each click moves on: from auto it flips the page, then keeps
  // the device's look even if the device changes, then returns to auto. Open tabs keep in step.
  var themeBtn = $("#theme"), paperBtn = $("#paper"), chrome = $("#theme-color"), toastEl = $("#toast"),
      sys = window.matchMedia && matchMedia("(prefers-color-scheme: dark)");
  var NAMES = { auto: "auto, as your device is set", light: "light, always", dark: "dark, always" };
  function stored(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }
  function isDark() { return root.getAttribute("data-theme") === "dark"; }
  function isPaper() { return root.hasAttribute("data-paper"); }
  function device() { return sys && sys.matches ? "dark" : "light"; }
  function mode() { var t = stored("enn:theme"); return t === "light" || t === "dark" ? t : "auto"; }
  function after(m) { return m === "auto" ? (device() === "dark" ? "light" : "dark") : m === device() ? "auto" : device(); }
  function toast(text) {
    if (!toastEl) return;
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastEl.hiding);
    toastEl.hiding = setTimeout(function () { toastEl.classList.remove("show"); }, 4000);
  }
  function paint(dark, paper) {
    root.setAttribute("data-theme", dark ? "dark" : "light");
    if (paper) root.setAttribute("data-paper", ""); else root.removeAttribute("data-paper");
    if (chrome) chrome.setAttribute("content", dark ? "@@DARK@@" : paper ? "@@PAPER@@" : "@@LIGHT@@");
    var m = mode(), label = "Theme: " + NAMES[m] + ". Switch to " + after(m) + ".";
    themeBtn.setAttribute("aria-label", label);
    themeBtn.title = label;
    if (paperBtn) paperBtn.setAttribute("aria-pressed", String(paper && !dark));
    var icon = document.getElementById("i-" + (m === "auto" ? "auto" : dark ? "moon" : "sun") + (still() ? "-still" : ""));
    $(".theme-icon", themeBtn).replaceChildren(icon.content.cloneNode(true));
  }
  // The new look grows out of the button that was pressed, or the old one shrinks into it.
  var switching = null;
  function reveal(btn, e, grow, change) {
    if (switching) switching.skipTransition();  // a quick second click finishes the first switch at once
    if (!document.startViewTransition || still()) { change(); return; }
    var r = btn.getBoundingClientRect(), x = e && e.clientX ? e.clientX : r.left + r.width / 2,
        y = e && e.clientY ? e.clientY : r.top + r.height / 2,
        far = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
    root.classList.add(grow ? "vt-grow" : "vt-shrink");
    var vt = switching = document.startViewTransition(change);
    vt.ready.then(function () {
      var dot = "circle(0px at " + x + "px " + y + "px)", all = "circle(" + far + "px at " + x + "px " + y + "px)";
      // Hold the last frame: without it the old page shows again for a moment before the transition ends,
      // a white flash when going dark.
      root.animate({ clipPath: grow ? [dot, all] : [all, dot] }, {
        duration: 500, easing: grow ? "cubic-bezier(.25,.55,.45,1)" : "cubic-bezier(.55,0,.75,.45)", fill: "forwards",
        pseudoElement: grow ? "::view-transition-new(root)" : "::view-transition-old(root)" });
    }).catch(function () {});
    vt.finished.finally(function () {
      if (switching === vt) { switching = null; root.classList.remove("vt-grow", "vt-shrink"); }
    });
  }
  themeBtn.addEventListener("click", function (e) {
    var m = after(mode()), dark = m === "auto" ? device() === "dark" : m === "dark";
    save("enn:theme", m === "auto" ? null : m);
    toast("Theme: " + NAMES[m] + ".");
    if (dark === isDark()) { paint(dark, isPaper()); return; }
    reveal(themeBtn, e, !dark, function () { paint(dark, isPaper()); });
  });
  if (paperBtn) paperBtn.addEventListener("click", function (e) {
    var paper = !(isPaper() && !isDark());
    save("enn:paper", paper ? "1" : "0");
    if (paper && isDark()) save("enn:theme", "light");
    toast(paper ? "Orioni mode: newsprint paper." : "Orioni mode off.");
    reveal(paperBtn, e, paper, function () { paint(paper ? false : isDark(), paper); });
  });
  if (sys && sys.addEventListener) sys.addEventListener("change", function (e) { if (mode() === "auto") paint(e.matches, isPaper()); });
  addEventListener("storage", function (e) {
    if (e.key !== "enn:theme" && e.key !== "enn:paper") return;
    var t = stored("enn:theme");
    paint(t === "dark" || (!t && !!sys && sys.matches), stored("enn:paper") === "1");
  });
  paint(isDark(), isPaper());
  showSecs();
  render();

  // Stories rise into place as they scroll into view, a few at a time.
  var arrivals = root.classList.contains("anim") && "IntersectionObserver" in window && new IntersectionObserver(function (es) {
    es.filter(function (e) { return e.isIntersecting; }).forEach(function (e, k) {
      e.target.style.setProperty("--d", Math.min(k, 6) * 70);
      e.target.classList.add("in");
      arrivals.unobserve(e.target);
    });
  }, { rootMargin: "0px 0px -6% 0px" });
  $$(".reveal").forEach(function (el) { if (arrivals) arrivals.observe(el); else el.classList.add("in"); });
""".replace("@@DARK@@", CHROME["dark"]).replace("@@PAPER@@", CHROME["paper"]).replace("@@LIGHT@@", CHROME["light"])

SCRIPT = """
  var S = JSON.parse(document.getElementById("stories-data").textContent);
  var store = {
    get: function (k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  };
  var main = $("#main"), q = $("#q"), note = $(".filter-note"), empty = $(".empty"), announce = $("#announce");

  // "New" since the previous visit (a visit ends after 30 idle minutes) and stories already read.
  var now = Date.now(), visit = store.get("enn:visit") || {}, since = visit.prev || 0;
  if (!visit.cur || now - visit.cur > 1800000) since = visit.cur || 0;
  store.set("enn:visit", { prev: since, cur: now });
  var read = store.get("enn:read") || [], fresh = 0;
  S.forEach(function (s, i) {
    var isNew = since && Date.parse(s.d) > since, isRead = read.indexOf(s.id) > -1;
    if (isNew && !isRead) fresh++;
    $$('.story[data-i="' + i + '"]').forEach(function (el) {
      el.classList.toggle("is-new", !!isNew && !isRead);
      el.classList.toggle("is-read", isRead);
    });
  });
  if (fresh) {
    var nc = $(".new-count");
    nc.textContent = " \\u00b7 " + fresh + " new since your last visit";
    nc.hidden = false;
  }
  function markRead(i) {
    if (read.indexOf(S[i].id) < 0) { read.push(S[i].id); store.set("enn:read", read.slice(-300)); }
    $$('.story[data-i="' + i + '"]').forEach(function (el) { el.classList.remove("is-new"); el.classList.add("is-read"); });
  }

  // Search (headline, agency, nation and the full story text) and the nation filter.
  var haystack = S.map(function (s, i) {
    var body = document.getElementById("b" + i);
    return [s.h, s.k, s.ag, s.n, body ? body.content.textContent : ""].join(" ").toLowerCase();
  });
  var nation = null;
  function apply() {
    var terms = q.value.toLowerCase().split(/\\s+/).filter(Boolean), active = !!(terms.length || nation), shown = 0;
    main.classList.toggle("filtering", active);
    $$(".feed .card").forEach(function (c) {
      var i = +c.dataset.i, ok = (!nation || S[i].n === nation) &&
        terms.every(function (t) { return haystack[i].indexOf(t) > -1; });
      c.hidden = active && !ok;
      if (ok) shown++;
    });
    $$(".nations button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.nation === nation)); });
    note.hidden = !active;
    empty.hidden = !active || shown > 0;
    if (active && main.getBoundingClientRect().top < 0) main.scrollIntoView();
    if (active) {
      var what = shown + (shown === 1 ? " story" : " stories");
      if (nation) what += " from " + nation;
      if (terms.length) what += " matching \\u201c" + q.value.trim() + "\\u201d";
      $(".filter-text", note).textContent = what;
    }
  }
  q.addEventListener("input", apply);
  q.addEventListener("keydown", function (e) { if (e.key === "Escape" && q.value) { q.value = ""; apply(); } });
  $$(".nations button").forEach(function (b) {
    b.addEventListener("click", function () {
      nation = nation === b.dataset.nation ? null : b.dataset.nation;
      apply();
      if (nation) $(".feed").scrollIntoView({ block: "start" });
    });
  });
  $$(".clear-filters").forEach(function (b) {
    b.addEventListener("click", function () { q.value = ""; nation = null; apply(); q.focus(); });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && !dlg.open && !/^(input|textarea|select)$/i.test(e.target.tagName)) { e.preventDefault(); q.focus(); }
  });

  // Reader: full story in a dialog, deep-linkable as #story-<post id>, with newer/older navigation.
  // Links never open new tabs (WCAG 3.2.5); Back returns to the story.
  var dlg = $("#reader"), body = $("#r-body"), order = [], cur = -1, pushed = false, opener = null;
  function visible() {
    if (!main.classList.contains("filtering")) return S.map(function (_, i) { return i; });
    return $$(".feed .card:not([hidden])").map(function (c) { return +c.dataset.i; });
  }
  function show(i, fromHistory) {
    var s = S[i];
    if (!s) return;
    if (!dlg.open) { order = visible(); if (order.indexOf(i) < 0) order = S.map(function (_, j) { return j; }); }
    cur = i;
    $("#r-kicker").textContent = s.k;
    $("#r-title").textContent = s.h;
    if (s.a) $("#r-av").src = s.a;
    $("#r-av").hidden = !s.a;
    $("#r-nation").textContent = s.n;
    $("#r-time").setAttribute("datetime", s.d);
    $("#r-min").textContent = s.m;
    $("#r-agency").textContent = s.ag;
    $("#r-link").href = s.u;
    $("#r-page").href = s.p;
    $$(".r-what").forEach(function (el) { el.textContent = ": " + s.h; });
    $("#r-copy").textContent = "Copy link";
    body.replaceChildren(document.getElementById("b" + i).content.cloneNode(true));
    var at = order.indexOf(i);
    $("#r-pos").textContent = (at + 1) + " of " + order.length;
    $("#r-prev").disabled = at <= 0;
    $("#r-next").disabled = at >= order.length - 1;
    tick();
    if (!dlg.open) { dlg.showModal(); root.classList.add("reading"); }
    $(".r-scroll").scrollTop = 0;
    markRead(i);
    var hash = "#story-" + s.id;
    if (!fromHistory && location.hash !== hash) {
      if (pushed || fromHash() > -1) history.replaceState(null, "", hash);
      else { history.pushState(null, "", hash); pushed = true; }
    }
  }
  function step(n) { var j = order[order.indexOf(cur) + n]; if (j !== undefined) show(j); }
  function fromHash() {
    var m = /^#story-(\\d+)$/.exec(location.hash);
    if (!m) return -1;
    for (var i = 0; i < S.length; i++) if (String(S[i].id) === m[1]) return i;
    return -1;
  }
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-i]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    opener = a;
    show(+a.dataset.i);
  });
  $("#r-prev").addEventListener("click", function () { step(-1); });
  $("#r-next").addEventListener("click", function () { step(1); });
  $("#r-close").addEventListener("click", function () { dlg.close(); });
  $("#r-copy").addEventListener("click", function () {
    var b = this, url = new URL(S[cur].p, location.href).href;
    function done() { b.textContent = "Link copied"; announce.textContent = "Link to this story copied"; }
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, function () { prompt("Copy this link", url); });
    else prompt("Copy this link", url);
  });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") step(-1);
    if (e.key === "ArrowRight") step(1);
  });
  dlg.addEventListener("close", function () {
    root.classList.remove("reading");
    body.replaceChildren();
    announce.textContent = "";
    if (pushed) { pushed = false; history.back(); }
    else if (fromHash() > -1) history.replaceState(null, "", location.pathname + location.search);
    if (opener) opener.focus();
  });
  window.addEventListener("popstate", function () {
    var i = fromHash();
    if (i > -1) show(i, true);
    else if (dlg.open) { pushed = false; dlg.close(); }
  });
  if (fromHash() > -1) show(fromHash(), true);
"""


def page_path(s):
    return f"story/{s['id']}/"


def time_tag(iso):
    """<time> that the page script turns into '3 hours ago'; without JS it reads as a date."""
    return f'<time datetime="{esc(iso)}" data-rel>{esc(fmt_date(iso))}</time>'


def kicker(s):
    label = f' · <span class="label">{esc(s["label"])}</span>' if s["label"] else ""
    return f'<p class="kicker"><span title="{esc(s["agency"])}">{esc(short_agency(s["agency"]))}</span>{label}</p>'


def avatar(url):
    return (f'<img class="av" src="{esc(url)}" alt="" width="18" height="18" loading="lazy" '
            f'referrerpolicy="no-referrer">' if url else "")


def minutes(n):
    return f'{n} <abbr title="minutes">min</abbr> read'


def meta(s, with_minutes=True):
    read = f'<span>· {minutes(s["minutes"])}</span>' if with_minutes else ""
    return (f'<p class="meta">{avatar(s["avatar"])}<span class="nation">{esc(s["nation"])}</span>'
            f'<span>· {time_tag(s["date"])}</span>{read}</p>')


def headline(s, i, tag="h3"):
    return f'<{tag} class="hl"><a href="{esc(page_path(s))}" data-i="{i}">{esc(s["headline"])}</a></{tag}>'


def thumb(s, eager=False):
    im = s["image"]
    if not im:
        return ""
    srcset = f' srcset="{esc(im["srcset"])}"' if im["srcset"] else ""
    load = 'fetchpriority="high"' if eager else 'loading="lazy"'
    return (f'<div class="thumb"><img src="{esc(im["src"])}"{srcset} alt="" width="{im["w"]}" height="{im["h"]}" '
            f'{load} decoding="async" referrerpolicy="no-referrer"></div>')


def dek(s):
    return f'<p class="dek">{esc(s["dek"])}</p>' if s["dek"] else ""


def lead_story(s):
    return (f'<article class="lead story" data-i="0">{thumb(s, eager=True)}{kicker(s)}{headline(s, 0, "h2")}'
            f'{dek(s)}{meta(s)}<a class="btn" href="{esc(page_path(s))}" data-i="0">Read the full story'
            f'<span class="sr">: {esc(s["headline"])}</span></a></article>')


def side_story(s, i):
    cls = "side story reveal has-thumb" if s["image"] else "side story reveal"
    return f'<article class="{cls}" data-i="{i}">{thumb(s)}{kicker(s)}{headline(s, i)}{meta(s, False)}</article>'


def card(s, i):
    cls = "card story reveal" + (" has-thumb" if s["image"] else "") + (" dup" if i < FRONT else "")
    return f'<article class="{cls}" data-i="{i}">{thumb(s)}{kicker(s)}{headline(s, i)}{dek(s)}{meta(s)}</article>'


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word[:-1] + 'ies' if word.endswith('y') else word + 's'}"


def story_image(s):
    im = s["image"]
    return (im["src"], im["w"], im["h"], "") if im else SHARE_CARD


def head(title, card_title, description, url, image, base, extra=""):
    """Theme set before paint, fonts, icons, the social card (Open Graph, X) and oEmbed discovery."""
    src, w, h, alt = image
    return (
        f"<head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<meta name='theme-color' id='theme-color' content='#2698d4'>"
        f"<script>{HEAD_SCRIPT}</script>"
        f"<title>{esc(title)}</title>"
        f"<meta name='description' content='{esc(description)}'>"
        f"<link rel='canonical' href='{esc(url)}'>"
        f"<link rel='alternate' type='application/rss+xml' title='Eurth News Network' href='{base}news.rss'>"
        f"<link rel='alternate' type='application/json+oembed' href='{esc(url)}oembed.json' title='{esc(card_title)}'>"
        f"<link rel='icon' href='{base}static/favicon.svg' type='image/svg+xml'>"
        f"<link rel='apple-touch-icon' href='{base}static/apple-touch-icon.png'>"
        f"<meta property='og:site_name' content='Eurth News Network · Geofiction'>"
        f"<meta property='og:locale' content='en_GB'>"
        f"<meta property='og:title' content='{esc(card_title)}'>"
        f"<meta property='og:description' content='{esc(description)}'>"
        f"<meta property='og:url' content='{esc(url)}'>"
        f"<meta property='og:image' content='{esc(src)}'>"
        + (f"<meta property='og:image:width' content='{w}'><meta property='og:image:height' content='{h}'>" if w else "")
        + (f"<meta property='og:image:alt' content='{esc(alt)}'>" if alt else "")
        + f"<meta name='twitter:card' content='summary_large_image'>"
        f"<meta name='twitter:site' content='@eurthnews'>"
        f"<meta name='copyright' content='{esc(RIGHTS)}'>"
        f"<meta name='tdm-reservation' content='1'>"
        f"<meta name='robots' content='noai, noimageai'>"
        f"{extra}"
        f"<link rel='preconnect' href='https://fonts.googleapis.com'>"
        f"<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        f"<link rel='stylesheet' href='{FONTS}'>"
        f"<style>{CSS}</style></head>"
    )


def oembed(title, image, author=None):
    """oEmbed 'link' response, so unfurlers that ask for oEmbed get the same card as Open Graph."""
    src, w, h, _ = image
    data = {"version": "1.0", "type": "link", "title": title, "provider_name": "Eurth News Network",
            "provider_url": PAGE_URL, "cache_age": 3600, "thumbnail_url": src}
    if w:
        data.update(thumbnail_width=w, thumbnail_height=h)
    if author:
        data["author_name"], data["author_url"] = author
    return json.dumps(data, ensure_ascii=False)


def orb(base, size):
    return (f"<span class='orb' aria-hidden='true' style='--s:{size}px;"
            f"background-image:url({base}static/eurth-globe-sprite.png)'></span>")


def topbar(now, base=""):
    """The globe, today's date and (once the script runs) the reader's local time; RSS and the theme switch."""
    return (f"<div class='topbar'><div><a class='tap orb-link' href='{SITE}' aria-label='eurth.org'>{orb(base, 32)}</a>"
            f"<time id='clock' datetime='{now.isoformat(timespec='seconds')}'>{now:%A} {now.day} {now:%b %Y}</time>"
            f"{SECONDS_BUTTON}</div>"
            f"<div><span>Updated <time datetime='{now.isoformat(timespec='seconds')}' data-rel>{now:%H:%M} "
            f"<abbr title='Coordinated Universal Time'>UTC</abbr></time></span>"
            f"<a class='tap' href='{base}news.rss'>RSS feed</a>{THEME_BUTTON}</div></div>")


def bar(base="", search=""):
    """Sticky section bar: links within this site (search too on the front page); a menu button on phones."""
    links = ""
    for name, anchor in MENU:
        cls = " class='js-only'" if anchor == "nations" else ""
        links += f"<a href='{base}#{anchor}'{cls}>{name}</a>"
    return (f"<nav class='bar' id='bar' aria-label='Sections'><div class='bar-in'>"
            f"<a class='brand orb-link' href='{base or '#'}'>{orb(base, 28)}Eurth News Network</a>"
            f"<button type='button' class='menu-btn js-only' id='menu-btn' aria-expanded='false' aria-controls='panel'>"
            f"{ICONS}<span>Menu</span></button>"
            f"<div class='panel' id='panel'><div class='menu'>{links}</div>{search}</div>"
            f"</div></nav>")


def footer(base=""):
    links = "".join(f"<li><a href='{href}'><span class='n'>{esc(name)}</span><span class='d'>{esc(where)}</span></a></li>"
                    for name, where, href in FOOTER_NAV)
    return (f"<footer class='sitefoot'><p class='title'>Eurth News Network</p>"
            f"<p>The newest stories from The Newsroom on eurth.org. Everything here is fiction, written by the members of "
            f"Eurth, the Worldbuilding &amp; Roleplay Writing Community; each story appears as its agency published it.</p>"
            f"<nav class='elsewhere' aria-label='Eurth elsewhere'><ul>{links}"
            f"<li><a href='{base}news.rss'><span class='n'>RSS feed</span><span class='d'>news.eurth.org</span></a></li>"
            f"</ul></nav>"
            f"<p class='paper-row js-only'><button type='button' class='btn paper-btn' id='paper' aria-pressed='false' "
            f"aria-describedby='paper-note'>Orioni mode</button><span id='paper-note'>Newsprint paper, the way the "
            f"Orioni press likes it.</span></p>"
            f"<p class='legal'>{esc(RIGHTS)} The stories are © their authors, the members of Eurth who posted them on "
            f"eurth.org. Nothing here may be copied, republished or used for text and data mining or AI training "
            f"without written permission.</p></footer>")


def build_html(items):
    now = datetime.datetime.now(datetime.timezone.utc)
    nations = {}
    for s in items:
        if s["author"] != "system":
            nations.setdefault(s["nation"], [s["avatar"], 0])[1] += 1
    agencies = {s["agency"] for s in items}

    feed = ""
    if len(items) > FRONT:
        feed = (f'<h2 class="group-h">More stories</h2>'
                f'<div class="cards">{"".join(card(s, i) for i, s in enumerate(items))}</div>')
    front = ""
    if items:
        front = (f'<section class="front" id="top" aria-label="Top stories">{lead_story(items[0])}'
                 f'<div class="latest"><h2 class="col-h">Also new</h2>'
                 f'{"".join(side_story(items[i], i) for i in range(1, min(FRONT, len(items))))}</div></section>')

    ranked = sorted(range(len(items)), key=lambda i: -items[i]["readers"])[:5]
    top = max([items[i]["readers"] for i in ranked] or [1]) or 1
    most_read = "".join(
        f'<li class="reveal"><span class="num">{n}</span><div><a href="{esc(page_path(items[i]))}" data-i="{i}">'
        f'{esc(items[i]["headline"])}</a><span class="sub">{esc(short_agency(items[i]["agency"]))} · '
        f'{plural(items[i]["readers"], "reader")}</span>'
        f'<span class="meter" aria-hidden="true"><i style="--w:{round(100 * items[i]["readers"] / top)}%"></i></span>'
        f'</div></li>'
        for n, i in enumerate(ranked, 1) if items[i]["readers"]
    )
    chips = "".join(
        f'<li><button type="button" data-nation="{esc(n)}" aria-pressed="false">{avatar(av)}'
        f'{esc(n)} <span class="n">{c}</span></button></li>'
        for n, (av, c) in sorted(nations.items(), key=lambda kv: kv[0].lower())
    )
    rail = ""
    if most_read:
        rail += f'<section id="most-read"><h2 class="col-h">Most read</h2><ol class="mostread">{most_read}</ol></section>'
    if chips:
        rail += (f'<section class="js-only" id="nations"><h2 class="col-h">Nations in this edition</h2>'
                 f'<ul class="nations">{chips}</ul></section>')

    data = [{
        "id": s["id"], "h": s["headline"], "ag": s["agency"], "n": s["nation"], "d": s["date"], "u": s["url"],
        "p": page_path(s), "a": s["avatar"], "m": s["minutes"],
        "k": short_agency(s["agency"]) + (f' · {s["label"]}' if s["label"] else ""),
    } for s in items]
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    bodies = "".join(f'<template id="b{i}">{s["cooked"]}</template>' for i, s in enumerate(items))

    return (
        f"<!doctype html><html lang='en'>"
        + head("Eurth News Network", "Eurth News Network", DESCRIPTION, PAGE_URL, SHARE_CARD, "",
               "<meta property='og:type' content='website'><meta name='referrer' content='no-referrer'>")
        + f"<body><a class='skip' href='#main'>Skip to stories</a>"
        f"<div class='paper'>"
        f"  <header>{topbar(now)}"
        f"    <div class='masthead'><h1 class='title'>Eurth News Network</h1>"
        f"      <p class='tagline'>Yesterday's News Today</p></div></header>"
        f"  {bar('', SEARCH)}"
        f"  <main id='main'>"
        f"    <div class='toolbar'><p class='edition'><strong>{plural(len(items), 'story')}</strong> from "
        f"{plural(len(agencies), 'agency')} in {plural(len(nations), 'nation')}<span class='new-count' hidden></span></p></div>"
        f"    <p class='filter-note' hidden><span class='filter-text' role='status'></span>"
        f"      <button type='button' class='btn clear-filters'>Clear</button></p>"
        f"    {front}"
        f"    <div class='body-grid'>"
        f"      <div class='feed' id='more'>{feed}"
        f"        <p class='empty' hidden>No stories match. <button type='button' class='btn clear-filters'>Clear search</button></p>"
        f"      </div>"
        f"      <aside class='rail' aria-label='Most read and nations'>{rail}</aside>"
        f"    </div>"
        f"  </main>"
        f"  {footer()}"
        f"</div>"
        f"<dialog id='reader' aria-labelledby='r-title'><div class='r-scroll'>"
        f"  <div class='r-bar'>"
        f"    <button type='button' class='btn' id='r-close'>Close</button>"
        f"    <span class='r-pos' id='r-pos'></span>"
        f"    <button type='button' class='btn' id='r-prev'>&larr; Newer<span class='sr'> story</span></button>"
        f"    <button type='button' class='btn' id='r-next'>Older<span class='sr'> story</span> &rarr;</button>"
        f"  </div>"
        f"  <article class='r-article'>"
        f"    <p class='kicker' id='r-kicker'></p>"
        f"    <h2 class='r-title' id='r-title'></h2>"
        f"    <p class='meta r-meta'><img class='av' id='r-av' alt='' width='18' height='18' referrerpolicy='no-referrer'>"
        f"<span class='nation' id='r-nation'></span><span>· <time id='r-time' data-rel></time></span>"
        f"<span>· <span id='r-min'></span> <abbr title='minutes'>min</abbr> read</span></p>"
        f"    <p class='r-source'>As published by <span id='r-agency'></span></p>"
        f"    <div class='prose' id='r-body'></div>"
        f"    <div class='r-foot'><a class='cta' id='r-link' href='{SITE}'>Read and discuss on Eurth"
        f"<span class='sr r-what'></span></a><a class='btn' id='r-page' href='./'>Story page<span class='sr r-what'></span></a>"
        f"<button type='button' class='btn' id='r-copy'>Copy link</button></div>"
        f"    <p class='sr' id='announce' aria-live='polite'></p>"
        f"  </article>"
        f"</div></dialog>"
        f"<p class='toast' id='toast' role='status'></p>{THEME_ICONS}"
        f"<script type='application/json' id='stories-data'>{data_json}</script>"
        f"{bodies}"
        f"<script>(function () {{{BASE_SCRIPT}{SCRIPT}}})();</script>"
        f"</body></html>"
    )


def comments(s):
    """Discourse's embedded discussion for this story's page (see README: Comments)."""
    return (f"<section class='comments' id='comments' aria-label='Discussion'><h2 class='col-h'>Discussion</h2>"
            f"<div id='discourse-comments'></div></section>"
            f"<script>window.DiscourseEmbed={{discourseUrl:'{SITE}/',discourseEmbedUrl:'{PAGE_URL}{page_path(s)}'}};"
            f"(function(){{var d=document.createElement('script');d.async=true;"
            f"d.src=DiscourseEmbed.discourseUrl+'javascripts/embed.js';document.head.appendChild(d);}})();</script>")


def build_story(items, i):
    """A story's own page: shareable, readable without JS, and the anchor for embedded comments."""
    s, base = items[i], "../../"
    now = datetime.datetime.now(datetime.timezone.utc)
    url = PAGE_URL + page_path(s)
    title = f"{s['headline']} · {short_agency(s['agency'])}"
    description = s["dek"] or f"A story from {s['agency']}, published in The Newsroom on eurth.org."
    extra = (f"<meta property='og:type' content='article'>"
             f"<meta property='article:published_time' content='{esc(s['date'])}'>"
             f"<meta property='article:section' content='{esc(short_agency(s['agency']))}'>")
    if EMBED_COMMENTS and s["author"] != "system":
        extra += f"<meta name='discourse-username' content='{esc(s['author'])}'>"

    pager = ""
    if i > 0:
        pager += (f"<a class='newer' href='{base}{page_path(items[i - 1])}'><span class='k'>&larr; Newer story</span>"
                  f"<span class='t'>{esc(items[i - 1]['headline'])}</span></a>")
    if i < len(items) - 1:
        pager += (f"<a class='older' href='{base}{page_path(items[i + 1])}'><span class='k'>Older story &rarr;</span>"
                  f"<span class='t'>{esc(items[i + 1]['headline'])}</span></a>")

    return (
        f"<!doctype html><html lang='en'>"
        + head(f"{title} · Eurth News Network", s["headline"], description, url, story_image(s), base, extra)
        + f"<body><a class='skip' href='#story'>Skip to story</a>"
        f"<div class='paper'>"
        f"  <header>{topbar(now, base)}"
        f"    <div class='masthead slim'><a class='title' href='{base}'>Eurth News Network</a></div></header>"
        f"  {bar(base)}"
        f"  <main id='story' class='story-page'>"
        f"    <nav class='crumbs' aria-label='You are here'><ol><li><a href='{base}'>Front page</a></li>"
        f"<li><a href='{base}#more'>More stories</a></li>"
        f"<li><span aria-current='page'>{esc(short_agency(s['agency']))}</span></li></ol></nav>"
        f"    <article class='r-article'>{kicker(s)}<h1 class='r-title'>{esc(s['headline'])}</h1>"
        f"      <p class='meta r-meta'>{avatar(s['avatar'])}<span class='nation'>{esc(s['nation'])}</span>"
        f"<span>· {time_tag(s['date'])}</span><span>· {minutes(s['minutes'])}</span></p>"
        f"      <p class='r-source'>As published by {esc(s['agency'])}</p>"
        f"      <div class='prose'>{s['cooked']}</div>"
        f"      <div class='r-foot'><a class='cta' href='{esc(s['url'])}'>Read and discuss on Eurth"
        f"<span class='sr'>: {esc(s['headline'])}</span></a><a class='btn' href='{base}'>Front page</a></div>"
        f"    </article>"
        f"    {comments(s) if EMBED_COMMENTS else ''}"
        f"    <nav class='pager' aria-label='Newer and older stories'>{pager}</nav>"
        f"  </main>"
        f"  {footer(base)}"
        f"</div><p class='toast' id='toast' role='status'></p>{THEME_ICONS}"
        f"<script>(function () {{{BASE_SCRIPT}}})();</script></body></html>"
    )


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    open(f"{OUTDIR}/.nojekyll", "w").close()
    shutil.copytree(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"), f"{OUTDIR}/static",
                    dirs_exist_ok=True)
    items = fetch_stories()
    write(f"{OUTDIR}/index.html", build_html(items))
    write(f"{OUTDIR}/oembed.json", oembed("Eurth News Network", SHARE_CARD))
    for i, s in enumerate(items):
        page = f"{OUTDIR}/{page_path(s)}"
        write(page + "index.html", build_story(items, i))
        write(page + "oembed.json", oembed(s["headline"], story_image(s), (s["nation"], f"{SITE}/u/{s['author']}")))
    write(f"{OUTDIR}/news.rss", build_rss(items))
    write(f"{OUTDIR}/.well-known/tdmrep.json", json.dumps([{"location": "/", "tdm-reservation": 1}]))
    print(f"Updated {len(items)} stories -> {OUTDIR}/")


if __name__ == "__main__":
    main()
