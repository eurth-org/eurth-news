"""Draws static/topic-<topic>-<shape>.jpg: the placeholder of a lead story without a photo (its topic's icon over
one of Eurth's maps, in the horizon disc) as images, for search engines and link previews of stories without a
photo of their own. Run it again after changing TOPICS, their icons or the maps. It needs Google Chrome (to draw
the page exactly as the site does) and Pillow (to save JPEGs); the site build itself needs neither.

    python3 tools/topic_images.py
"""
import os, subprocess, sys, tempfile
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import newsroom

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Per shape: the disc's diameter and how far it sits past the top and right edges, as on the page's
# placeholder; the icon and label scale with the image's width.
DISC = {"16x9": (780, -190, -100), "4x3": (900, -220, -120), "1x1": (1040, -280, -160)}


def page(name, ic, mp, shape):
    w, h = newsroom.TOPIC_SHAPES[shape]
    d, top, right = DISC[shape]
    vb, path = newsroom.FA[ic]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:#002b36}}
.ph{{position:relative;width:{w}px;height:{h}px;display:flex;flex-direction:column;justify-content:center;
  align-items:flex-start;gap:24px;padding-left:96px;box-sizing:border-box;color:#fcf6e1}}
.disc{{position:absolute;right:{right}px;top:{top}px;width:{d}px;height:{d}px;border-radius:50%;
  background:url("file://{REPO}/static/map-{mp}.jpg") center/cover no-repeat,#002b36;box-shadow:0 0 0 12px #2698d4}}
svg{{position:relative;width:150px;height:150px;fill:#fcf6e1}}
.k{{position:relative;font:700 34px/44px Helvetica,Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase}}
</style></head><body><div class="ph"><span class="disc"></span>
<svg viewBox="{vb}"><path d="{path}"/></svg><span class="k">{name}</span></div></body></html>"""


def main():
    topics = [(name, ic, mp) for name, ic, mp, _ in newsroom.TOPICS] + [("News", "newspaper", "satellite")]
    with tempfile.TemporaryDirectory() as tmp:
        for name, ic, mp in topics:
            for shape, (w, h) in newsroom.TOPIC_SHAPES.items():
                html, png = os.path.join(tmp, "p.html"), os.path.join(tmp, "p.png")
                with open(html, "w") as f:
                    f.write(page(name, ic, mp, shape))
                subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                "--force-device-scale-factor=1", f"--user-data-dir={tmp}/profile",
                                f"--window-size={w},{h}", f"--screenshot={png}", f"file://{html}"],
                               check=True, capture_output=True)
                im = Image.open(png).convert("RGB")
                assert im.size == (w, h), (name, shape, im.size)
                out = os.path.join(REPO, "static", f"topic-{name.lower()}-{shape}.jpg")
                im.save(out, quality=82, optimize=True, progressive=True)
                print(out.rsplit("/", 2)[-2] + "/" + os.path.basename(out), os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main()
