#!/usr/bin/env python3
"""Rolling news feed: newest 25 stories (replies) in The Newsroom, category 36, on eurth.org."""
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
    """Rewrite Discourse's relative /u/, /t/, /c/, /uploads/ URLs to absolute."""
    def repl(m):
        attr, q, url = m.group(1), m.group(2), m.group(3)
        if url.startswith(("http:", "https:", "//", "mailto:", "tel:", "javascript:", "data:", "#")):
            return m.group(0)
        if url.startswith("/"):
            return f"{attr}={q}{SITE}{url}{q}"
        return m.group(0)

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
# Styled after the Eurth design system: forum light / Solarized night themes, Libre Baskerville
# for headlines, Helvetica for labels and text, JetBrains Mono for dates. The page frame is
# Eurth's own (OOC); the stories inside it keep their agencies' words, never their branding.

FONTS = ("https://fonts.googleapis.com/css2?family=Libre+Baskerville:ital,wght@0,400;0,700;1,400"
         "&family=JetBrains+Mono:wght@400;700&display=swap")

SECTIONS = [  # the in-character categories on eurth.org, with their forum colours
    ("Affairs", "affairs/17", "cat-blue"),
    ("Business", "business/18", "cat-grey"),
    ("Conflict", "conflict/19", "cat-silver"),
    ("Diplomacy", "diplomacy/20", "cat-vermilion"),
    ("Entertainment", "entertainment/21", "cat-red"),
    ("Future & Past", "future-past/22", "cat-orange"),
    ("The Newsroom", "affairs/the-newsroom/36", "cat-red"),
]

SHARE_CARD = (f"{PAGE_URL}static/share-card.jpg", 1200, 800,
              "Eurth News Network: yesterday's news today, from the nations of Eurth")
DESCRIPTION = ("Yesterday's news today: the newest stories from the nations of Eurth, the Worldbuilding & "
               "Roleplay Writing Community. Every story is fiction, written by its members.")

CSS = """
:root{color-scheme:light dark;
  --eurth-blue:#2698d4;--eurth-blue-deep:#1b6fa0;--night:#002b36;
  --surface:#ffffff;--surface-raised:#f8f8f8;--line:#e9e9e9;--line-strong:#646464;--ink:#222222;--ink-muted:#646464;
  --accent-text:#1b6fa0;--highlight:#ffff4d;--on-highlight:#222222;--shade:rgba(0,43,54,.6);
  --cat-blue:#2698d4;--cat-grey:#808281;--cat-silver:#b3b5b4;--cat-vermilion:#e45735;--cat-red:#bf1e2e;--cat-orange:#f1592a;
  --radius-sm:2px;--radius-md:12px;--radius-avatar:10%;
  --serif:"Libre Baskerville",Baskerville,Georgia,serif;
  --sans:"Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root{
  --surface:#002b36;--surface-raised:#0d353f;--line:#193f47;--line-strong:#798c88;--ink:#fcf6e1;--ink-muted:#97a59d;
  --accent-text:#3eafe7;--highlight:#f2f481;--on-highlight:#002b36;--shade:rgba(0,0,0,.65)}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--surface);color:var(--ink);font:16px/1.5 var(--sans)}
[hidden]{display:none!important}
html:not(.js) .js-only{display:none!important}
a{color:inherit}
:focus-visible{outline:2px solid var(--accent-text);outline-offset:2px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.skip{position:absolute;left:-999px;top:.5em;z-index:5;background:var(--ink);color:var(--surface);padding:.5em 1em}
.skip:focus{left:.5em}
.paper{max-width:1280px;margin:0 auto;padding:0 2em 2.5em}

.topbar{display:flex;justify-content:space-between;align-items:center;gap:6px 16px;flex-wrap:wrap;padding:12px 0;
  border-bottom:1px solid var(--line);font:12px/20px var(--mono);color:var(--ink-muted)}
.topbar>span{display:inline-flex;align-items:center;gap:12px}
.topbar img{display:block;width:24px;height:24px}
.topbar a{color:var(--ink)}
.masthead{text-align:center;padding:1.4em .5em 1.1em;border-bottom:4px double var(--ink)}
.masthead .title{display:block;margin:0;font:400 clamp(2em,6.4vw,4em)/1.08 var(--serif);letter-spacing:-.01em;
  text-decoration:none;text-wrap:balance}
.tagline{font:italic 1.05em/1.4 var(--serif);color:var(--ink-muted);margin:.5em 0 0}
.masthead.slim{padding:1em .5em .9em}
.masthead.slim .title{font-size:clamp(1.5em,4vw,2.25em)}
.nav-strip{display:flex;justify-content:center;gap:8px 26px;flex-wrap:wrap;padding:12px .5em;border-bottom:1px solid var(--ink)}
.chip{display:inline-flex;align-items:center;gap:8px;font:700 14px/20px var(--sans);color:var(--ink);text-decoration:none}
.chip::before{content:"";width:10px;height:10px;border-radius:var(--radius-sm);background:var(--chip,var(--eurth-blue));flex:none}
a.chip:hover{text-decoration:underline;text-underline-offset:3px}

.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px 24px;flex-wrap:wrap;padding:12px 0;
  border-bottom:1px solid var(--line)}
.edition{margin:0;font-size:14px;line-height:20px;color:var(--ink-muted)}
.edition strong,.new-count{color:var(--ink)}
.search{position:relative;flex:0 1 340px}
.search input{width:100%;font:15px/20px var(--sans);padding:8px 40px 8px 10px;background:var(--surface);color:var(--ink);
  border:1px solid var(--line-strong);border-radius:var(--radius-sm);-webkit-appearance:none;appearance:none}
.search input::placeholder{color:var(--ink-muted)}
.search kbd{position:absolute;right:8px;top:50%;transform:translateY(-50%);font:12px/1 var(--mono);color:var(--ink-muted);
  border:1px solid var(--line-strong);border-radius:var(--radius-sm);padding:3px 6px;pointer-events:none}
.search input:focus+kbd,.search input:not(:placeholder-shown)+kbd{display:none}
.filter-note{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:20px 0 0;font-size:15px}
.btn{display:inline-flex;align-items:center;font:700 14px/20px var(--sans);color:var(--ink);background:transparent;
  border:1px solid var(--line-strong);border-radius:var(--radius-sm);padding:7px 14px;cursor:pointer;text-decoration:none}
.btn:hover:not(:disabled){background:var(--surface-raised);border-color:var(--ink)}
.btn:disabled{opacity:.35;cursor:default}
.cta{display:inline-flex;align-items:center;font:700 15px/20px var(--sans);color:var(--night);background:var(--eurth-blue);
  border-radius:var(--radius-md);padding:8px 16px;text-decoration:none;white-space:nowrap}
.cta:hover{background:var(--eurth-blue-deep);color:#fff}

.kicker{margin:0 0 8px;font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink-muted)}
.kicker .label{color:var(--ink)}
.is-new .kicker::before{content:"New";display:inline-block;margin-right:8px;padding:1px 6px;border-radius:var(--radius-sm);
  background:var(--highlight);color:var(--on-highlight)}
.hl{font:400 1.15em/1.35 var(--serif);margin:0 0 8px;text-wrap:balance}
.hl a{text-decoration:none}
.hl a:hover{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:.18em}
.is-read .hl a{color:var(--ink-muted)}
.dek{margin:0 0 12px;font-size:14px;line-height:20px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;
  overflow:hidden}
.meta{margin:auto 0 0;font:12px/18px var(--mono);color:var(--ink-muted);display:flex;align-items:center;flex-wrap:wrap;gap:2px 8px}
.av{width:18px;height:18px;border-radius:var(--radius-avatar);object-fit:cover;background:var(--surface-raised);flex:none}
.nation{color:var(--ink);font-weight:700}
.thumb{aspect-ratio:3/2;overflow:hidden;background:var(--surface-raised);border-radius:var(--radius-sm);margin:0 0 12px}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}

.front{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:0 36px;padding:32px 0;border-bottom:4px double var(--ink)}
.lead{position:relative}
.lead .thumb{aspect-ratio:2/1;margin-bottom:16px}
.lead .kicker{font-size:14px;line-height:20px}
.lead .hl{font-size:clamp(1.75em,3.1vw,2.5em);line-height:1.2;margin-bottom:12px}
.lead .dek{font:400 1.1em/1.65 var(--serif);-webkit-line-clamp:5;margin-bottom:16px}
.lead .meta{font-size:13px;margin-bottom:20px}
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
.card .hl a::after,.side .hl a::after{content:"";position:absolute;inset:0}

.body-grid{display:grid;grid-template-columns:minmax(0,1fr) 290px;gap:36px;margin-top:32px}
.group-h{display:flex;align-items:center;gap:12px;font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;
  margin:0 0 20px}
.group-h::after{content:"";flex:1;border-top:1px solid var(--ink)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(235px,1fr));gap:32px 28px;margin-bottom:40px}
.card{position:relative;display:flex;flex-direction:column;padding-top:16px;border-top:1px solid var(--line)}
.card:not(.has-thumb) .dek{-webkit-line-clamp:9}
.filtering .front,.filtering .group-h{display:none}
.empty{padding:32px 0;text-align:center;color:var(--ink-muted)}

.rail{border-left:1px solid var(--line);padding-left:36px;align-self:start;position:sticky;top:16px}
.rail section{margin-bottom:40px}
.mostread{list-style:none;margin:0;padding:0}
.mostread li{position:relative;display:grid;grid-template-columns:28px minmax(0,1fr);gap:8px;padding:12px 0;
  border-bottom:1px solid var(--line)}
.mostread li:first-child{padding-top:0}
.mostread .num{font:400 1.6em/1 var(--serif);color:var(--accent-text)}
.mostread a{font:400 1em/1.4 var(--serif);text-decoration:none}
.mostread a:hover{text-decoration:underline}
.mostread a::after{content:"";position:absolute;inset:0}
.mostread .sub{display:block;font:12px/18px var(--mono);color:var(--ink-muted);margin-top:6px}
.nations{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:6px}
.nations button{display:inline-flex;align-items:center;gap:6px;font:13px/18px var(--sans);color:var(--ink);padding:4px 8px 4px 4px;
  border:1px solid var(--line-strong);border-radius:var(--radius-sm);background:transparent;cursor:pointer}
.nations button:hover{border-color:var(--ink)}
.nations button[aria-pressed=true]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.nations .n{font-family:var(--mono);color:var(--ink-muted)}
.nations button[aria-pressed=true] .n{color:inherit}

.sitefoot{text-align:center;border-top:4px double var(--ink);margin-top:16px;padding-top:24px}
.sitefoot .title{font:400 1.6em/1.2 var(--serif);margin:0 0 8px}
.sitefoot p{font-size:14px;line-height:20px;color:var(--ink-muted);margin:8px auto;max-width:46em}
.sitefoot a{color:var(--accent-text)}

#reader{padding:0;border:0;width:min(800px,100vw);max-width:100vw;height:100vh;height:100dvh;max-height:100dvh;margin:0 auto;
  background:var(--surface);color:var(--ink)}
#reader::backdrop{background:var(--shade)}
.r-scroll{height:100%;overflow:auto;overscroll-behavior:contain}
.r-bar{position:sticky;top:0;z-index:1;display:flex;align-items:center;gap:8px;padding:10px clamp(16px,4vw,40px);
  background:var(--surface);border-bottom:1px solid var(--line)}
.r-pos{margin-left:auto;margin-right:6px;font:12px/18px var(--mono);color:var(--ink-muted)}
.r-article{padding:28px clamp(18px,6vw,56px) 48px}
.r-article .kicker{font-size:14px;line-height:20px}
.r-title{font:400 clamp(1.65em,4.2vw,2.5em)/1.22 var(--serif);margin:4px 0 14px;text-wrap:balance}
.r-meta{font-size:13px;padding-bottom:16px;margin-bottom:12px;border-bottom:1px solid var(--line)}
.r-source{font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink-muted);margin:0 0 24px}
.r-foot{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:40px;padding-top:20px;border-top:4px double var(--ink)}
html.reading{overflow:hidden}
.prose{font:17px/1.65 var(--sans);overflow-wrap:anywhere}
.prose img{max-width:100%;height:auto}
.prose img.emoji{width:1.2em;height:1.2em;vertical-align:-.2em}
.prose h1,.prose h2,.prose h3,.prose h4,.prose h5{font-family:var(--serif);font-weight:400;line-height:1.3;margin:1.4em 0 .5em}
.prose h1{font-size:1.5em}.prose h2{font-size:1.3em}.prose h3{font-size:1.15em}
.prose .anchor{display:none}
.prose a{color:var(--accent-text);text-underline-offset:.15em}
.prose blockquote{margin:1.2em 0;padding:0 0 0 1.1em;border-left:3px solid var(--line)}
.prose hr{border:0;border-top:1px solid var(--line);margin:1.6em 0}
.prose table{border-collapse:collapse;display:block;max-width:100%;overflow-x:auto;font-size:.9em}
.prose td,.prose th{border:1px solid var(--line);padding:6px 10px}
.prose pre{background:var(--surface-raised);padding:12px;overflow:auto;border-radius:var(--radius-sm)}
.prose code{font-family:var(--mono);font-size:.9em;background:var(--surface-raised);padding:1px 4px}
.prose details{border:1px solid var(--line);border-radius:var(--radius-sm);padding:8px 14px;margin:1.2em 0}
.prose aside.onebox{border:1px solid var(--line);border-radius:var(--radius-sm);padding:12px;margin:1.2em 0;font-size:.85em}
@media (prefers-color-scheme:dark){.prose [style*=color]{color:inherit!important}}

.story-page{max-width:800px;margin:0 auto}
.story-page .r-article{padding:32px 0 8px}
.pager{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:32px 0 8px;padding-top:20px;border-top:1px solid var(--line)}
.pager a{display:block;text-decoration:none}
.pager .k{display:block;font:700 12px/16px var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink-muted);margin-bottom:6px}
.pager .t{font:400 1.05em/1.4 var(--serif)}
.pager a:hover .t{text-decoration:underline}
.pager .older{grid-column:2;text-align:right}
.comments{margin-top:40px}

@media (min-width:860px){#reader{height:calc(100dvh - 48px);margin:24px auto;border:1px solid var(--line)}}
@media (prefers-reduced-motion:no-preference){#reader[open]{animation:rise .18s ease-out}
  @keyframes rise{from{opacity:0;transform:translateY(8px)}}}
@media (max-width:1000px){.body-grid{grid-template-columns:minmax(0,1fr) 240px}}
@media (max-width:860px){
  .paper{padding:0 16px 32px}
  .front,.body-grid{grid-template-columns:minmax(0,1fr)}
  .latest{border-left:0;padding-left:0;margin-top:32px}
  .lead .thumb{margin-left:-16px;margin-right:-16px;border-radius:0}
  .rail{border-left:0;padding-left:0;position:static;border-top:4px double var(--ink);padding-top:24px}
  .search{flex-basis:100%}
}
@media (max-width:560px){
  .cards{grid-template-columns:minmax(0,1fr);gap:20px}
  .card.has-thumb{display:grid;grid-template-columns:minmax(0,1fr) 92px;column-gap:16px;align-content:start}
  .card.has-thumb>*{grid-column:1}
  .card.has-thumb .thumb{grid-column:2;grid-row:1/span 4;aspect-ratio:1;margin:0}
  .card .dek,.card:not(.has-thumb) .dek{-webkit-line-clamp:3}
  .nav-strip{gap:6px 18px}
  .pager{grid-template-columns:1fr}.pager .older{grid-column:1;text-align:left}
}
main:not(.filtering) .card.dup{display:none}
@media print{.toolbar,.nav-strip,.rail,#reader,.skip,.comments{display:none!important}}
"""

SCRIPT = """
(function () {
  var S = JSON.parse(document.getElementById("stories-data").textContent);
  var store = {
    get: function (k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  };
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var main = $("#main"), q = $("#q"), note = $(".filter-note"), empty = $(".empty");

  // Relative times, refreshed every minute; the full date stays in the tooltip.
  var day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });
  var dayYear = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });
  var full = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "short", year: "numeric",
                                                hour: "2-digit", minute: "2-digit" });
  function ago(t) {
    var s = (Date.now() - t) / 1000, d = Math.floor(s / 86400);
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
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
  tick();
  setInterval(tick, 60000);

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
    nc.textContent = " · " + fresh + " new since your last visit";
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
    $("#r-min").textContent = s.m + " min read";
    $("#r-agency").textContent = s.ag;
    $("#r-link").href = s.u;
    $("#r-page").href = s.p;
    $("#r-copy").textContent = "Copy link";
    body.replaceChildren(document.getElementById("b" + i).content.cloneNode(true));
    $$("a[href]", body).forEach(function (a) {
      if (a.getAttribute("href").charAt(0) !== "#") { a.target = "_blank"; a.rel = "noopener"; }
    });
    var at = order.indexOf(i);
    $("#r-pos").textContent = (at + 1) + " of " + order.length;
    $("#r-prev").disabled = at <= 0;
    $("#r-next").disabled = at >= order.length - 1;
    tick();
    if (!dlg.open) { dlg.showModal(); document.documentElement.classList.add("reading"); }
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
    function done() { b.textContent = "Link copied"; }
    if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, function () { prompt("Copy this link", url); });
    else prompt("Copy this link", url);
  });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });
  dlg.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft") step(-1);
    if (e.key === "ArrowRight") step(1);
  });
  dlg.addEventListener("close", function () {
    document.documentElement.classList.remove("reading");
    body.replaceChildren();
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
})();
"""


def page_path(s):
    return f"story/{s['id']}/"


def time_tag(iso):
    """<time> that the page script turns into '3 h ago'; without JS it reads as a date."""
    return f'<time datetime="{esc(iso)}" data-rel>{esc(fmt_date(iso))}</time>'


def kicker(s):
    label = f' · <span class="label">{esc(s["label"])}</span>' if s["label"] else ""
    return f'<p class="kicker"><span title="{esc(s["agency"])}">{esc(short_agency(s["agency"]))}</span>{label}</p>'


def avatar(url):
    return (f'<img class="av" src="{esc(url)}" alt="" width="18" height="18" loading="lazy" '
            f'referrerpolicy="no-referrer">' if url else "")


def meta(s, minutes=True):
    read = f'<span>· {s["minutes"]} min read</span>' if minutes else ""
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
            f'{dek(s)}{meta(s)}<a class="btn" href="{esc(page_path(s))}" data-i="0">Read the full story</a></article>')


def side_story(s, i):
    cls = "side story has-thumb" if s["image"] else "side story"
    return f'<article class="{cls}" data-i="{i}">{thumb(s)}{kicker(s)}{headline(s, i)}{meta(s, False)}</article>'


def card(s, i):
    cls = "card story" + (" has-thumb" if s["image"] else "") + (" dup" if i < FRONT else "")
    return f'<article class="{cls}" data-i="{i}">{thumb(s)}{kicker(s)}{headline(s, i)}{dek(s)}{meta(s)}</article>'


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word[:-1] + 'ies' if word.endswith('y') else word + 's'}"


def story_image(s):
    im = s["image"]
    return (im["src"], im["w"], im["h"], "") if im else SHARE_CARD


def head(title, card_title, description, url, image, base, extra=""):
    """Fonts, icons, the social card (Open Graph, X) and oEmbed discovery for one page."""
    src, w, h, alt = image
    return (
        f"<head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(title)}</title>"
        f"<meta name='description' content='{esc(description)}'>"
        f"<link rel='canonical' href='{esc(url)}'>"
        f"<link rel='alternate' type='application/rss+xml' title='Eurth News Network' href='{base}news.rss'>"
        f"<link rel='alternate' type='application/json+oembed' href='{esc(url)}oembed.json' title='{esc(card_title)}'>"
        f"<link rel='icon' href='{base}static/favicon.svg' type='image/svg+xml'>"
        f"<link rel='apple-touch-icon' href='{base}static/apple-touch-icon.png'>"
        f"<meta name='theme-color' content='#2698d4' media='(prefers-color-scheme: light)'>"
        f"<meta name='theme-color' content='#002b36' media='(prefers-color-scheme: dark)'>"
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
        f"{extra}"
        f"<link rel='preconnect' href='https://fonts.googleapis.com'>"
        f"<link rel='preconnect' href='https://fonts.gstatic.com' crossorigin>"
        f"<link rel='stylesheet' href='{FONTS}'>"
        f"<script>document.documentElement.className+=' js'</script>"
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


def topbar(now, base=""):
    return (f"<div class='topbar'><span><a href='{SITE}'><img src='{base}static/eurth-yurt-circle.svg' alt='eurth.org' "
            f"width='24' height='24'></a>{now:%A} {now.day} {now:%b %Y}</span>"
            f"<span>Updated <time datetime='{now.isoformat(timespec='seconds')}' data-rel>{now:%H:%M} UTC</time>"
            f" · <a href='{base}news.rss'>RSS</a></span></div>")


def nav():
    links = "".join(f"<a class='chip' style='--chip:var(--{tok})' href='{SITE}/c/{path}'>{esc(name)}</a>"
                    for name, path, tok in SECTIONS)
    return f"<nav class='nav-strip' aria-label='Categories on eurth.org'>{links}</nav>"


def footer(base=""):
    return (f"<footer class='sitefoot'><p class='title'>Eurth News Network</p>"
            f"<p>The newest stories from The Newsroom on eurth.org. Everything here is fiction, written by the members of "
            f"Eurth, the Worldbuilding &amp; Roleplay Writing Community; each story appears as its agency published it.</p>"
            f"<p><a href='{base}news.rss'>RSS</a> · <a href='{SITE}/c/affairs/the-newsroom/36'>The Newsroom</a>"
            f" · <a href='{SITE}'>eurth.org</a> · <a href='{SITE}/tos'>Terms</a></p></footer>")


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
        front = (f'<section class="front" aria-label="Top stories">{lead_story(items[0])}'
                 f'<div class="latest"><h2 class="col-h">Also new</h2>'
                 f'{"".join(side_story(items[i], i) for i in range(1, min(FRONT, len(items))))}</div></section>')

    ranked = sorted(range(len(items)), key=lambda i: -items[i]["readers"])[:5]
    most_read = "".join(
        f'<li><span class="num">{n}</span><div><a href="{esc(page_path(items[i]))}" data-i="{i}">'
        f'{esc(items[i]["headline"])}</a><span class="sub">{esc(short_agency(items[i]["agency"]))} · '
        f'{plural(items[i]["readers"], "reader")}</span></div></li>'
        for n, i in enumerate(ranked, 1) if items[i]["readers"]
    )
    chips = "".join(
        f'<li><button type="button" data-nation="{esc(n)}" aria-pressed="false">{avatar(av)}'
        f'{esc(n)} <span class="n">{c}</span></button></li>'
        for n, (av, c) in sorted(nations.items(), key=lambda kv: kv[0].lower())
    )
    rail = ""
    if most_read:
        rail += f'<section><h2 class="col-h">Most read</h2><ol class="mostread">{most_read}</ol></section>'
    if chips:
        rail += (f'<section class="js-only"><h2 class="col-h">Nations in this edition</h2>'
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
        f"<div class='paper'>{topbar(now)}"
        f"  <header class='masthead'><h1 class='title'>Eurth News Network</h1>"
        f"    <p class='tagline'>Yesterday's News Today</p></header>"
        f"  {nav()}"
        f"  <div class='toolbar'>"
        f"    <p class='edition'><strong>{plural(len(items), 'story')}</strong> from {plural(len(agencies), 'agency')}"
        f"      in {plural(len(nations), 'nation')}<span class='new-count' hidden></span></p>"
        f"    <label class='search js-only'><span class='sr'>Search stories</span>"
        f"      <input id='q' type='search' placeholder='Search headlines, agencies, nations' autocomplete='off'>"
        f"      <kbd>/</kbd></label>"
        f"  </div>"
        f"  <main id='main'>"
        f"    <p class='filter-note' hidden><span class='filter-text' role='status'></span>"
        f"      <button type='button' class='btn clear-filters'>Clear</button></p>"
        f"    {front}"
        f"    <div class='body-grid'>"
        f"      <div class='feed'>{feed}"
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
        f"    <button type='button' class='btn' id='r-prev' aria-label='Newer story'>&larr; Newer</button>"
        f"    <button type='button' class='btn' id='r-next' aria-label='Older story'>Older &rarr;</button>"
        f"  </div>"
        f"  <article class='r-article'>"
        f"    <p class='kicker' id='r-kicker'></p>"
        f"    <h2 class='r-title' id='r-title'></h2>"
        f"    <p class='meta r-meta'><img class='av' id='r-av' alt='' width='18' height='18' referrerpolicy='no-referrer'>"
        f"<span class='nation' id='r-nation'></span><span>· <time id='r-time' data-rel></time></span>"
        f"<span>· <span id='r-min'></span></span></p>"
        f"    <p class='r-source'>As published by <span id='r-agency'></span></p>"
        f"    <div class='prose' id='r-body'></div>"
        f"    <div class='r-foot'><a class='cta' id='r-link' href='{SITE}' target='_blank' rel='noopener'>"
        f"Read and discuss on Eurth</a><a class='btn' id='r-page' href='./'>Story page</a>"
        f"<button type='button' class='btn' id='r-copy'>Copy link</button></div>"
        f"  </article>"
        f"</div></dialog>"
        f"<script type='application/json' id='stories-data'>{data_json}</script>"
        f"{bodies}"
        f"<script>{SCRIPT}</script>"
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
        pager += (f"<a class='newer' href='{base}{page_path(items[i - 1])}'><span class='k'>&larr; Newer</span>"
                  f"<span class='t'>{esc(items[i - 1]['headline'])}</span></a>")
    if i < len(items) - 1:
        pager += (f"<a class='older' href='{base}{page_path(items[i + 1])}'><span class='k'>Older &rarr;</span>"
                  f"<span class='t'>{esc(items[i + 1]['headline'])}</span></a>")

    return (
        f"<!doctype html><html lang='en'>"
        + head(f"{title} · Eurth News Network", s["headline"], description, url, story_image(s), base, extra)
        + f"<body><a class='skip' href='#story'>Skip to story</a>"
        f"<div class='paper'>{topbar(now, base)}"
        f"  <header class='masthead slim'><a class='title' href='{base}'>Eurth News Network</a></header>"
        f"  {nav()}"
        f"  <main id='story' class='story-page'>"
        f"    <article class='r-article'>{kicker(s)}<h1 class='r-title'>{esc(s['headline'])}</h1>"
        f"      <p class='meta r-meta'>{avatar(s['avatar'])}<span class='nation'>{esc(s['nation'])}</span>"
        f"<span>· {time_tag(s['date'])}</span><span>· {s['minutes']} min read</span></p>"
        f"      <p class='r-source'>As published by {esc(s['agency'])}</p>"
        f"      <div class='prose'>{s['cooked']}</div>"
        f"      <div class='r-foot'><a class='cta' href='{esc(s['url'])}'>Read and discuss on Eurth</a>"
        f"<a class='btn' href='{base}'>All stories</a></div>"
        f"    </article>"
        f"    {comments(s) if EMBED_COMMENTS else ''}"
        f"    <nav class='pager' aria-label='More stories'>{pager}</nav>"
        f"  </main>"
        f"  {footer(base)}"
        f"</div></body></html>"
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
    print(f"Updated {len(items)} stories -> {OUTDIR}/")


if __name__ == "__main__":
    main()
