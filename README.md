# Eurth News Network

A rolling front page for **The Newsroom** on [Eurth](https://eurth.org): the 25 newest news stories (replies) posted in the category, presented side by side, plus an RSS feed. Rebuilt automatically every 2 hours.

Live page: https://news.eurth.org/
RSS feed:  https://news.eurth.org/news.rss

## How it works

- `newsroom.py` queries the Discourse search API for the newest 25 replies in the Newsroom category (`category:36 in:replies order:latest`) and fetches each post's full content, plus the latest issue of The Eurth Weekly and Rhyme Magazine for the footer.
- Every agency formats its posts differently (banners, mock menus, tickers, datelines), so the script reads each post and pulls out a real headline, section label, standfirst, lead photo and reading time. The page then shows every agency the same way; the original post is kept intact for reading.
- It renders into `_site/`:
  - `index.html`: the front page. Lead story, "Also new" column, a "More stories" grid in reading order, Most read, a nation filter and full-text search. A sticky section bar keeps search and the sections in reach (a menu button on phones); the top bar shows the reader's local date and time. Stories open in a reader with newer/older navigation, deep-linkable as `#story-<post id>`. "New" and "Read" markers since your last visit.
  - `story/<post id>/index.html`: one page per story, readable without JavaScript, with its own social card.
  - `oembed.json` next to every page, advertised with `<link rel="alternate" type="application/json+oembed">`, plus Open Graph and X card tags, so links unfurl on Discourse, Discord, Slack, Bluesky, Mastodon and X.
  - `news.rss`: an RSS 2.0 feed with real headlines and the full story content.
  - `static/`: copied from the repo (the globe as a 240-frame sprite strip and its first frame as favicon, Apple touch icon, share card, and three of Eurth's maps for stories without a photo).
- The GitHub Actions workflow (`.github/workflows/newsroom.yml`) runs the script every 2 hours, on every push to `main`, and on demand, and deploys `_site/` to GitHub Pages.

## Design

The page follows the **Eurth** design system (Claude Design): Libre Baskerville for headlines, Helvetica for labels and text, JetBrains Mono for dates, [Font Awesome](https://fontawesome.com) icons (the forum's set, CC BY 4.0) in the menu, section headings, buttons and footer, and the forum's globe, turning in the corner, beside the sticky title, in the footer and as the favicon (as on gov.eurth.org). The page frame is Eurth's own (out of character); the stories inside keep their agencies' words but not their banners or colours, and the Eurth logo never sits on a story. Navigation stays on the site and scrolls smoothly; links to eurth.org are in the reader, on story pages and in the footer. `static/share-card.jpg` is the system's 1200 x 800 ShareCard layout with the satellite map of Eurth.

A lead story without a photo gets a placeholder: the icon of its topic (conflict, diplomacy, politics, economy, health, science, culture or news, read from its headline and standfirst) over one of Eurth's own maps in the system's horizon disc. No people and no real places, so it suits whichever nation the story comes from.

The header carries two controls:

- **O-Mode** (Font Awesome's fountain pen) turns on Orioni mode: warm newsprint parchment instead of white, in the spirit of the FT and De Tijd. Light theme only. The footer has the same as a switch, an O that rolls along its track, under the RSS feed.
- **The theme switch**, after [Deluminator](https://github.com/stijn/deluminator) and [Governmint](https://gov.eurth.org/): auto follows the device, and each click moves on (from auto it flips the page, then keeps the device's look, then returns to auto). The mode is set before the page paints, and the new look grows out of the button in a circle (View Transitions). Its icons are [line-md](https://github.com/cyberalien/line-md)'s (MIT): the sun morphs into the moon and back, the rays turn and the stars twinkle.

Each control explains itself in a tooltip that appears on hover and keyboard focus, stays while pointed at, and goes with Escape.

Arrivals are small and play once: the masthead rule draws in, the lead settles, stories rise into place as they scroll in, Most read fills its meters, the clock runs to the second with its separators blinking as on a Mac. Nothing moves for visitors who ask for reduced motion.

The footer has three columns: about the site, Eurth's other sites (forums, map, Governmint, uptime, The Newsroom, guidelines), and Eurth's periodicals, The Eurth Weekly and Rhyme Magazine, each with its latest issue.

## Accessibility

Built and tested to **WCAG 2.2 AAA**, checked with axe-core (every A, AA, AAA and best-practice rule) in all three looks, on the front page, in the reader and on story pages:

- 7:1 contrast for all text in every look and state, including the card hover background; 3:1 for control borders and focus rings. One named exception, a brand decision: "Read and discuss on Eurth" is white on Eurth blue (3.2:1 at 19px bold, which the Eurth system and WCAG AA allow for large text, but not AAA's 4.5:1).
- 44 x 44 px minimum targets; a 2px focus ring; the sticky bar never covers the focused element.
- No new tabs; read and new stories are marked in text, not just colour; tooltips follow WCAG 1.4.13.
- A second known exception, by choice: the globes, the favicon, the theme icon and the clock's seconds keep moving with no pause on the page, so WCAG 2.2.2 is met only for visitors whose device asks for reduced motion (for them nothing moves).
- Article text at most ~70 characters wide, 1.6 line height, paragraph spacing 1.5 times the line height; agencies' own text colours and justification give way to the theme.
- Landmarks, a skip link, breadcrumbs on story pages, link text that names its story, abbreviations with their expansions.
- Works without JavaScript (stories link to their own pages) and reflows to 320px.

How the site got here, request by request, is in [ROADMAP.md](ROADMAP.md).

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

## Copyright

© 2026 Eurth. All rights reserved: no copying, republishing or text and data mining without written permission. The stories are © their authors, the members of Eurth who posted them on eurth.org. Images and other material that members take from other websites, linked or copied, belong to whoever holds their rights; Eurth doesn't own or check it and isn't responsible for it, and flagging the original post on eurth.org gets it taken down (it drops off this site at the next update). See [LICENSE](LICENSE). The site states the same in its footer, its RSS feed, a `copyright` meta tag, and a machine-readable text-and-data-mining reservation (`tdm-reservation` meta tag and `/.well-known/tdmrep.json`, the W3C TDMRep format).
