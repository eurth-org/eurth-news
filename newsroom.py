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
# newsprint; Libre Baskerville for headlines, Helvetica for labels and text, JetBrains Mono for dates,
# Font Awesome icons and line-md's animated sun and moon. The page frame is Eurth's own (OOC); the
# stories inside keep their agencies' words, never their branding. Built to WCAG 2.2 AAA: 7:1 text
# contrast in every theme and state (one named brand exception: white on Eurth blue for the call to
# action, 3.2:1 at 19px bold), 44px targets; nothing moves for visitors who ask their device for reduced
# motion. Known gap: there's no on-page pause for the turning globe, icons and seconds (WCAG 2.2.2).

FONTS = ("https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400"
         "&family=JetBrains+Mono:wght@400;700&display=swap")

# Font Awesome Free 6.5.2 by @fontawesome (icons CC BY 4.0, fontawesome.com/license/free), the forum's icon
# set; each page carries them once, as a hidden sprite.
FA = {
    "arrow-left": ("0 0 448 512", 'M9.4 233.4c-12.5 12.5-12.5 32.8 0 45.3l160 160c12.5 12.5 32.8 12.5 45.3 0s12.5-32.8 0-45.3L109.2'
            ' 288 416 288c17.7 0 32-14.3 32-32s-14.3-32-32-32l-306.7 0L214.6 118.6c12.5-12.5 12.5-32.8 0-45.3'
            's-32.8-12.5-45.3 0l-160 160z'),
    "arrow-right": ("0 0 448 512", 'M438.6 278.6c12.5-12.5 12.5-32.8 0-45.3l-160-160c-12.5-12.5-32.8-12.5-45.3 0s-12.5 32.8 0 45.3L3'
            '38.8 224 32 224c-17.7 0-32 14.3-32 32s14.3 32 32 32l306.7 0L233.4 393.4c-12.5 12.5-12.5 32.8 0 4'
            '5.3s32.8 12.5 45.3 0l160-160z'),
    "bars": ("0 0 448 512", 'M0 96C0 78.3 14.3 64 32 64H416c17.7 0 32 14.3 32 32s-14.3 32-32 32H32C14.3 128 0 113.7 0 96zM0 2'
            '56c0-17.7 14.3-32 32-32H416c17.7 0 32 14.3 32 32s-14.3 32-32 32H32c-17.7 0-32-14.3-32-32zM448 41'
            '6c0 17.7-14.3 32-32 32H32c-17.7 0-32-14.3-32-32s14.3-32 32-32H416c17.7 0 32 14.3 32 32z'),
    "bolt": ("0 0 448 512", 'M349.4 44.6c5.9-13.7 1.5-29.7-10.6-38.5s-28.6-8-39.9 1.8l-256 224c-10 8.8-13.6 22.9-8.9 35.3S50.'
            '7 288 64 288H175.5L98.6 467.4c-5.9 13.7-1.5 29.7 10.6 38.5s28.6 8 39.9-1.8l256-224c10-8.8 13.6-2'
            '2.9 8.9-35.3s-16.6-20.7-30-20.7H272.5L349.4 44.6z'),
    "book": ("0 0 448 512", 'M96 0C43 0 0 43 0 96V416c0 53 43 96 96 96H384h32c17.7 0 32-14.3 32-32s-14.3-32-32-32V384c17.7 0 '
            '32-14.3 32-32V32c0-17.7-14.3-32-32-32H384 96zm0 384H352v64H96c-17.7 0-32-14.3-32-32s14.3-32 32-3'
            '2zm32-240c0-8.8 7.2-16 16-16H336c8.8 0 16 7.2 16 16s-7.2 16-16 16H144c-8.8 0-16-7.2-16-16zm16 48'
            'H336c8.8 0 16 7.2 16 16s-7.2 16-16 16H144c-8.8 0-16-7.2-16-16s7.2-16 16-16z'),
    "book-open": ("0 0 576 512", 'M249.6 471.5c10.8 3.8 22.4-4.1 22.4-15.5V78.6c0-4.2-1.6-8.4-5-11C247.4 52 202.4 32 144 32C93.5 3'
            '2 46.3 45.3 18.1 56.1C6.8 60.5 0 71.7 0 83.8V454.1c0 11.9 12.8 20.2 24.1 16.5C55.6 460.1 105.5 4'
            '48 144 448c33.9 0 79 14 105.6 23.5zm76.8 0C353 462 398.1 448 432 448c38.5 0 88.4 12.1 119.9 22.6'
            'c11.3 3.8 24.1-4.6 24.1-16.5V83.8c0-12.1-6.8-23.3-18.1-27.6C529.7 45.3 482.5 32 432 32c-58.4 0-1'
            '03.4 20-123 35.6c-3.3 2.6-5 6.8-5 11V456c0 11.4 11.7 19.3 22.4 15.5z'),
    "check": ("0 0 448 512", 'M438.6 105.4c12.5 12.5 12.5 32.8 0 45.3l-256 256c-12.5 12.5-32.8 12.5-45.3 0l-128-128c-12.5-12.5'
            '-12.5-32.8 0-45.3s32.8-12.5 45.3 0L160 338.7 393.4 105.4c12.5-12.5 32.8-12.5 45.3 0z'),
    "circle-half-stroke": ("0 0 512 512", 'M448 256c0-106-86-192-192-192V448c106 0 192-86 192-192zM0 256a256 256 0 1 1 512 0A256 256 0 1 1 '
            '0 256z'),
    "coins": ("0 0 512 512", 'M512 80c0 18-14.3 34.6-38.4 48c-29.1 16.1-72.5 27.5-122.3 30.9c-3.7-1.8-7.4-3.5-11.3-5C300.6 137'
            '.4 248.2 128 192 128c-8.3 0-16.4 .2-24.5 .6l-1.1-.6C142.3 114.6 128 98 128 80c0-44.2 86-80 192-8'
            '0S512 35.8 512 80zM160.7 161.1c10.2-.7 20.7-1.1 31.3-1.1c62.2 0 117.4 12.3 152.5 31.4C369.3 204.'
            '9 384 221.7 384 240c0 4-.7 7.9-2.1 11.7c-4.6 13.2-17 25.3-35 35.5c0 0 0 0 0 0c-.1 .1-.3 .1-.4 .2'
            'l0 0 0 0c-.3 .2-.6 .3-.9 .5c-35 19.4-90.8 32-153.6 32c-59.6 0-112.9-11.3-148.2-29.1c-1.9-.9-3.7-'
            '1.9-5.5-2.9C14.3 274.6 0 258 0 240c0-34.8 53.4-64.5 128-75.4c10.5-1.5 21.4-2.7 32.7-3.5zM416 240'
            'c0-21.9-10.6-39.9-24.1-53.4c28.3-4.4 54.2-11.4 76.2-20.5c16.3-6.8 31.5-15.2 43.9-25.5V176c0 19.3'
            '-16.5 37.1-43.8 50.9c-14.6 7.4-32.4 13.7-52.4 18.5c.1-1.8 .2-3.5 .2-5.3zm-32 96c0 18-14.3 34.6-3'
            '8.4 48c-1.8 1-3.6 1.9-5.5 2.9C304.9 404.7 251.6 416 192 416c-62.8 0-118.6-12.6-153.6-32C14.3 370'
            '.6 0 354 0 336V300.6c12.5 10.3 27.6 18.7 43.9 25.5C83.4 342.6 135.8 352 192 352s108.6-9.4 148.1-'
            '25.9c7.8-3.2 15.3-6.9 22.4-10.9c6.1-3.4 11.8-7.2 17.2-11.2c1.5-1.1 2.9-2.3 4.3-3.4V304v5.7V336zm'
            '32 0V304 278.1c19-4.2 36.5-9.5 52.1-16c16.3-6.8 31.5-15.2 43.9-25.5V272c0 10.5-5 21-14.9 30.9c-1'
            '6.3 16.3-45 29.7-81.3 38.4c.1-1.7 .2-3.5 .2-5.3zM192 448c56.2 0 108.6-9.4 148.1-25.9c16.3-6.8 31'
            '.5-15.2 43.9-25.5V432c0 44.2-86 80-192 80S0 476.2 0 432V396.6c12.5 10.3 27.6 18.7 43.9 25.5C83.4'
            ' 438.6 135.8 448 192 448z'),
    "comments": ("0 0 640 512", 'M208 352c114.9 0 208-78.8 208-176S322.9 0 208 0S0 78.8 0 176c0 38.6 14.7 74.3 39.6 103.4c-3.5 9.'
            '4-8.7 17.7-14.2 24.7c-4.8 6.2-9.7 11-13.3 14.3c-1.8 1.6-3.3 2.9-4.3 3.7c-.5 .4-.9 .7-1.1 .8l-.2 '
            '.2 0 0 0 0C1 327.2-1.4 334.4 .8 340.9S9.1 352 16 352c21.8 0 43.8-5.6 62.1-12.5c9.2-3.5 17.8-7.4 '
            '25.3-11.4C134.1 343.3 169.8 352 208 352zM448 176c0 112.3-99.1 196.9-216.5 207C255.8 457.4 336.4 '
            '512 432 512c38.2 0 73.9-8.7 104.7-23.9c7.5 4 16 7.9 25.2 11.4c18.3 6.9 40.3 12.5 62.1 12.5c6.9 0'
            ' 13.1-4.5 15.2-11.1c2.1-6.6-.2-13.8-5.8-17.9l0 0 0 0-.2-.2c-.2-.2-.6-.4-1.1-.8c-1-.8-2.5-2-4.3-3'
            '.7c-3.6-3.3-8.5-8.1-13.3-14.3c-5.5-7-10.7-15.4-14.2-24.7c24.9-29 39.6-64.7 39.6-103.4c0-92.8-84.'
            '9-168.9-192.6-175.5c.4 5.1 .6 10.3 .6 15.5z'),
    "file-lines": ("0 0 384 512", 'M64 0C28.7 0 0 28.7 0 64V448c0 35.3 28.7 64 64 64H320c35.3 0 64-28.7 64-64V160H256c-17.7 0-32-14'
            '.3-32-32V0H64zM256 0V128H384L256 0zM112 256H272c8.8 0 16 7.2 16 16s-7.2 16-16 16H112c-8.8 0-16-7'
            '.2-16-16s7.2-16 16-16zm0 64H272c8.8 0 16 7.2 16 16s-7.2 16-16 16H112c-8.8 0-16-7.2-16-16s7.2-16 '
            '16-16zm0 64H272c8.8 0 16 7.2 16 16s-7.2 16-16 16H112c-8.8 0-16-7.2-16-16s7.2-16 16-16z'),
    "fire-flame-curved": ("0 0 384 512", 'M153.6 29.9l16-21.3C173.6 3.2 180 0 186.7 0C198.4 0 208 9.6 208 21.3V43.5c0 13.1 5.4 25.7 14.9 3'
            '4.7L307.6 159C356.4 205.6 384 270.2 384 337.7C384 434 306 512 209.7 512H192C86 512 0 426 0 320v-'
            '3.8c0-48.8 19.4-95.6 53.9-130.1l3.5-3.5c4.2-4.2 10-6.6 16-6.6C85.9 176 96 186.1 96 198.6V288c0 3'
            '5.3 28.7 64 64 64s64-28.7 64-64v-3.9c0-18-7.2-35.3-19.9-48l-38.6-38.6c-24-24-37.5-56.7-37.5-90.7'
            'c0-27.7 9-54.8 25.6-76.9z'),
    "flag": ("0 0 448 512", 'M64 32C64 14.3 49.7 0 32 0S0 14.3 0 32V64 368 480c0 17.7 14.3 32 32 32s32-14.3 32-32V352l64.3-16'
            '.1c41.1-10.3 84.6-5.5 122.5 13.4c44.2 22.1 95.5 24.8 141.7 7.4l34.7-13c12.5-4.7 20.8-16.6 20.8-3'
            '0V66.1c0-23-24.2-38-44.8-27.7l-9.6 4.8c-46.3 23.2-100.8 23.2-147.1 0c-35.1-17.6-75.4-22-113.5-12'
            '.5L64 48V32z'),
    "flask": ("0 0 448 512", 'M288 0H160 128C110.3 0 96 14.3 96 32s14.3 32 32 32V196.8c0 11.8-3.3 23.5-9.5 33.5L10.3 406.2C3.6'
            ' 417.2 0 429.7 0 442.6C0 480.9 31.1 512 69.4 512H378.6c38.3 0 69.4-31.1 69.4-69.4c0-12.8-3.6-25.'
            '4-10.3-36.4L329.5 230.4c-6.2-10.1-9.5-21.7-9.5-33.5V64c17.7 0 32-14.3 32-32s-14.3-32-32-32H288zM'
            '192 196.8V64h64V196.8c0 23.7 6.6 46.9 19 67.1L309.5 320h-171L173 263.9c12.4-20.2 19-43.4 19-67.1'
            'z'),
    "globe": ("0 0 512 512", 'M352 256c0 22.2-1.2 43.6-3.3 64H163.3c-2.2-20.4-3.3-41.8-3.3-64s1.2-43.6 3.3-64H348.7c2.2 20.4 3'
            '.3 41.8 3.3 64zm28.8-64H503.9c5.3 20.5 8.1 41.9 8.1 64s-2.8 43.5-8.1 64H380.8c2.1-20.6 3.2-42 3.'
            '2-64s-1.1-43.4-3.2-64zm112.6-32H376.7c-10-63.9-29.8-117.4-55.3-151.6c78.3 20.7 142 77.5 171.9 15'
            '1.6zm-149.1 0H167.7c6.1-36.4 15.5-68.6 27-94.7c10.5-23.6 22.2-40.7 33.5-51.5C239.4 3.2 248.7 0 2'
            '56 0s16.6 3.2 27.8 13.8c11.3 10.8 23 27.9 33.5 51.5c11.6 26 20.9 58.2 27 94.7zm-209 0H18.6C48.6 '
            '85.9 112.2 29.1 190.6 8.4C165.1 42.6 145.3 96.1 135.3 160zM8.1 192H131.2c-2.1 20.6-3.2 42-3.2 64'
            's1.1 43.4 3.2 64H8.1C2.8 299.5 0 278.1 0 256s2.8-43.5 8.1-64zM194.7 446.6c-11.6-26-20.9-58.2-27-'
            '94.6H344.3c-6.1 36.4-15.5 68.6-27 94.6c-10.5 23.6-22.2 40.7-33.5 51.5C272.6 508.8 263.3 512 256 '
            '512s-16.6-3.2-27.8-13.8c-11.3-10.8-23-27.9-33.5-51.5zM135.3 352c10 63.9 29.8 117.4 55.3 151.6C11'
            '2.2 482.9 48.6 426.1 18.6 352H135.3zm358.1 0c-30 74.1-93.6 130.9-171.9 151.6c25.5-34.2 45.2-87.7'
            ' 55.3-151.6H493.4z'),
    "handshake": ("0 0 640 512", 'M323.4 85.2l-96.8 78.4c-16.1 13-19.2 36.4-7 53.1c12.9 17.8 38 21.3 55.3 7.8l99.3-77.2c7-5.4 17-4'
            '.2 22.5 2.8s4.2 17-2.8 22.5l-20.9 16.2L512 316.8V128h-.7l-3.9-2.5L434.8 79c-15.3-9.8-33.2-15-51.'
            '4-15c-21.8 0-43 7.5-60 21.2zm22.8 124.4l-51.7 40.2C263 274.4 217.3 268 193.7 235.6c-22.2-30.5-16'
            '.6-73.1 12.7-96.8l83.2-67.3c-11.6-4.9-24.1-7.4-36.8-7.4C234 64 215.7 69.6 200 80l-72 48V352h28.2'
            'l91.4 83.4c19.6 17.9 49.9 16.5 67.8-3.1c5.5-6.1 9.2-13.2 11.1-20.6l17 15.6c19.5 17.9 49.9 16.6 6'
            '7.8-2.9c4.5-4.9 7.8-10.6 9.9-16.5c19.4 13 45.8 10.3 62.1-7.5c17.9-19.5 16.6-49.9-2.9-67.8l-134.2'
            '-123zM16 128c-8.8 0-16 7.2-16 16V352c0 17.7 14.3 32 32 32H64c17.7 0 32-14.3 32-32V128H16zM48 320'
            'a16 16 0 1 1 0 32 16 16 0 1 1 0-32zM544 128V352c0 17.7 14.3 32 32 32h32c17.7 0 32-14.3 32-32V144'
            'c0-8.8-7.2-16-16-16H544zm32 208a16 16 0 1 1 32 0 16 16 0 1 1 -32 0z'),
    "heart-pulse": ("0 0 512 512", 'M228.3 469.1L47.6 300.4c-4.2-3.9-8.2-8.1-11.9-12.4h87c22.6 0 43-13.6 51.7-34.5l10.5-25.2 49.3 10'
            '9.5c3.8 8.5 12.1 14 21.4 14.1s17.8-5 22-13.3L320 253.7l1.7 3.4c9.5 19 28.9 31 50.1 31H476.3c-3.7'
            ' 4.3-7.7 8.5-11.9 12.4L283.7 469.1c-7.5 7-17.4 10.9-27.7 10.9s-20.2-3.9-27.7-10.9zM503.7 240h-13'
            '2c-3 0-5.8-1.7-7.2-4.4l-23.2-46.3c-4.1-8.1-12.4-13.3-21.5-13.3s-17.4 5.1-21.5 13.3l-41.4 82.8L20'
            '5.9 158.2c-3.9-8.7-12.7-14.3-22.2-14.1s-18.1 5.9-21.8 14.8l-31.8 76.3c-1.2 3-4.2 4.9-7.4 4.9H16c'
            '-2.6 0-5 .4-7.3 1.1C3 225.2 0 208.2 0 190.9v-5.8c0-69.9 50.5-129.5 119.4-141C165 36.5 211.4 51.4'
            ' 244 84l12 12 12-12c32.6-32.6 79-47.5 124.6-39.9C461.5 55.6 512 115.2 512 185.1v5.8c0 16.9-2.8 3'
            '3.5-8.3 49.1z'),
    "landmark": ("0 0 512 512", 'M240.1 4.2c9.8-5.6 21.9-5.6 31.8 0l171.8 98.1L448 104l0 .9 47.9 27.4c12.6 7.2 18.8 22 15.1 36s-1'
            '6.4 23.8-30.9 23.8H32c-14.5 0-27.2-9.8-30.9-23.8s2.5-28.8 15.1-36L64 104.9V104l4.4-1.6L240.1 4.2'
            'zM64 224h64V416h40V224h64V416h48V224h64V416h40V224h64V420.3c.6 .3 1.2 .7 1.8 1.1l48 32c11.7 7.8 '
            '17 22.4 12.9 35.9S494.1 512 480 512H32c-14.1 0-26.5-9.2-30.6-22.7s1.1-28.1 12.9-35.9l48-32c.6-.4'
            ' 1.2-.7 1.8-1.1V224z'),
    "layer-group": ("0 0 576 512", 'M264.5 5.2c14.9-6.9 32.1-6.9 47 0l218.6 101c8.5 3.9 13.9 12.4 13.9 21.8s-5.4 17.9-13.9 21.8l-218'
            '.6 101c-14.9 6.9-32.1 6.9-47 0L45.9 149.8C37.4 145.8 32 137.3 32 128s5.4-17.9 13.9-21.8L264.5 5.'
            '2zM476.9 209.6l53.2 24.6c8.5 3.9 13.9 12.4 13.9 21.8s-5.4 17.9-13.9 21.8l-218.6 101c-14.9 6.9-32'
            '.1 6.9-47 0L45.9 277.8C37.4 273.8 32 265.3 32 256s5.4-17.9 13.9-21.8l53.2-24.6 152 70.2c23.4 10.'
            '8 50.4 10.8 73.8 0l152-70.2zm-152 198.2l152-70.2 53.2 24.6c8.5 3.9 13.9 12.4 13.9 21.8s-5.4 17.9'
            '-13.9 21.8l-218.6 101c-14.9 6.9-32.1 6.9-47 0L45.9 405.8C37.4 401.8 32 393.3 32 384s5.4-17.9 13.'
            '9-21.8l53.2-24.6 152 70.2c23.4 10.8 50.4 10.8 73.8 0z'),
    "link": ("0 0 640 512", 'M579.8 267.7c56.5-56.5 56.5-148 0-204.5c-50-50-128.8-56.5-186.3-15.4l-1.6 1.1c-14.4 10.3-17.7 30'
            '.3-7.4 44.6s30.3 17.7 44.6 7.4l1.6-1.1c32.1-22.9 76-19.3 103.8 8.6c31.5 31.5 31.5 82.5 0 114L422'
            '.3 334.8c-31.5 31.5-82.5 31.5-114 0c-27.9-27.9-31.5-71.8-8.6-103.8l1.1-1.6c10.3-14.4 6.9-34.4-7.'
            '4-44.6s-34.4-6.9-44.6 7.4l-1.1 1.6C206.5 251.2 213 330 263 380c56.5 56.5 148 56.5 204.5 0L579.8 '
            '267.7zM60.2 244.3c-56.5 56.5-56.5 148 0 204.5c50 50 128.8 56.5 186.3 15.4l1.6-1.1c14.4-10.3 17.7'
            '-30.3 7.4-44.6s-30.3-17.7-44.6-7.4l-1.6 1.1c-32.1 22.9-76 19.3-103.8-8.6C74 372 74 321 105.5 289'
            '.5L217.7 177.2c31.5-31.5 82.5-31.5 114 0c27.9 27.9 31.5 71.8 8.6 103.9l-1.1 1.6c-10.3 14.4-6.9 3'
            '4.4 7.4 44.6s34.4 6.9 44.6-7.4l1.1-1.6C433.5 260.8 427 182 377 132c-56.5-56.5-148-56.5-204.5 0L6'
            '0.2 244.3z'),
    "magnifying-glass": ("0 0 512 512", 'M416 208c0 45.9-14.9 88.3-40 122.7L502.6 457.4c12.5 12.5 12.5 32.8 0 45.3s-32.8 12.5-45.3 0L330.'
            '7 376c-34.4 25.2-76.8 40-122.7 40C93.1 416 0 322.9 0 208S93.1 0 208 0S416 93.1 416 208zM208 352a'
            '144 144 0 1 0 0-288 144 144 0 1 0 0 288z'),
    "map": ("0 0 576 512", 'M384 476.1L192 421.2V35.9L384 90.8V476.1zm32-1.2V88.4L543.1 37.5c15.8-6.3 32.9 5.3 32.9 22.3V394'
            '.6c0 9.8-6 18.6-15.1 22.3L416 474.8zM15.1 95.1L160 37.2V423.6L32.9 474.5C17.1 480.8 0 469.2 0 45'
            '2.2V117.4c0-9.8 6-18.6 15.1-22.3z'),
    "masks-theater": ("0 0 640 512", 'M74.6 373.2c41.7 36.1 108 82.5 166.1 73.7c6.1-.9 12.1-2.5 18-4.5c-9.2-12.3-17.3-24.4-24.2-35.4c-'
            '21.9-35-28.8-75.2-25.9-113.6c-20.6 4.1-39.2 13-54.7 25.4c-6.5 5.2-16.3 1.3-14.8-7c6.4-33.5 33-60'
            '.9 68.2-66.3c2.6-.4 5.3-.7 7.9-.8l19.4-131.3c2-13.8 8-32.7 25-45.9C278.2 53.2 310.5 37 363.2 32.'
            '2c-.8-.7-1.6-1.4-2.4-2.1C340.6 14.5 288.4-11.5 175.7 5.6S20.5 63 5.7 83.9C0 91.9-.8 102 .6 111.8'
            'L24.8 276.1c5.5 37.3 21.5 72.6 49.8 97.2zm87.7-219.6c4.4-3.1 10.8-2 11.8 3.3c.1 .5 .2 1.1 .3 1.6'
            'c3.2 21.8-11.6 42-33.1 45.3s-41.5-11.8-44.7-33.5c-.1-.5-.1-1.1-.2-1.6c-.6-5.4 5.2-8.4 10.3-6.7c9'
            ' 3 18.8 3.9 28.7 2.4s19.1-5.3 26.8-10.8zM261.6 390c29.4 46.9 79.5 110.9 137.6 119.7s124.5-37.5 1'
            '66.1-73.7c28.3-24.5 44.3-59.8 49.8-97.2l24.2-164.3c1.4-9.8 .6-19.9-5.1-27.9c-14.8-20.9-57.3-61.2'
            '-170-78.3S299.4 77.2 279.2 92.8c-7.8 6-11.5 15.4-12.9 25.2L242.1 282.3c-5.5 37.3-.4 75.8 19.6 10'
            '7.7zM404.5 235.3c-7.7-5.5-16.8-9.3-26.8-10.8s-19.8-.6-28.7 2.4c-5.1 1.7-10.9-1.3-10.3-6.7c.1-.5 '
            '.1-1.1 .2-1.6c3.2-21.8 23.2-36.8 44.7-33.5s36.3 23.5 33.1 45.3c-.1 .5-.2 1.1-.3 1.6c-1 5.3-7.4 6'
            '.4-11.8 3.3zm136.2 15.5c-1 5.3-7.4 6.4-11.8 3.3c-7.7-5.5-16.8-9.3-26.8-10.8s-19.8-.6-28.7 2.4c-5'
            '.1 1.7-10.9-1.3-10.3-6.7c.1-.5 .1-1.1 .2-1.6c3.2-21.8 23.2-36.8 44.7-33.5s36.3 23.5 33.1 45.3c-.'
            '1 .5-.2 1.1-.3 1.6zM530 350.2c-19.6 44.7-66.8 72.5-116.8 64.9s-87.1-48.2-93-96.7c-1-8.3 8.9-12.1'
            ' 15.2-6.7c23.9 20.8 53.6 35.3 87 40.3s66.1 .1 94.9-12.8c7.6-3.4 16 3.2 12.6 10.9z'),
    "newspaper": ("0 0 512 512", 'M96 96c0-35.3 28.7-64 64-64H448c35.3 0 64 28.7 64 64V416c0 35.3-28.7 64-64 64H80c-44.2 0-80-35.8'
            '-80-80V128c0-17.7 14.3-32 32-32s32 14.3 32 32V400c0 8.8 7.2 16 16 16s16-7.2 16-16V96zm64 24v80c0'
            ' 13.3 10.7 24 24 24H296c13.3 0 24-10.7 24-24V120c0-13.3-10.7-24-24-24H184c-13.3 0-24 10.7-24 24z'
            'm208-8c0 8.8 7.2 16 16 16h48c8.8 0 16-7.2 16-16s-7.2-16-16-16H384c-8.8 0-16 7.2-16 16zm0 96c0 8.'
            '8 7.2 16 16 16h48c8.8 0 16-7.2 16-16s-7.2-16-16-16H384c-8.8 0-16 7.2-16 16zM160 304c0 8.8 7.2 16'
            ' 16 16H432c8.8 0 16-7.2 16-16s-7.2-16-16-16H176c-8.8 0-16 7.2-16 16zm0 96c0 8.8 7.2 16 16 16H432'
            'c8.8 0 16-7.2 16-16s-7.2-16-16-16H176c-8.8 0-16 7.2-16 16z'),
    "pen-fancy": ("0 0 512 512", 'M373.5 27.1C388.5 9.9 410.2 0 433 0c43.6 0 79 35.4 79 79c0 22.8-9.9 44.6-27.1 59.6L277.7 319l-10'
            '.3-10.3-64-64L193 234.3 373.5 27.1zM170.3 256.9l10.4 10.4 64 64 10.4 10.4-19.2 83.4c-3.9 17.1-16'
            '.9 30.7-33.8 35.4L24.4 510.3l95.4-95.4c2.6 .7 5.4 1.1 8.3 1.1c17.7 0 32-14.3 32-32s-14.3-32-32-3'
            '2s-32 14.3-32 32c0 2.9 .4 5.6 1.1 8.3L1.7 487.6 51.5 310c4.7-16.9 18.3-29.9 35.4-33.8l83.4-19.2z'),
    "rss": ("0 0 448 512", 'M0 64C0 46.3 14.3 32 32 32c229.8 0 416 186.2 416 416c0 17.7-14.3 32-32 32s-32-14.3-32-32C384 253'
            '.6 226.4 96 32 96C14.3 96 0 81.7 0 64zM0 416a64 64 0 1 1 128 0A64 64 0 1 1 0 416zM32 160c159.1 0'
            ' 288 128.9 288 288c0 17.7-14.3 32-32 32s-32-14.3-32-32c0-123.7-100.3-224-224-224c-17.7 0-32-14.3'
            '-32-32s14.3-32 32-32z'),
    "shield-halved": ("0 0 512 512", 'M256 0c4.6 0 9.2 1 13.4 2.9L457.7 82.8c22 9.3 38.4 31 38.3 57.2c-.5 99.2-41.3 280.7-213.6 363.2c'
            '-16.7 8-36.1 8-52.8 0C57.3 420.7 16.5 239.2 16 140c-.1-26.2 16.3-47.9 38.3-57.2L242.7 2.9C246.8 '
            '1 251.4 0 256 0zm0 66.8V444.8C394 378 431.1 230.1 432 141.4L256 66.8l0 0z'),
    "xmark": ("0 0 384 512", 'M342.6 150.6c12.5-12.5 12.5-32.8 0-45.3s-32.8-12.5-45.3 0L192 210.7 86.6 105.4c-12.5-12.5-32.8-1'
            '2.5-45.3 0s-12.5 32.8 0 45.3L146.7 256 41.4 361.4c-12.5 12.5-12.5 32.8 0 45.3s32.8 12.5 45.3 0L1'
            '92 301.3 297.4 406.6c12.5 12.5 32.8 12.5 45.3 0s12.5-32.8 0-45.3L237.3 256 342.6 150.6z'),
}
SPRITE = ("<svg aria-hidden='true' focusable='false' style='position:absolute;width:0;height:0;overflow:hidden'>"
          + "".join(f"<symbol id='fa-{n}' viewBox='{vb}'><path d='{d}'/></symbol>" for n, (vb, d) in FA.items())
          + "</svg>")


def icon(name, cls="i"):
    return f"<svg class='{cls}' aria-hidden='true' focusable='false'><use href='#fa-{name}'/></svg>"


MENU = [("Top stories", "top", "newspaper"), ("More stories", "more", "layer-group"),
        ("Most read", "most-read", "fire-flame-curved"), ("Nations", "nations", "flag")]

# Sun, moon and auto from line-md by Vjacheslav Trushkin (MIT), as in Deluminator and on gov.eurth.org:
# switching morphs one into the other, then the sun's rays turn and the stars twinkle. The "-still" versions
# are for reduced motion.
LINE_MD = (
    # light-dark-loop
    '<template id=\'i-auto\'><svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false" v'
    'iewBox="0 0 24 24"><defs><mask id="SVGPWNvGc7L"><circle cx="7.5" cy="7.5" r="5.5" fill="#fff"/><circ'
    'le cx="11" cy="7.5" r="6.5"><animate fill="freeze" attributeName="cx" dur="0.4s" values="7.5;11"/><a'
    'nimate fill="freeze" attributeName="r" dur="0.4s" values="5.5;6.5"/></circle></mask><mask id="SVGE5i'
    'ORxWn"><g fill="#fff"><circle cx="12" cy="9" r="5.5" transform="rotate(-45 12 12)"><animate fill="fr'
    'eeze" attributeName="cy" begin="0.9s" dur="0.5s" to="15"/></circle><path d="M12.62 20.62h3l-1.5 2.5Z'
    '" opacity="0"><animateTransform attributeName="transform" dur="5s" repeatCount="indefinite" type="ro'
    'tate" values="-145 14.12 14.12;-95 14.12 14.12"/><set fill="freeze" attributeName="opacity" begin="1'
    '.4s" to="1"/><animate fill="freeze" attributeName="d" begin="1.4s" dur="0.4s" values="M13.12 17.12h2'
    'l-1 2Z;M12.62 20.62h3l-1.5 2.5Z"/></path><path d="M12.62 20.62h3l-1.5 2.5Z" opacity="0"><animateTran'
    'sform attributeName="transform" dur="5s" repeatCount="indefinite" type="rotate" values="-95 14.12 14'
    '.12;-45 14.12 14.12"/><set fill="freeze" attributeName="opacity" begin="1.4s" to="1"/><animate fill='
    '"freeze" attributeName="d" begin="1.4s" dur="0.4s" values="M13.12 17.12h2l-1 2Z;M12.62 20.62h3l-1.5 '
    '2.5Z"/></path><path d="M12.62 20.62h3l-1.5 2.5Z" opacity="0"><animateTransform attributeName="transf'
    'orm" dur="5s" repeatCount="indefinite" type="rotate" values="-45 14.12 14.12;5 14.12 14.12"/><set fi'
    'll="freeze" attributeName="opacity" begin="1.4s" to="1"/><animate fill="freeze" attributeName="d" be'
    'gin="1.4s" dur="0.4s" values="M13.12 17.12h2l-1 2Z;M12.62 20.62h3l-1.5 2.5Z"/></path><path d="M12.62'
    ' 20.62h3l-1.5 2.5Z" opacity="0"><animateTransform attributeName="transform" dur="5s" repeatCount="in'
    'definite" type="rotate" values="5 14.12 14.12;55 14.12 14.12"/><set fill="freeze" attributeName="opa'
    'city" begin="1.4s" to="1"/><animate fill="freeze" attributeName="d" begin="1.4s" dur="0.4s" values="'
    'M13.12 17.12h2l-1 2Z;M12.62 20.62h3l-1.5 2.5Z"/></path></g><path d="M-4.97 12l18.38 -18.38l10.61 10.'
    '61l-18.38 18.38Z"/></mask></defs><g fill="currentColor"><path d="M0 0h24v24H0z" mask="url(#SVGPWNvGc'
    '7L)"/><path d="M0 0h24v24H0z" mask="url(#SVGE5iORxWn)"/></g><path fill="none" stroke="currentColor" '
    'stroke-dasharray="24" stroke-dashoffset="24" stroke-linecap="round" stroke-linejoin="round" stroke-w'
    'idth="2" d="M22 12h-22" transform="rotate(-45 12 12)"><animate attributeName="d" dur="5s" keyTimes="'
    '0;0.5;1" repeatCount="indefinite" values="M22 12h-22;M24 12h-22;M22 12h-22"/><animate fill="freeze" '
    'attributeName="stroke-dashoffset" begin="0.5s" dur="0.3s" to="0"/></path></svg></template>'
    # sunny-loop
    '<template id=\'i-sun\'><svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false" vi'
    'ewBox="0 0 24 24"><g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round'
    '" stroke-width="2"><path stroke-dasharray="34" d="M12 7c2.76 0 5 2.24 5 5c0 2.76 -2.24 5 -5 5c-2.76 '
    '0 -5 -2.24 -5 -5c0 -2.76 2.24 -5 5 -5Z"><animate fill="freeze" attributeName="stroke-dashoffset" dur'
    '="0.4s" values="34;0"/></path><path d="M12 21v1M21 12h1M12 3v-1M3 12h-1" opacity="0"><animateTransfo'
    'rm attributeName="transform" dur="30s" repeatCount="indefinite" type="rotate" values="0 12 12;360 12'
    ' 12"/><set fill="freeze" attributeName="opacity" begin="0.5s" to="1"/><animate fill="freeze" attribu'
    'teName="d" begin="0.5s" dur="0.2s" values="M12 19v1M19 12h1M12 5v-1M5 12h-1;M12 21v1M21 12h1M12 3v-1'
    'M3 12h-1"/></path><path d="M18.5 18.5l0.5 0.5M18.5 5.5l0.5 -0.5M5.5 5.5l-0.5 -0.5M5.5 18.5l-0.5 0.5"'
    ' opacity="0"><animateTransform attributeName="transform" dur="30s" repeatCount="indefinite" type="ro'
    'tate" values="0 12 12;360 12 12"/><set fill="freeze" attributeName="opacity" begin="0.7s" to="1"/><a'
    'nimate fill="freeze" attributeName="d" begin="0.7s" dur="0.2s" values="M17 17l0.5 0.5M17 7l0.5 -0.5M'
    '7 7l-0.5 -0.5M7 17l-0.5 0.5;M18.5 18.5l0.5 0.5M18.5 5.5l0.5 -0.5M5.5 5.5l-0.5 -0.5M5.5 18.5l-0.5 0.5'
    '"/></path></g></svg></template>'
    # moon-loop
    '<template id=\'i-moon\'><svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false" v'
    'iewBox="0 0 24 24"><path fill="none" stroke="currentColor" stroke-dasharray="56" stroke-linecap="rou'
    'nd" stroke-linejoin="round" stroke-width="2" d="M7 6c0 6.08 4.92 11 11 11c0.53 0 1.05 -0.04 1.56 -0.'
    '11c-1.61 2.47 -4.39 4.11 -7.56 4.11c-4.97 0 -9 -4.03 -9 -9c0 -3.17 1.64 -5.95 4.11 -7.56c-0.07 0.51 '
    '-0.11 1.03 -0.11 1.56Z"><animate fill="freeze" attributeName="stroke-dashoffset" dur="0.6s" values="'
    '56;0"/></path><g fill="currentColor"><path d="M15.22 6.03l2.53 -1.94l-3.19 -0.09l-1.06 -3l-1.06 3l-3'
    '.19 0.09l2.53 1.94l-0.91 3.06l2.63 -1.81l2.63 1.81l-0.91 -3.06Z" opacity="0"><animate attributeName='
    '"opacity" begin="0.7s" dur="6s" keyTimes="0;0.1;0.4;0.5;1" repeatCount="indefinite" values="0;1;1;0;'
    '0"/></path><path d="M19.61 12.25l1.64 -1.25l-2.06 -0.05l-0.69 -1.95l-0.69 1.95l-2.06 0.05l1.64 1.25l'
    '-0.59 1.98l1.7 -1.17l1.7 1.17l-0.59 -1.98Z" opacity="0"><animate attributeName="opacity" begin="0.7s'
    '" dur="6s" keyTimes="0;0.2;0.3;0.6;0.7;1" repeatCount="indefinite" values="0;0;1;1;0;0"/></path><pat'
    'h d="M13.61 5.25l1.64 -1.25l-2.06 -0.05l-0.69 -1.95l-0.69 1.95l-2.06 0.05l1.64 1.25l-0.59 1.98l1.7 -'
    '1.17l1.7 1.17Z" opacity="0"><animate attributeName="opacity" begin="3.7s" dur="6s" keyTimes="0;0.1;0'
    '.4;0.5;1" repeatCount="indefinite" values="0;1;1;0;0"/></path><path d="M20.83 9.73l1.88 -1.44l-2.37 '
    '-0.07l-0.79 -2.22l-0.79 2.23l-2.37 0.07l1.88 1.44l-0.68 2.27l1.95 -1.34l1.95 1.34Z" opacity="0"><ani'
    'mate attributeName="opacity" begin="3.7s" dur="6s" keyTimes="0;0.2;0.3;0.6;0.7;1" repeatCount="indef'
    'inite" values="0;0;1;1;0;0"/></path></g></svg></template>'
    # sunny-outline-to-moon-loop-transition
    '<template id=\'i-to-dark\'><svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false'
    '" viewBox="0 0 24 24"><defs><mask id="SVGHXYFDcmX"><path fill="#fff" d="M12 2c5.52 0 10 4.48 10 10c0'
    ' 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0 -5.52 4.48 -10 10 -10Z"><animate fill="freeze" att'
    'ributeName="d" dur="0.4s" values="M12 6c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6'
    'c0 -3.31 2.69 -6 6 -6Z;M12 2c5.52 0 10 4.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0'
    ' -5.52 4.48 -10 10 -10Z"/><set fill="freeze" attributeName="opacity" begin="0.4s" to="0"/></path><pa'
    'th d="M18 -4c5.52 0 10 4.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0 -5.52 4.48 -10 '
    '10 -10ZM12 4c4.42 0 8 3.58 8 8c0 4.42 -3.58 8 -8 8c-4.42 0 -8 -3.58 -8 -8c0 -4.42 3.58 -8 8 -8Z"><an'
    'imate fill="freeze" attributeName="d" dur="0.4s" values="M22 -4c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 '
    '6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6ZM12 8c2.21 0 4 1.79 4 4c0 2.21 -1.79 4 -4 4c-2.21 0 -4'
    ' -1.79 -4 -4c0 -2.21 1.79 -4 4 -4Z;M18 -4c5.52 0 10 4.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4'
    '.48 -10 -10c0 -5.52 4.48 -10 10 -10ZM12 4c4.42 0 8 3.58 8 8c0 4.42 -3.58 8 -8 8c-4.42 0 -8 -3.58 -8 '
    '-8c0 -4.42 3.58 -8 8 -8Z"/><set fill="freeze" attributeName="opacity" begin="0.4s" to="0"/></path></'
    'mask><mask id="SVGYzLhkdyh"><path fill="#fff" d="M18 -6c6.62 0 12 5.38 12 12c0 6.62 -5.38 12 -12 12c'
    '-6.62 0 -12 -5.38 -12 -12c0 -6.62 5.38 -12 12 -12Z"><animate fill="freeze" attributeName="d" dur="0.'
    '4s" values="M22 -6c4.42 0 8 3.58 8 8c0 4.42 -3.58 8 -8 8c-4.42 0 -8 -3.58 -8 -8c0 -4.42 3.58 -8 8 -8'
    'Z;M18 -6c6.62 0 12 5.38 12 12c0 6.62 -5.38 12 -12 12c-6.62 0 -12 -5.38 -12 -12c0 -6.62 5.38 -12 12 -'
    '12Z"/><set fill="freeze" attributeName="opacity" begin="0.4s" to="0"/></path><path d="M18 -4c5.52 0 '
    '10 4.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0 -5.52 4.48 -10 10 -10ZM2 12v-20h30v'
    '30h-20c5.52 0 10 -4.48 10 -10c0 -5.52 -4.48 -10 -10 -10c-5.52 0 -10 4.48 -10 10Z"><animate fill="fre'
    'eze" attributeName="d" dur="0.4s" values="M22 -4c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2'
    '.69 -6 -6c0 -3.31 2.69 -6 6 -6ZM6 12v-20h26v26h-20c3.31 0 6 -2.69 6 -6c0 -3.31 -2.69 -6 -6 -6c-3.31 '
    '0 -6 2.69 -6 6Z;M18 -4c5.52 0 10 4.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0 -5.52'
    ' 4.48 -10 10 -10ZM2 12v-20h30v30h-20c5.52 0 10 -4.48 10 -10c0 -5.52 -4.48 -10 -10 -10c-5.52 0 -10 4.'
    '48 -10 10Z"/><set fill="freeze" attributeName="opacity" begin="0.4s" to="0"/></path></mask></defs><p'
    'ath fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2'
    '" d="M12 21v1M21 12h1M12 3v-1M3 12h-1M18.5 18.5l0.5 0.5M18.5 5.5l0.5 -0.5M5.5 5.5l-0.5 -0.5M5.5 18.5'
    'l-0.5 0.5"><animate fill="freeze" attributeName="opacity" dur="0.4s" values="1;0"/></path><g fill="c'
    'urrentColor"><path d="M0 0h24v24H0z" mask="url(#SVGHXYFDcmX)"/><path d="M0 0h24v24H0z" mask="url(#SV'
    'GYzLhkdyh)"/></g><path fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="rou'
    'nd" stroke-width="2" d="M7 6c0 6.08 4.92 11 11 11c0.53 0 1.05 -0.04 1.56 -0.11c-1.61 2.47 -4.39 4.11'
    ' -7.56 4.11c-4.97 0 -9 -4.03 -9 -9c0 -3.17 1.64 -5.95 4.11 -7.56c-0.07 0.51 -0.11 1.03 -0.11 1.56Z" '
    'opacity="0"><set fill="freeze" attributeName="opacity" begin="0.4s" to="1"/></path><g fill="currentC'
    'olor"><path d="M15.22 6.03l2.53 -1.94l-3.19 -0.09l-1.06 -3l-1.06 3l-3.19 0.09l2.53 1.94l-0.91 3.06l2'
    '.63 -1.81l2.63 1.81l-0.91 -3.06Z" opacity="0"><animate attributeName="opacity" begin="0.4s" dur="6s"'
    ' keyTimes="0;0.1;0.4;0.5;1" repeatCount="indefinite" values="0;1;1;0;0"/></path><path d="M19.61 12.2'
    '5l1.64 -1.25l-2.06 -0.05l-0.69 -1.95l-0.69 1.95l-2.06 0.05l1.64 1.25l-0.59 1.98l1.7 -1.17l1.7 1.17l-'
    '0.59 -1.98Z" opacity="0"><animate attributeName="opacity" begin="0.4s" dur="6s" keyTimes="0;0.2;0.3;'
    '0.6;0.7;1" repeatCount="indefinite" values="0;0;1;1;0;0"/></path><path d="M13.61 5.25l1.64 -1.25l-2.'
    '06 -0.05l-0.69 -1.95l-0.69 1.95l-2.06 0.05l1.64 1.25l-0.59 1.98l1.7 -1.17l1.7 1.17Z" opacity="0"><an'
    'imate attributeName="opacity" begin="3.4s" dur="6s" keyTimes="0;0.1;0.4;0.5;1" repeatCount="indefini'
    'te" values="0;1;1;0;0"/></path><path d="M20.83 9.73l1.88 -1.44l-2.37 -0.07l-0.79 -2.22l-0.79 2.23l-2'
    '.37 0.07l1.88 1.44l-0.68 2.27l1.95 -1.34l1.95 1.34Z" opacity="0"><animate attributeName="opacity" be'
    'gin="3.4s" dur="6s" keyTimes="0;0.2;0.3;0.6;0.7;1" repeatCount="indefinite" values="0;0;1;1;0;0"/></'
    'path></g></svg></template>'
    # moon-to-sunny-outline-loop-transition
    '<template id=\'i-to-light\'><svg xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="fals'
    'e" viewBox="0 0 24 24"><defs><mask id="SVGUXuaaerw"><path fill="#fff" d="M12 6c3.31 0 6 2.69 6 6c0 3'
    '.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6Z"><animate fill="freeze" attributeName='
    '"d" dur="0.4s" values="M12 2c5.52 0 10 4.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0'
    ' -5.52 4.48 -10 10 -10Z;M12 6c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2'
    '.69 -6 6 -6Z"/></path><path d="M22 -4c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0'
    ' -3.31 2.69 -6 6 -6Z"><animate fill="freeze" attributeName="d" dur="0.4s" values="M18 -4c5.52 0 10 4'
    '.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0 -5.52 4.48 -10 10 -10Z;M22 -4c3.31 0 6 '
    '2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6Z"/><set fill="freeze" attri'
    'buteName="opacity" begin="0.4s" to="0"/></path><path d="M12 8c2.21 0 4 1.79 4 4c0 2.21 -1.79 4 -4 4c'
    '-2.21 0 -4 -1.79 -4 -4c0 -2.21 1.79 -4 4 -4Z"><animate fill="freeze" attributeName="d" dur="0.4s" va'
    'lues="M12 4c4.42 0 8 3.58 8 8c0 4.42 -3.58 8 -8 8c-4.42 0 -8 -3.58 -8 -8c0 -4.42 3.58 -8 8 -8Z;M12 8'
    'c2.21 0 4 1.79 4 4c0 2.21 -1.79 4 -4 4c-2.21 0 -4 -1.79 -4 -4c0 -2.21 1.79 -4 4 -4Z"/></path></mask>'
    '<mask id="SVGjqg97bFZ"><path fill="#fff" d="M22 -6c4.42 0 8 3.58 8 8c0 4.42 -3.58 8 -8 8c-4.42 0 -8 '
    '-3.58 -8 -8c0 -4.42 3.58 -8 8 -8Z"><animate fill="freeze" attributeName="d" dur="0.4s" values="M18 -'
    '6c6.62 0 12 5.38 12 12c0 6.62 -5.38 12 -12 12c-6.62 0 -12 -5.38 -12 -12c0 -6.62 5.38 -12 12 -12Z;M22'
    ' -6c4.42 0 8 3.58 8 8c0 4.42 -3.58 8 -8 8c-4.42 0 -8 -3.58 -8 -8c0 -4.42 3.58 -8 8 -8Z"/><set fill="'
    'freeze" attributeName="opacity" begin="0.4s" to="0"/></path><path d="M22 -4c3.31 0 6 2.69 6 6c0 3.31'
    ' -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6ZM6 12v-20h26v26h-20c3.31 0 6 -2.69 6 -6c0 '
    '-3.31 -2.69 -6 -6 -6c-3.31 0 -6 2.69 -6 6Z"><animate fill="freeze" attributeName="d" dur="0.4s" valu'
    'es="M18 -4c5.52 0 10 4.48 10 10c0 5.52 -4.48 10 -10 10c-5.52 0 -10 -4.48 -10 -10c0 -5.52 4.48 -10 10'
    ' -10ZM2 12v-20h30v30h-20c5.52 0 10 -4.48 10 -10c0 -5.52 -4.48 -10 -10 -10c-5.52 0 -10 4.48 -10 10Z;M'
    '22 -4c3.31 0 6 2.69 6 6c0 3.31 -2.69 6 -6 6c-3.31 0 -6 -2.69 -6 -6c0 -3.31 2.69 -6 6 -6ZM6 12v-20h26'
    'v26h-20c3.31 0 6 -2.69 6 -6c0 -3.31 -2.69 -6 -6 -6c-3.31 0 -6 2.69 -6 6Z"/><set fill="freeze" attrib'
    'uteName="opacity" begin="0.4s" to="0"/></path></mask></defs><g fill="currentColor"><path d="M0 0h24v'
    '24H0z" mask="url(#SVGUXuaaerw)"/><path d="M0 0h24v24H0z" mask="url(#SVGjqg97bFZ)"/></g><g fill="none'
    '" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"><path d="M12'
    ' 21v1M21 12h1M12 3v-1M3 12h-1" opacity="0"><animateTransform attributeName="transform" dur="30s" rep'
    'eatCount="indefinite" type="rotate" values="0 12 12;360 12 12"/><set fill="freeze" attributeName="op'
    'acity" begin="0.4s" to="1"/><animate fill="freeze" attributeName="d" begin="0.4s" dur="0.2s" values='
    '"M12 19v1M19 12h1M12 5v-1M5 12h-1;M12 21v1M21 12h1M12 3v-1M3 12h-1"/></path><path d="M18.5 18.5l0.5 '
    '0.5M18.5 5.5l0.5 -0.5M5.5 5.5l-0.5 -0.5M5.5 18.5l-0.5 0.5" opacity="0"><animateTransform attributeNa'
    'me="transform" dur="30s" repeatCount="indefinite" type="rotate" values="0 12 12;360 12 12"/><set fil'
    'l="freeze" attributeName="opacity" begin="0.6s" to="1"/><animate fill="freeze" attributeName="d" beg'
    'in="0.6s" dur="0.2s" values="M17 17l0.5 0.5M17 7l0.5 -0.5M7 7l-0.5 -0.5M7 17l-0.5 0.5;M18.5 18.5l0.5'
    ' 0.5M18.5 5.5l0.5 -0.5M5.5 5.5l-0.5 -0.5M5.5 18.5l-0.5 0.5"/></path></g></svg></template>'
)
CRESCENT = ("M7 6 C7 12.08 11.92 17 18 17 C18.53 17 19.05 16.96 19.56 16.89 C17.95 19.36 15.17 21 12 21 "
            "C7.03 21 3 16.97 3 12 C3 8.83 4.64 6.05 7.11 4.44 C7.04 4.95 7 5.47 7 6 Z")
STARS = ("m15.22 6.03l2.53-1.94L14.56 4L13.5 1l-1.06 3l-3.19.09l2.53 1.94l-.91 3.06l2.63-1.81l2.63 1.81z",
         "M19.61 12.25L21.25 11l-2.06-.05L18.5 9l-.69 1.95l-2.06.05l1.64 1.25l-.59 1.98l1.7-1.17l1.7 1.17z")
RAYS = ("M12 21v1M21 12h1M12 3v-1M3 12h-1", "M18.5 18.5l0.5 0.5M18.5 5.5l0.5 -0.5M5.5 5.5l-0.5 -0.5M5.5 18.5l-0.5 0.5")
SVG = "<svg viewBox='0 0 24 24' aria-hidden='true' focusable='false'>"
THEME_ICONS = LINE_MD + (
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


def tip_button(id_, cls, label, tip, inner, extra=""):
    """A control with a tooltip that shows on hover and keyboard focus and goes with Escape (WCAG 1.4.13)."""
    return (f"<button type='button' class='{cls} js-only' id='{id_}' aria-label='{esc(label)}' data-tip='{esc(tip)}'"
            f"{extra}>{inner}</button>")


THEME_BUTTON = tip_button("theme", "hdr-btn theme-btn", "Theme", "label",
                          "<span class='theme-icon' aria-hidden='true'></span>")
ORIONI_TIP = ("Orioni mode: warm newsprint paper instead of white, like the FT or De Tijd, the way the Orioni press likes "
              "it. It colours the light theme only, so turning it on leaves dark mode.")
PAPER_BUTTON = tip_button("paper", "btn paper-btn", "Orioni mode", ORIONI_TIP,
                          icon("pen-fancy") + "<span>Orioni mode</span>", " role='switch' aria-checked='false'")

SEARCH = ("<div class='search js-only' role='search'><label class='sr' for='q'>Search stories</label>"
          + icon("magnifying-glass", "search-i") +
          "<input id='q' type='search' placeholder='Search headlines, agencies, nations' autocomplete='off'>"
          "<kbd aria-hidden='true'>/</kbd></div>")

SHARE_CARD = (f"{PAGE_URL}static/share-card.jpg", 1200, 800,
              "Eurth News Network: yesterday's news today, from the nations of Eurth")
DESCRIPTION = ("Yesterday's news today: the newest stories from the nations of Eurth, the Worldbuilding & "
               "Roleplay Writing Community. Every story is fiction, written by its members.")

OWNER, SINCE = "Eurth", 2026
YEARS = str(SINCE) if datetime.date.today().year <= SINCE else f"{SINCE}–{datetime.date.today().year}"
RIGHTS = f"© {YEARS} {OWNER}. All rights reserved."

FOOTER_NAV = [  # (name, where it lives, link, icon)
    ("Forums", "eurth.org", f"{SITE}/", "comments"),
    ("Map", "map.eurth.org", "https://map.eurth.org/", "map"),
    ("Governmint", "gov.eurth.org", "https://gov.eurth.org/", "landmark"),
    ("Uptime", "status.eurth.org", "https://status.eurth.org/", "heart-pulse"),
    ("The Newsroom", "eurth.org", f"{SITE}/c/affairs/the-newsroom/36", "newspaper"),
    ("Guidelines", "eurth.org", f"{SITE}/guidelines", "book-open"),
]

PERIODICALS = [  # (topic, name, what it is): the footer shows each one's latest issue
    (5607, "The Eurth Weekly", "National and global news, reviewed every week."),
    (2829, "Rhyme Magazine", "The monthly journal of global affairs."),
]

# A lead story without a photo gets its topic's icon over one of Eurth's own maps: no people and no real places,
# so it fits whichever nation the story comes from.
TOPICS = [  # (topic, icon, map, words), the topic with the most matching words wins
    ("Conflict", "shield-halved", "night",
     r"wars?|militar\w*|arm(?:y|ies|ed)|troops?|soldiers?|attacks?|invasion|invad\w+|ambush\w*|missiles?|nav(?:y|al)|"
     r"defen[cs]e|clash\w*|rebels?|militias?|bomb\w*|ceasefire|weapons?|drones?|doctrine"),
    ("Diplomacy", "handshake", "political",
     r"treat(?:y|ies)|summits?|ambassadors?|diplomat\w*|sanctions?|allian\w+|embass(?:y|ies)|accords?|pacts?|"
     r"condemn\w*|resolution"),
    ("Politics", "landmark", "political",
     r"elect\w*|parliament\w*|presiden\w*|government\w*|minist\w*|bills?|laws?|legislat\w*|assembl\w*|vot\w+|"
     r"part(?:y|ies)|chancellor|referendum|cabinet|senate|congress|decree|coalition|protest\w*"),
    ("Economy", "coins", "satellite",
     r"currenc\w*|bank\w*|econom\w*|markets?|trade|oil|prices?|tax\w*|crypto\w*|business\w*|inflation|budgets?|gdp|"
     r"invest\w*|stocks?|wages?|energy|strikes?|workers?"),
    ("Health", "heart-pulse", "satellite",
     r"hospitals?|outbreak|health\w*|diseases?|virus\w*|vaccin\w*|medic\w*|doctors?|patients?|mrsa"),
    ("Science", "flask", "satellite",
     r"scien\w*|research\w*|space|technolog\w*|engineer\w*|climate|canal|launch\w*|ai"),
    ("Culture", "masks-theater", "satellite",
     r"festival\w*|music\w*|films?|magazines?|arts?|sports?|cultur\w*|museums?|awards?|church\w*|religio\w*|royal"),
]

# Theme surfaces for the browser's own chrome (address bar), set before the page paints.
CHROME = {"light": "#ffffff", "paper": "#fcf6e1", "dark": "#002b36"}

HEAD_SCRIPT = """(function(){var d=document.documentElement,m=window.matchMedia,t=null,p=null;
try{t=localStorage.getItem("enn:theme");p=localStorage.getItem("enn:paper")}catch(e){}
var dark=t==="dark"||(t!=="light"&&!!m&&m("(prefers-color-scheme: dark)").matches);
d.setAttribute("data-theme",dark?"dark":"light");if(p==="1")d.setAttribute("data-paper","");
d.className+=" js"+(!!m&&m("(prefers-reduced-motion: reduce)").matches?"":" anim");
var e=document.getElementById("theme-color");if(e)e.setAttribute("content",dark?"%s":p==="1"?"%s":"%s")})();""" % (
    CHROME["dark"], CHROME["paper"], CHROME["light"])

DARK = ("color-scheme:dark;--surface:#002b36;--surface-raised:#0a3a46;--line:#1f4a55;--line-strong:#8fa29d;"
        "--ink:#fcf6e1;--ink-muted:#c6d1cb;--accent-text:#a3d8f5;--highlight:#f2f481;--on-highlight:#002b36;"
        "--shade:rgba(0,0,0,.65)")

CSS = """
:root{color-scheme:light;
  --eurth-blue:#2698d4;--eurth-blue-deep:#1b6fa0;--night:#002b36;--parchment:#fcf6e1;
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
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
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
.i{display:inline-block;flex:none;width:1em;height:1em;fill:currentColor;vertical-align:-.125em}

/* The globe: a 240-frame strip, always turning (still for reduced motion) */
.orb{display:block;flex:none;width:var(--s);height:var(--s);background:0 0/var(--s) auto no-repeat;
  animation:orb 9.6s steps(240) infinite}
@keyframes orb{to{background-position:0 calc(var(--s) * -240)}}

.topbar{display:flex;justify-content:space-between;align-items:center;gap:0 16px;flex-wrap:wrap;border-bottom:1px solid var(--line);
  font:13px/20px var(--mono);color:var(--ink-muted)}
.topbar>div{display:flex;align-items:center;gap:0 12px;flex-wrap:wrap}
.topbar .controls{gap:0 8px}
.topbar a{color:var(--ink);text-underline-offset:3px}
#clock{display:inline-block;font-variant-numeric:tabular-nums}
#clock.dim .sep{visibility:hidden}
.hdr-btn{display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;margin:4px 0;padding:0;
  border:1px solid var(--line-strong);border-radius:999px;background:transparent;color:var(--ink);cursor:pointer;
  transition:background-color .2s,transform .15s}
.hdr-btn:hover{background:var(--surface-raised)}
.hdr-btn:active{transform:scale(.92)}
.theme-icon,.theme-icon svg{display:block;width:22px;height:22px}
/* Orioni mode: a button like RSS feed that works as a switch; filled in, and its pen gives a flourish, when on */
.foot-actions{display:flex;flex-wrap:wrap;gap:12px}
.paper-btn[aria-checked=true],.paper-btn[aria-checked=true]:hover:not(:disabled){background:var(--ink);color:var(--surface);
  border-color:var(--ink)}
.paper-btn[aria-checked=true] .i{animation:flourish .6s var(--ease)}
@keyframes flourish{30%{transform:rotate(-14deg) translateY(-2px)}65%{transform:rotate(8deg)}}
.tip{position:fixed;z-index:7;max-width:min(300px,calc(100vw - 16px));margin:0;padding:8px 12px;font:14px/20px var(--sans);
  color:var(--surface);background:var(--ink);border-radius:var(--radius-sm)}
.toast{position:fixed;left:50%;bottom:24px;z-index:6;max-width:calc(100vw - 32px);margin:0;padding:10px 16px;
  font:15px/22px var(--sans);color:var(--surface);background:var(--ink);border-radius:var(--radius-md);
  opacity:0;transform:translate(-50%,8px);pointer-events:none;transition:opacity .25s,transform .25s var(--ease)}
.toast.show{opacity:1;transform:translate(-50%,0)}
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
.menu a{position:relative;display:inline-flex;align-items:center;gap:8px;min-height:44px;font:700 14px/20px var(--sans);
  text-decoration:none}
.menu .i{width:14px;height:14px;fill:var(--ink-muted);transition:fill .2s,transform .25s var(--ease)}
.menu a:hover .i,.menu a:focus-visible .i{fill:var(--accent-text);transform:translateY(-1px)}
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
.edition a{color:var(--accent-text);text-underline-offset:3px}
.filter-note{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:20px 0 0;font-size:15px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;font:700 14px/20px var(--sans);
  color:var(--ink);background:transparent;border:1px solid var(--line-strong);border-radius:var(--radius-sm);padding:10px 16px;
  cursor:pointer;text-decoration:none;transition:background-color .15s,border-color .15s,transform .15s}
.btn .i{width:14px;height:14px}
.btn:hover:not(:disabled){background:var(--surface-raised);border-color:var(--ink)}
.btn:active:not(:disabled){transform:scale(.97)}
.btn:disabled{opacity:.45;cursor:default}
.btn .i-check,.btn.done .i-link{display:none}
.btn.done .i-check{display:inline-block}
/* The one brand exception to 7:1: white on Eurth blue, at the size the Eurth system allows it (3.2:1, 19px bold) */
.cta{display:inline-flex;align-items:center;gap:10px;min-height:44px;font:700 19px/24px var(--sans);color:#fff;
  background:var(--eurth-blue);border-radius:var(--radius-md);padding:10px 20px;text-decoration:none;white-space:nowrap;
  transition:background-color .15s,transform .15s}
.cta .i{width:18px;height:18px}
.cta:hover{background:var(--eurth-blue-deep)}
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
/* Placeholder for a lead story without a photo: its topic over one of Eurth's maps, in the horizon disc */
.ph{position:relative;display:flex;flex-direction:column;justify-content:center;align-items:flex-start;gap:12px;
  padding:0 0 0 clamp(24px,7%,64px);background:var(--night);color:var(--parchment)}
.ph-disc{position:absolute;right:-12%;top:-32%;width:76%;aspect-ratio:1;border-radius:9999px;
  background:var(--map) center/cover no-repeat,var(--night);box-shadow:0 0 0 6px var(--eurth-blue);transition:transform 1.2s var(--ease)}
.ph-i{position:relative;width:clamp(44px,9vw,72px);height:clamp(44px,9vw,72px);fill:var(--parchment)}
.ph-k{position:relative;font:700 14px/20px var(--sans);letter-spacing:.08em;text-transform:uppercase}
.lead:hover .ph-disc{transform:rotate(-8deg) scale(1.03)}

.group-h{display:flex;align-items:center;gap:10px;font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;
  margin:0 0 20px}
.group-h::after{content:"";flex:1;border-top:1px solid var(--ink)}
.col-h{display:flex;align-items:center;gap:10px;font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;
  margin:0 0 16px;padding-bottom:10px;border-bottom:1px solid var(--ink)}
.group-h .i,.col-h .i{width:14px;height:14px;fill:var(--accent-text)}
.top-stories{padding-top:28px}
.front{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:0 36px;padding:0 0 32px;border-bottom:4px double var(--ink)}
.lead{position:relative}
.lead .thumb{aspect-ratio:2/1;margin-bottom:16px}
.lead .kicker{font-size:14px;line-height:20px}
.lead .hl{font-size:clamp(1.75em,3.1vw,2.5em);line-height:1.2;margin-bottom:12px}
.lead .dek{font:400 1.1em/1.65 var(--serif);-webkit-line-clamp:5;margin-bottom:16px}
.lead .meta{margin-bottom:20px}
.latest{border-left:1px solid var(--line);padding-left:36px}
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
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(235px,1fr));gap:24px 36px;margin-bottom:40px}
.card{position:relative;display:flex;flex-direction:column;padding:16px;margin:0 -16px;border:1px solid transparent;
  border-top-color:var(--line);border-radius:var(--radius-sm);
  transition:background-color .2s ease,border-color .2s ease,box-shadow .2s ease}
.card:hover,.card:focus-within{background:var(--surface-raised);border-color:var(--line-strong);
  border-top-color:var(--accent-text);box-shadow:inset 0 2px 0 var(--accent-text)}
.card:hover .thumb img{transform:scale(1.04)}
.card:not(.has-thumb) .dek{-webkit-line-clamp:9}
.filtering .top-stories,.filtering .feed>.group-h{display:none}
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

/* Footer: about, Eurth's other sites, the periodicals, then the small print */
.sitefoot{border-top:4px double var(--ink);margin-top:16px}
.foot-grid{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr) minmax(0,1.5fr);gap:32px 48px;padding:32px 0;
  border-bottom:1px solid var(--line)}
.foot-title{font:400 1.6em/1.2 var(--serif);margin:0 0 12px}
.foot-about p{font-size:15px;line-height:24px;color:var(--ink-muted);margin:0 0 16px;max-width:34em}
.foot-about .orb{margin-bottom:12px}
.foot-links,.papers{list-style:none;margin:0;padding:0}
.foot-links a{display:grid;grid-template-columns:32px minmax(0,1fr);align-items:center;column-gap:10px;min-height:44px;
  padding:6px 8px;margin:0 -8px;text-decoration:none;border-radius:var(--radius-sm);transition:background-color .15s}
.foot-links a:hover{background:var(--surface-raised)}
.foot-links .i{grid-row:1/span 2;width:18px;height:18px;justify-self:center;fill:var(--accent-text);
  transition:transform .3s var(--ease)}
.foot-links a:hover .i{transform:scale(1.15) rotate(-6deg)}
.foot-links .n{font:700 15px/20px var(--sans);color:var(--ink)}
.foot-links a:hover .n{text-decoration:underline}
.foot-links .d{font:13px/20px var(--mono);color:var(--ink-muted)}
.papers{display:grid;gap:16px}
.papers a{position:relative;display:grid;grid-template-columns:84px minmax(0,1fr);gap:4px 16px;align-items:start;padding:12px;
  margin:0 -12px;text-decoration:none;border:1px solid transparent;border-radius:var(--radius-sm);
  transition:background-color .2s,border-color .2s}
.papers a:hover{background:var(--surface-raised);border-color:var(--line-strong)}
/* Covers at their own proportions; on hover they tilt toward the pointer, lifted like paper off the page */
.cover{grid-row:1/span 4;align-self:start;display:block;width:84px;overflow:hidden;border-radius:var(--radius-sm);
  transform-origin:50% 60%;transition:transform .45s var(--ease),box-shadow .45s var(--ease)}
.cover img{display:block;width:100%;height:auto}
@media (prefers-reduced-motion:no-preference){.papers a:hover .cover{box-shadow:0 0 10px rgba(0,0,0,.2);
  transform:perspective(600px) rotateX(var(--ty,0deg)) rotateY(var(--tx,0deg)) rotate(var(--turn,-3deg)) scale(var(--grow,1.06))}}
.papers a.wide{grid-template-columns:minmax(0,1fr)}
.papers a.wide .cover{grid-row:auto;width:100%;max-width:360px;margin-bottom:6px;--turn:-1deg;--grow:1.02}
.p-name{font:400 1.15em/1.3 var(--serif);color:var(--ink)}
.papers a:hover .p-name{text-decoration:underline}
.p-blurb{font-size:14px;line-height:20px;color:var(--ink-muted)}
.p-issue{font:13px/20px var(--mono);color:var(--ink-muted)}
.p-go{display:inline-flex;align-items:center;gap:6px;font:700 14px/20px var(--sans);color:var(--accent-text);margin-top:4px}
.p-go .i{width:12px;height:12px;transition:transform .25s var(--ease)}
.papers a:hover .p-go .i{transform:translateX(4px)}
.foot-legal{padding:20px 0 0;text-align:center}
.foot-legal p{font-size:13px;line-height:20px;color:var(--ink-muted);margin:0 auto 8px;max-width:56em}

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
.pager .k{display:flex;align-items:center;gap:8px;font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;
  color:var(--ink-muted);margin-bottom:6px}
.pager .older .k{justify-content:flex-end}
.pager .k .i{width:12px;height:12px}
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
   stories rise into place as they scroll in, Most read fills its meters */
@keyframes rise{from{opacity:0;transform:translateY(12px)}}
@keyframes draw{from{transform:scaleX(0)}}
@keyframes settle{from{opacity:.35;transform:scale(1.06)}}
@keyframes grow{from{transform:scaleX(0)}}
@keyframes pop{0%{opacity:0;transform:scale(.4)}70%{transform:scale(1.12)}100%{transform:none}}
@keyframes drop{from{opacity:0;transform:translateY(-6px)}}
@keyframes fade{from{opacity:0}}
.anim .masthead .title{animation:rise .8s var(--ease) both}
.anim .masthead .tagline{animation:rise .8s .15s var(--ease) both}
.anim .masthead::after{animation:draw 1s .2s var(--ease) both}
.anim .lead .thumb img,.anim .lead .ph-disc{animation:settle 1.4s var(--ease) both}
.anim .lead .ph-i,.anim .lead .ph-k{animation:rise .8s .3s var(--ease) both}
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
.anim .tip:not([hidden]){animation:fade .15s ease}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.001ms!important;animation-iteration-count:1!important;
  transition-duration:.001ms!important}.orb{animation:none!important}}

@media (min-width:860px){#reader{height:calc(100dvh - 48px);margin:24px auto;border:1px solid var(--line-strong)}}
@media (max-width:1000px){.body-grid{grid-template-columns:minmax(0,1fr) 240px}
  .foot-grid{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.foot-papers{grid-column:1/-1}}
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
  .menu-btn .i{width:14px;height:14px}
  .menu-btn .i-close,.bar.open .menu-btn .i-bars{display:none}
  .bar.open .menu-btn .i-close{display:inline-block}
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
@media (max-width:640px){.foot-grid{grid-template-columns:minmax(0,1fr)}}
@media (max-width:560px){
  .cards{grid-template-columns:minmax(0,1fr);gap:20px}
  .card.has-thumb{display:grid;grid-template-columns:minmax(0,1fr) 92px;column-gap:16px;align-content:start}
  .card.has-thumb>*{grid-column:1}
  .card.has-thumb .thumb{grid-column:2;grid-row:1/span 4;aspect-ratio:1;margin:0}
  .card .dek,.card:not(.has-thumb) .dek{-webkit-line-clamp:3}
  .pager{grid-template-columns:1fr}.pager .older{grid-column:1;text-align:left}.pager .older .k{justify-content:flex-start}
}
main:not(.filtering) .card.dup{display:none}
@media print{.bar,.rail,#reader,.skip,.comments,.topbar .controls,.tip,.toast{display:none!important}
  .reveal{opacity:1!important;animation:none!important}}
""".replace("@@DARK@@", DARK)

BASE_SCRIPT = """
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var root = document.documentElement;
  var lessMotion = window.matchMedia ? matchMedia("(prefers-reduced-motion: reduce)") : null;
  function still() { return !!(lessMotion && lessMotion.matches); }
  function stored(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function save(k, v) { try { if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch (e) {} }

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
  // a Mac; for reduced motion it shows minutes only.
  var clock = $("#clock"), lastMinute = -1, clockTimer = 0;
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
    var d = new Date(), secs = !still();
    clearTimeout(clockTimer);
    if (clock) {
      var dp = today.formatToParts(d), wd = dp[0].type === "weekday" ? dp[0].value + dp[1].value : "";
      clock.innerHTML = '<span class="c-wd">' + wd + "</span>" + dp.slice(wd ? 2 : 0).map(function (p) { return p.value; }).join("") +
        " \\u00b7 " + (secs ? withSecs : noSecs).formatToParts(d).map(function (p) { return part(p, d); }).join("");
      clock.setAttribute("datetime", d.toISOString());
      clock.title = "Your local time";
      clock.classList.toggle("dim", secs && d.getSeconds() % 2 === 1);
    }
    if (d.getMinutes() !== lastMinute) { lastMinute = d.getMinutes(); tick(); }
    var t = Date.now();
    clockTimer = setTimeout(render, secs ? 1000 - t % 1000 : 60000 - t % 60000);
  }

  // The favicon is the globe too, turning in the tab (as on gov.eurth.org), still for reduced motion.
  var fav = $("#favicon"), favTimer = 0, favSprite = null;
  function favicon() {
    clearInterval(favTimer);
    if (!fav) return;
    if (still()) { fav.href = fav.getAttribute("data-still"); return; }
    var c = document.createElement("canvas"), g = c.getContext && c.getContext("2d"), f = 0;
    if (!g) return;
    c.width = c.height = 64;
    function run() {
      favTimer = setInterval(function () {
        g.clearRect(0, 0, 64, 64);
        g.drawImage(favSprite, 0, f * 64, 64, 64, 0, 0, 64, 64);
        fav.href = c.toDataURL("image/png");
        f = (f + 2) % 240;
      }, 80);
    }
    if (favSprite) { run(); return; }
    favSprite = new Image();
    favSprite.onload = run;
    favSprite.src = fav.getAttribute("data-sprite");
  }

  // Tooltips for the header controls: on hover and keyboard focus, they stay while pointed at and go with Escape.
  var tipEl = $("#tip"), tipFor = null, tipHide = 0;
  function showTip(el) {
    if (!tipEl) return;
    clearTimeout(tipHide);
    var t = el.getAttribute("data-tip");
    tipFor = el;
    tipEl.textContent = t === "label" ? el.getAttribute("aria-label") : t;
    tipEl.hidden = false;
    if (t !== "label") el.setAttribute("aria-describedby", "tip");
    var r = el.getBoundingClientRect(), w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), innerWidth - w - 8), y = r.bottom + 8;
    if (y + h > innerHeight - 8) y = Math.max(8, r.top - h - 8);
    tipEl.style.left = x + "px";
    tipEl.style.top = y + "px";
  }
  function hideTip(now) {
    if (!tipEl) return;
    clearTimeout(tipHide);
    function go() { if (tipFor) tipFor.removeAttribute("aria-describedby"); tipFor = null; tipEl.hidden = true; }
    if (now) go(); else tipHide = setTimeout(go, 200);
  }
  $$("[data-tip]").forEach(function (el) {
    el.addEventListener("pointerenter", function () { showTip(el); });
    el.addEventListener("pointerleave", function () { hideTip(); });
    el.addEventListener("focus", function () { if (el.matches(":focus-visible")) showTip(el); });
    el.addEventListener("blur", function () { hideTip(true); });
  });
  if (tipEl) {
    tipEl.addEventListener("pointerenter", function () { clearTimeout(tipHide); });
    tipEl.addEventListener("pointerleave", function () { hideTip(); });
  }
  addEventListener("scroll", function () { if (tipFor) hideTip(true); }, { passive: true });

  // Periodical covers lean toward the pointer.
  $$(".papers a").forEach(function (a) {
    var c = $(".cover", a), clamp = function (v) { return Math.max(-0.5, Math.min(0.5, v)); };
    if (!c) return;
    a.addEventListener("pointermove", function (e) {
      var r = c.getBoundingClientRect();
      c.style.setProperty("--tx", (clamp((e.clientX - r.left) / r.width - 0.5) * 18).toFixed(1) + "deg");
      c.style.setProperty("--ty", (-clamp((e.clientY - r.top) / r.height - 0.5) * 14).toFixed(1) + "deg");
    });
    a.addEventListener("pointerleave", function () { c.style.removeProperty("--tx"); c.style.removeProperty("--ty"); });
  });

  // Section bar: sticks to the top, brings in the globe and title once the masthead has scrolled away,
  // folds into a menu on phones.
  var bar = $("#bar"), menuBtn = $("#menu-btn"), mast = $(".masthead");
  if (mast && "IntersectionObserver" in window) {
    new IntersectionObserver(function (e) { bar.classList.toggle("stuck", !e[0].isIntersecting); }).observe(mast);
  }
  function menu(open) { bar.classList.toggle("open", open); menuBtn.setAttribute("aria-expanded", String(open)); }
  menuBtn.addEventListener("click", function () { menu(!bar.classList.contains("open")); });
  $$("#panel a").forEach(function (a) { a.addEventListener("click", function () { menu(false); }); });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (tipFor) { hideTip(true); return; }
    if (bar.classList.contains("open") && e.target.id !== "q") { menu(false); menuBtn.focus(); }
  });

  // Auto, light, dark and Orioni mode (after github.com/stijn/deluminator and gov.eurth.org). Auto follows the
  // device and is remembered by forgetting the choice; each click moves on: from auto it flips the page, then keeps
  // the device's look even if the device changes, then returns to auto. Open tabs keep in step.
  var themeBtn = $("#theme"), paperBtn = $("#paper"), chrome = $("#theme-color"),
      toastEl = $("#toast"), sys = window.matchMedia && matchMedia("(prefers-color-scheme: dark)");
  var NAMES = { auto: "auto, as your device is set", light: "light, always", dark: "dark, always" };
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
  // how: "to-dark" or "to-light" plays line-md's morph from one icon to the other.
  function paint(dark, paper, how) {
    root.setAttribute("data-theme", dark ? "dark" : "light");
    if (paper) root.setAttribute("data-paper", ""); else root.removeAttribute("data-paper");
    if (chrome) chrome.setAttribute("content", dark ? "@@DARK@@" : paper ? "@@PAPER@@" : "@@LIGHT@@");
    var m = mode(), label = "Theme: " + NAMES[m] + ". Switch to " + after(m) + ".";
    themeBtn.setAttribute("aria-label", label);
    if (paperBtn) paperBtn.setAttribute("aria-checked", String(paper && !dark));
    var name = m === "auto" ? "auto" : dark ? "moon" : "sun";
    var id = still() ? name + "-still" : m !== "auto" && how ? how : name;
    $(".theme-icon", themeBtn).replaceChildren(document.getElementById("i-" + id).content.cloneNode(true));
    if (tipFor === themeBtn) showTip(themeBtn);
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
    reveal(themeBtn, e, !dark, function () { paint(dark, isPaper(), dark ? "to-dark" : "to-light"); });
  });
  // Orioni mode, the footer's newsprint switch.
  if (paperBtn) paperBtn.addEventListener("click", function (e) {
    var paper = !(isPaper() && !isDark()), wasDark = isDark();
    save("enn:paper", paper ? "1" : "0");
    if (paper && wasDark) save("enn:theme", "light");
    toast(paper ? "Orioni mode: newsprint paper." : "Orioni mode off.");
    reveal(paperBtn, e, paper, function () { paint(paper ? false : wasDark, paper, paper && wasDark ? "to-light" : ""); });
  });
  if (sys && sys.addEventListener) sys.addEventListener("change", function (e) { if (mode() === "auto") paint(e.matches, isPaper()); });
  addEventListener("storage", function (e) {
    if (e.key !== "enn:theme" && e.key !== "enn:paper") return;
    var t = stored("enn:theme");
    paint(t === "dark" || (!t && !!sys && sys.matches), stored("enn:paper") === "1");
  });

  save("enn:motion", null);  // left behind by the Pause motion switch, since removed
  paint(isDark(), isPaper());
  render();
  favicon();

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
  var dlg = $("#reader"), body = $("#r-body"), copy = $("#r-copy"), order = [], cur = -1, pushed = false, opener = null;
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
    copy.classList.remove("done");
    $(".lbl", copy).textContent = "Copy link";
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
  copy.addEventListener("click", function () {
    var url = new URL(S[cur].p, location.href).href;
    function done() { copy.classList.add("done"); $(".lbl", copy).textContent = "Link copied"; announce.textContent = "Link to this story copied"; }
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


def topic(s):
    """The story's broad topic, from the words in its headline, label and standfirst."""
    text = " ".join([s["headline"], s["label"], s["dek"]]).lower()
    best, score = ("News", "newspaper", "satellite"), 0
    for name, ic, mp, words in TOPICS:
        n = len(re.findall(rf"\b(?:{words})\b", text))
        if n > score:
            best, score = (name, ic, mp), n
    return best


def placeholder(s, base=""):
    name, ic, mp = topic(s)
    return (f"<div class='thumb ph' aria-hidden='true' style='--map:url({base}static/map-{mp}.jpg)'>"
            f"<span class='ph-disc'></span>{icon(ic, 'ph-i')}<span class='ph-k'>{name}</span></div>")


def dek(s):
    return f'<p class="dek">{esc(s["dek"])}</p>' if s["dek"] else ""


def lead_story(s):
    return (f'<article class="lead story" data-i="0">{thumb(s, eager=True) or placeholder(s)}{kicker(s)}'
            f'{headline(s, 0, "h3")}{dek(s)}{meta(s)}<a class="btn" href="{esc(page_path(s))}" data-i="0">'
            f'{icon("newspaper")}Read the full story<span class="sr">: {esc(s["headline"])}</span></a></article>')


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
        f"<link rel='icon' id='favicon' type='image/png' href='{base}static/favicon-64.png' "
        f"data-still='{base}static/favicon-64.png' data-sprite='{base}static/eurth-globe-sprite.png'>"
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
    """The globe and today's date (with the reader's local time once the script runs); the theme switch."""
    return (f"<div class='topbar'><div><a class='tap orb-link' href='{SITE}' aria-label='eurth.org'>{orb(base, 32)}</a>"
            f"<time id='clock' datetime='{now.isoformat(timespec='seconds')}'>{now:%A} {now.day} {now:%b %Y}</time></div>"
            f"<div class='controls'>{THEME_BUTTON}</div></div>")


def bar(base="", search=""):
    """Sticky section bar: links within this site (search too on the front page); a menu button on phones."""
    links = ""
    for name, anchor, ic in MENU:
        cls = " class='js-only'" if anchor == "nations" else ""
        links += f"<a href='{base}#{anchor}'{cls}>{icon(ic)}<span>{name}</span></a>"
    return (f"<nav class='bar' id='bar' aria-label='Sections'><div class='bar-in'>"
            f"<a class='brand orb-link' href='{base or '#'}'>{orb(base, 28)}Eurth News Network</a>"
            f"<button type='button' class='menu-btn js-only' id='menu-btn' aria-expanded='false' aria-controls='panel'>"
            f"{icon('bars', 'i i-bars')}{icon('xmark', 'i i-close')}<span>Menu</span></button>"
            f"<div class='panel' id='panel'><div class='menu'>{links}</div>{search}</div>"
            f"</div></nav>")


def first_image(cooked):
    p = Lines()
    p.feed(cooked)
    p.close()
    return next((im for im in p.images if im["src"].startswith("http")), None)


def fetch_periodicals():
    """The latest issue of each periodical, for the footer; a periodical that can't be read is shown without one."""
    papers = []
    for tid, name, blurb in PERIODICALS:
        paper = {"name": name, "blurb": blurb, "url": f"{SITE}/t/{tid}/last", "issue": "", "date": "", "image": None}
        try:
            last = get_json(f"{SITE}/t/{tid}.json")["post_stream"]["stream"][-1]
            post = get_json(f"{SITE}/posts/{last}.json")
            cooked = fix_urls(fix_images(post.get("cooked") or ""))
            story = extract(cooked, name)
            # The first picture is the periodical's own: The Eurth Weekly's banner, Rhyme Magazine's cover.
            paper.update(issue=story["headline"], date=post.get("created_at", ""), image=first_image(cooked) or story["image"])
        except Exception:
            pass
        papers.append(paper)
    return papers


def footer(papers, base=""):
    links = "".join(f"<li><a href='{href}'>{icon(ic)}<span class='n'>{esc(name)}</span><span class='d'>{esc(where)}</span>"
                    f"</a></li>" for name, where, href, ic in FOOTER_NAV)
    issues = ""
    for p in papers:
        im = p["image"]
        size = f" width='{im['w']}' height='{im['h']}'" if im and im["w"] and im["h"] else ""
        cover = (f"<img src='{esc(im['src'])}'{size} alt='' loading='lazy' decoding='async' referrerpolicy='no-referrer'>"
                 if im else orb(base, 84))
        latest = (f"<span class='p-issue'>Latest: {esc(p['issue'])}" + (f" · {esc(fmt_date(p['date']))}" if p["date"] else "")
                  + "</span>") if p["issue"] else ""
        wide = " class='wide'" if im and im["w"] and im["h"] and im["w"] > 1.6 * im["h"] else ""
        issues += (f"<li><a href='{esc(p['url'])}'{wide}><span class='cover'>{cover}</span><span class='p-name'>{esc(p['name'])}</span>"
                   f"<span class='p-blurb'>{esc(p['blurb'])}</span>{latest}"
                   f"<span class='p-go'>Read the latest issue{icon('arrow-right')}</span></a></li>")
    return (f"<footer class='sitefoot'><div class='foot-grid'>"
            f"<section class='foot-about' aria-labelledby='f-about'>{orb(base, 40)}"
            f"<h2 class='foot-title' id='f-about'>Eurth News Network</h2>"
            f"<p>The newest stories from The Newsroom on eurth.org, side by side. Everything here is fiction, written by the "
            f"members of Eurth, the Worldbuilding &amp; Roleplay Writing Community; each story appears as its agency "
            f"published it.</p><div class='foot-actions'><a class='btn' href='{base}news.rss'>{icon('rss')}RSS feed</a>"
            f"{PAPER_BUTTON}</div></section>"
            f"<nav class='foot-col' aria-labelledby='f-eurth'><h2 class='col-h' id='f-eurth'>{icon('globe')}Eurth</h2>"
            f"<ul class='foot-links'>{links}</ul></nav>"
            f"<section class='foot-col foot-papers' aria-labelledby='f-papers'>"
            f"<h2 class='col-h' id='f-papers'>{icon('book-open')}Our periodicals</h2><ul class='papers'>{issues}</ul></section>"
            f"</div><div class='foot-legal'>"
            f"<p>{esc(RIGHTS)} The stories are © their authors, the members of Eurth who posted them on eurth.org. Nothing "
            f"here may be copied, republished or used for text and data mining or AI training without written permission.</p>"
            f"<p>Members sometimes put images and other material from other websites in their stories, linked or copied. "
            f"Eurth doesn't own or check that material and isn't responsible for it; its rights stay with whoever holds them. "
            f"If something of yours appears here without your permission, flag the original post on eurth.org; once it comes "
            f"down there, it's gone from here at the next update.</p></div>"
            f"<div class='tip' id='tip' role='tooltip' hidden></div></footer>")


def chrome_bits():
    """What every page carries once: the toast and the theme icons (the tooltip lives in the footer, inside a landmark)."""
    return f"<p class='toast' id='toast' role='status'></p>{THEME_ICONS}"


def build_html(items, papers):
    now = datetime.datetime.now(datetime.timezone.utc)
    nations = {}
    for s in items:
        if s["author"] != "system":
            nations.setdefault(s["nation"], [s["avatar"], 0])[1] += 1
    agencies = {s["agency"] for s in items}

    feed = ""
    if len(items) > FRONT:
        feed = (f'<h2 class="group-h">{icon("layer-group")}More stories</h2>'
                f'<div class="cards">{"".join(card(s, i) for i, s in enumerate(items))}</div>')
    front = ""
    if items:
        front = (f'<section class="top-stories" id="top" aria-labelledby="top-h">'
                 f'<h2 class="group-h" id="top-h">{icon("newspaper")}Top stories</h2>'
                 f'<div class="front">{lead_story(items[0])}'
                 f'<div class="latest"><h2 class="col-h">{icon("bolt")}Also new</h2>'
                 f'{"".join(side_story(items[i], i) for i in range(1, min(FRONT, len(items))))}</div></div></section>')

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
        rail += (f'<section id="most-read"><h2 class="col-h">{icon("fire-flame-curved")}Most read</h2>'
                 f'<ol class="mostread">{most_read}</ol></section>')
    if chips:
        rail += (f'<section class="js-only" id="nations"><h2 class="col-h">{icon("flag")}Nations in this edition</h2>'
                 f'<ul class="nations">{chips}</ul></section>')

    data = [{
        "id": s["id"], "h": s["headline"], "ag": s["agency"], "n": s["nation"], "d": s["date"], "u": s["url"],
        "p": page_path(s), "a": s["avatar"], "m": s["minutes"],
        "k": short_agency(s["agency"]) + (f' · {s["label"]}' if s["label"] else ""),
    } for s in items]
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    bodies = "".join(f'<template id="b{i}">{s["cooked"]}</template>' for i, s in enumerate(items))
    stamp = now.isoformat(timespec="seconds")

    return (
        f"<!doctype html><html lang='en'>"
        + head("Eurth News Network", "Eurth News Network", DESCRIPTION, PAGE_URL, SHARE_CARD, "",
               "<meta property='og:type' content='website'><meta name='referrer' content='no-referrer'>")
        + f"<body>{SPRITE}<a class='skip' href='#main'>Skip to stories</a>"
        f"<div class='paper'>"
        f"  <header>{topbar(now)}"
        f"    <div class='masthead'><h1 class='title'>Eurth News Network</h1>"
        f"      <p class='tagline'>Yesterday's News Today</p></div></header>"
        f"  {bar('', SEARCH)}"
        f"  <main id='main'>"
        f"    <div class='toolbar'><p class='edition'><strong>{plural(len(items), 'story')}</strong> from "
        f"{plural(len(agencies), 'agency')} in {plural(len(nations), 'nation')} · updated <time datetime='{stamp}' "
        f"data-rel>{now:%H:%M} <abbr title='Coordinated Universal Time'>UTC</abbr></time> · "
        f"<a href='news.rss'>RSS feed</a><span class='new-count' hidden></span></p></div>"
        f"    <p class='filter-note' hidden><span class='filter-text' role='status'></span>"
        f"      <button type='button' class='btn clear-filters'>{icon('xmark')}Clear</button></p>"
        f"    {front}"
        f"    <div class='body-grid'>"
        f"      <div class='feed' id='more'>{feed}"
        f"        <p class='empty' hidden>No stories match. <button type='button' class='btn clear-filters'>"
        f"{icon('xmark')}Clear search</button></p>"
        f"      </div>"
        f"      <aside class='rail' aria-label='Most read and nations'>{rail}</aside>"
        f"    </div>"
        f"  </main>"
        f"  {footer(papers)}"
        f"</div>"
        f"<dialog id='reader' aria-labelledby='r-title'><div class='r-scroll'>"
        f"  <div class='r-bar'>"
        f"    <button type='button' class='btn' id='r-close'>{icon('xmark')}Close</button>"
        f"    <span class='r-pos' id='r-pos'></span>"
        f"    <button type='button' class='btn' id='r-prev'>{icon('arrow-left')}Newer<span class='sr'> story</span></button>"
        f"    <button type='button' class='btn' id='r-next'>Older<span class='sr'> story</span>{icon('arrow-right')}</button>"
        f"  </div>"
        f"  <article class='r-article'>"
        f"    <p class='kicker' id='r-kicker'></p>"
        f"    <h2 class='r-title' id='r-title'></h2>"
        f"    <p class='meta r-meta'><img class='av' id='r-av' alt='' width='18' height='18' referrerpolicy='no-referrer'>"
        f"<span class='nation' id='r-nation'></span><span>· <time id='r-time' data-rel></time></span>"
        f"<span>· <span id='r-min'></span> <abbr title='minutes'>min</abbr> read</span></p>"
        f"    <p class='r-source'>As published by <span id='r-agency'></span></p>"
        f"    <div class='prose' id='r-body'></div>"
        f"    <div class='r-foot'><a class='cta' id='r-link' href='{SITE}'>{icon('comments')}Read and discuss on Eurth"
        f"<span class='sr r-what'></span></a><a class='btn' id='r-page' href='./'>{icon('file-lines')}Story page"
        f"<span class='sr r-what'></span></a><button type='button' class='btn' id='r-copy'>"
        f"{icon('link', 'i i-link')}{icon('check', 'i i-check')}<span class='lbl'>Copy link</span></button></div>"
        f"    <p class='sr' id='announce' aria-live='polite'></p>"
        f"  </article>"
        f"</div></dialog>"
        f"{chrome_bits()}"
        f"<script type='application/json' id='stories-data'>{data_json}</script>"
        f"{bodies}"
        f"<script>(function () {{{BASE_SCRIPT}{SCRIPT}}})();</script>"
        f"</body></html>"
    )


def comments(s):
    """Discourse's embedded discussion for this story's page (see README: Comments)."""
    return (f"<section class='comments' id='comments' aria-label='Discussion'><h2 class='col-h'>{icon('comments')}Discussion</h2>"
            f"<div id='discourse-comments'></div></section>"
            f"<script>window.DiscourseEmbed={{discourseUrl:'{SITE}/',discourseEmbedUrl:'{PAGE_URL}{page_path(s)}'}};"
            f"(function(){{var d=document.createElement('script');d.async=true;"
            f"d.src=DiscourseEmbed.discourseUrl+'javascripts/embed.js';document.head.appendChild(d);}})();</script>")


def build_story(items, i, papers):
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
        pager += (f"<a class='newer' href='{base}{page_path(items[i - 1])}'><span class='k'>{icon('arrow-left')}Newer story"
                  f"</span><span class='t'>{esc(items[i - 1]['headline'])}</span></a>")
    if i < len(items) - 1:
        pager += (f"<a class='older' href='{base}{page_path(items[i + 1])}'><span class='k'>Older story{icon('arrow-right')}"
                  f"</span><span class='t'>{esc(items[i + 1]['headline'])}</span></a>")

    return (
        f"<!doctype html><html lang='en'>"
        + head(f"{title} · Eurth News Network", s["headline"], description, url, story_image(s), base, extra)
        + f"<body>{SPRITE}<a class='skip' href='#story'>Skip to story</a>"
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
        f"      <div class='r-foot'><a class='cta' href='{esc(s['url'])}'>{icon('comments')}Read and discuss on Eurth"
        f"<span class='sr'>: {esc(s['headline'])}</span></a><a class='btn' href='{base}'>{icon('newspaper')}Front page</a></div>"
        f"    </article>"
        f"    {comments(s) if EMBED_COMMENTS else ''}"
        f"    <nav class='pager' aria-label='Newer and older stories'>{pager}</nav>"
        f"  </main>"
        f"  {footer(papers, base)}"
        f"</div>{chrome_bits()}"
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
    papers = fetch_periodicals()
    write(f"{OUTDIR}/index.html", build_html(items, papers))
    write(f"{OUTDIR}/oembed.json", oembed("Eurth News Network", SHARE_CARD))
    for i, s in enumerate(items):
        page = f"{OUTDIR}/{page_path(s)}"
        write(page + "index.html", build_story(items, i, papers))
        write(page + "oembed.json", oembed(s["headline"], story_image(s), (s["nation"], f"{SITE}/u/{s['author']}")))
    write(f"{OUTDIR}/news.rss", build_rss(items))
    write(f"{OUTDIR}/.well-known/tdmrep.json", json.dumps([{"location": "/", "tdm-reservation": 1}]))
    print(f"Updated {len(items)} stories -> {OUTDIR}/")


if __name__ == "__main__":
    main()
