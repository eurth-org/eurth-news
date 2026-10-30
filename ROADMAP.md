# Roadmap

Eurth News Network is the front page of The Newsroom on eurth.org: the newest stories from Eurth's national news agencies, presented side by side at [news.eurth.org](https://news.eurth.org/). This file records how it was built and polished, request by request, so the next Eurth site can start where this one ended.

## What sets it apart

1. **Every agency on equal terms.** Each nation formats its posts its own way (banners, mock menus, tickers, datelines). The site reads every post for its real headline, standfirst, photo and reading time, and shows them all alike; the original post is kept, word for word, for reading.
2. **A real front page.** Lead story, "Also new", a grid in reading order, Most read, a nation filter and full-text search, with a reader that opens stories in place.
3. **Eurth's look.** Built from the Eurth design system: Libre Baskerville, Helvetica, JetBrains Mono, the turning globe, Font Awesome, the forum's light and Solarized night themes, and Orioni mode's newsprint.
4. **Accessible to WCAG 2.2 AAA**, checked with axe-core in every look, with one named brand exception.
5. **Made to be shared.** Every story has its own page, social card and oEmbed response, plus an RSS feed.

## Phases

| Phase | What | Status |
| --- | --- | --- |
| **0. Feed** | A paper-style page and RSS feed of the 25 newest Newsroom stories, rebuilt by GitHub Actions | Done (Sep 2026) |
| **1. Front page** | Headlines read from each post, lead story, grid, Most read, nation filter, search, reader, story pages | Done (#1) |
| **2. Eurth design system** | Tokens, type, globe, icons, light and night, Orioni mode | Done (#1–#6) |
| **3. Accessibility** | WCAG 2.2 AAA in every look and state, tested with axe-core | Done (#3); two named exceptions since #6 and #7 |
| **4. Sharing** | Open Graph and X cards, oEmbed, a share card, RSS with real headlines | Done (#1) |
| **5. Rights** | All rights reserved, text-and-data-mining reservation, disclaimer for members' borrowed images | Done (#4, #5) |
| **6. Discussion** | Discourse comments under each story page | Built, switched off: waits for Admin › Embedding on eurth.org |

## Updates

Times in CET.

| Update | When | Added |
| --- | --- | --- |
| #0 Feed (`d4f10a9`…`5430ae4`) | 28–29 Sep 2026 | The original paper-style page and RSS feed, GitHub Actions and Pages |
| #1 Redesign (`4cc5d23`) | 29 Oct 2026, 10:19 | Brief B1–B4: headlines read from each post, the front page, reader, story pages, social cards, oEmbed, the Eurth design system, comments switch |
| #2 Feedback round 1 (`544047f`) | 29 Oct 2026, 11:07 | 1.1–1.5: globe, local clock, sticky section bar with search and a phone menu, card hover |
| #3 Feedback round 2 (`8da9f91`) | 29 Oct 2026, 11:33 | 2.1–2.5.1: WCAG 2.2 AAA, light/dark switch, arrival animations, Orioni mode |
| #4 Feedback round 3 (`9ee3d51`) | 29 Oct 2026, 21:25 | 6–10: copyright, auto theme, seconds clock, search icon, footer links |
| #5 Feedback round 4 (`29701a5`) | 29 Oct 2026, 23:20 | 11: disclaimer for images members take from other websites |
| #6 Feedback round 5 (`9cee418`) | 29 Oct 2026, 23:52 | 12–22: line-md icons, Orioni switch in the header, Pause motion, placeholder images, icons, footer columns with periodicals, spinning favicon, smooth scrolling, this roadmap |
| #7 Feedback round 6 (`6d4eb2d`) | 30 Oct 2026, 02:13 | 20–21 (round 6): Pause motion taken out; the Orioni switch to the footer, an O-Mode button in the header |
| #8 Feedback round 7 | 30 Oct 2026 | 22–24 (round 7): O-Mode out of the header; Orioni mode a button in the footer that works as a switch; periodical covers uncropped, tilting on hover |

## What's in so far

The update that added each item is in brackets.

**Reading the stories**
- Headline, section label ("Breaking", "Politics"), standfirst, lead photo and reading time read from every post; menus, tickers, datelines, bylines and the agency's own banner are skipped; ALL-CAPS headlines calmed down (#1).
- Photos chosen by shape, not logos or banners, preferably from below the headline (#1).
- Agencies' own colours, backgrounds and justification give way to the theme; links open in the same tab (#1, #3).

**Front page**
- Top stories (the lead and "Also new"), More stories in reading order, Most read with reader meters, nations in this edition as a filter, full-text search (#1; meters #3; headings #6).
- A sticky section bar with search and a menu button on phones; the globe and title appear once the masthead scrolls away; links glide to their section (#2; globe #3; smooth scrolling #6).
- The reader: the story in place, newer and older, deep links, copy link, "New" and "Read" markers (#1; icons on every button #6).
- A lead story without a photo gets its topic's icon over one of Eurth's maps (#6).
- The edition line: stories, agencies, nations, when it was updated, the RSS feed (#1; moved from the top bar #6).

**Look**
- The Eurth design system: Libre Baskerville, Helvetica, JetBrains Mono, "Eurth News Network" in title case, the logo never on a story (#1).
- Three looks: the forum's white, Solarized night, and Orioni mode's newsprint (#3).
- The globe, always turning: top left, beside the sticky title, in the footer and as the favicon (#2; sprite #3; always #6; favicon #6).
- Font Awesome icons in the menu, section headings, buttons and footer (#6).
- The clock: local date and time, to the second, with separators blinking as on a Mac (#2; seconds #4).
- The footer: about the site, Eurth's other sites, The Eurth Weekly and Rhyme Magazine with their latest issues, the small print (#4; columns and periodicals #6).
- Periodical covers at their own proportions, leaning toward the pointer on hover (#8).

**Controls**
- The theme switch: auto, light, dark, with line-md's morphing sun and moon and a circular reveal from the button (#3; auto and flash fix #4; line-md loops #6).
- Orioni mode: a button beside the RSS feed in the footer that works as a switch, with a fountain pen that gives a flourish when it turns on; its tooltip explains it (#3; in the footer #7; a button #8).
- Tooltips that show on hover and focus, stay while pointed at, and go with Escape (#6).

**Accessibility**
- WCAG 2.2 AAA, tested with axe-core in all three looks, on the front page, in the reader and on story pages (#3; re-tested each update).
- 7:1 text contrast in every look and state; one named exception, white on Eurth blue for "Read and discuss on Eurth" (#3; exception #6).
- Nothing moves for reduced motion; without an on-page pause, WCAG 2.2.2 is a second named exception for everyone else (#7).
- 44 px targets, a 2px focus ring, the sticky bar never hiding the focused element, landmarks, breadcrumbs, link text that names its story, abbreviations expanded, 1.4.8 line length and spacing, reflow to 320px, works without JavaScript (#3).

**Sharing and rights**
- Story pages, Open Graph and X cards, a 1200 x 800 share card, oEmbed, RSS with headlines (#1).
- © Eurth, all rights reserved, with a text-and-data-mining reservation; stories © their authors; borrowed images disclaimed, with a takedown route (#4, #5).

## Feedback log

Every request, in the order it was made, and the update that did it.

| # | Asked for | Done |
| --- | --- | --- |
| B1 | Make the news overview a thousand times better, keeping the neutral design | Headlines, standfirsts and photos read from every post; every agency shown alike; a real front page, reader, story pages; old bugs fixed (`/t/None/` links, the cron, "Confict") (#1) |
| B2 | Discourse's embedded discussion | Built behind `EMBED_COMMENTS`; waits for eurth.org's Admin › Embedding (#1) |
| B3 | Social cards and oEmbed for news.eurth.org | Open Graph and X tags, a ShareCard, oEmbed JSON beside every page (#1) |
| B4 | Use the Eurth styleguide from Claude Design | Tokens, type, globe; title-case masthead; the logo kept off stories (#1) |
| 1.1 | The rotating Eurth globe top left | Done (#2) |
| 1.2 | Local time beside the date | Live local date and time (#2) |
| 1.3 | The menu of external links takes people away | Replaced by on-page sections; Eurth's links went to the footer (#2) |
| 1.4 | Sticky header, hamburger on phones | Sticky section bar with search; a Menu button on phones (#2) |
| 1.5 | A card-like hover in More stories | Raised background, a blue top rule, a slight photo zoom (#2) |
| 2.1 | The globe left of the title in the sticky header | Done (#3) |
| 2.2 | Card contrast; the most stringent accessibility | WCAG 2.2 AAA, tested with axe-core: 7:1 in every look and state, 44px targets and more (#3) |
| 2.3 | A light/dark switch like Deluminator, right of RSS | Done, with the circular reveal (#3) |
| 2.4 | Delightful CSS animations, like the Luddites artifact | Arrivals: the masthead rule, the lead, stories rising, meters filling; the Luddites gloss and foil left out, as the Eurth system has no glows (#3) |
| 2.5 | The FT's and De Tijd's paper | Parchment, the system's own long-read ground (#3) |
| 2.5.1 | Keep the original look; an "Orioni mode" for the paper | Done (#3) |
| 6 | Copyright the website and the repository | LICENSE: all rights reserved; footer, RSS, meta tag, text-and-data-mining reservation; stories © their authors; earlier versions stay MIT (#4) |
| 7 | Auto mode as on gov.eurth.org; stop the flash going dark | Auto, light, dark; the reveal holds its last frame (#4) |
| 8 | Seconds, and a colon that blinks as on a Mac | Done, with a way to stop it (#4; Pause motion #6) |
| 9 | A search icon | Font Awesome's magnifying glass (#4) |
| 10 | Footer links to the forums, map, Governmint and uptime | Done, with The Newsroom and the guidelines; "Terms" pointed at a 404 (#4) |
| 11 | We're not responsible for images members hotlink or copy | Footer disclaimer with a takedown route; LICENSE claims no rights in them (#5) |
| 12 | Animated line-md icons in the switch | The sun morphs into the moon and back; rays turn, stars twinkle (#6) |
| 13 | Orioni mode as an O-themed switch in the header, explained in a tooltip | An O that rolls along its track, beside the theme switch (#6); moved to the footer (#7) |
| 14 | The globe should always spin | Always turning; Pause motion stops it (WCAG 2.2.2) (#6); the pause went again (#7) |
| 15 | A placeholder for a lead story without a photo that suits any context, culture or place | The topic's icon over one of Eurth's own maps (#6) |
| 16 | Font Awesome icons in the menu and their sections, not cheap | One small, muted size; Eurth blue in the headings (#6) |
| 17 | A multi-column footer, with The Eurth Weekly and Rhyme Magazine | About, Eurth's sites, the periodicals with their latest issues (#6) |
| 18 | The spinning globe as favicon, as on gov.eurth.org | Done (#6) |
| 19 | Keep a record of all requests in ROADMAP.md | This file (#6) |
| 20 | Smooth scrolling instead of jumps | Done, off with Pause motion or reduced motion (#6) |
| 21 | Icons on the reader's buttons | Close, newer, older, discuss, story page, copy link (#6) |
| 22 | "Read and discuss on Eurth" in Eurth blue with white text | Done; the site's one named contrast exception (#6) |
| 20 (round 6) | Remove the pause button; nobody asked for it | Taken out, with its remembered setting; motion still stops for reduced motion, and WCAG 2.2.2 is now a named exception (#7) |
| 21 (round 6) | The Orioni switch into the footer's first column, under the RSS feed; a second button, "O-Mode", with Font Awesome's `pen-fancy` | The switch, with its name beside it, under the RSS feed; O-Mode in the header does the same, and the two stay in step (#7) |
| 22 (round 7) | O-Mode belongs in the footer: out of the header | Out of the header; it and the Orioni switch became one button in the footer (#8) |
| 23 (round 7) | Orioni mode as a button like "RSS feed" that works as a switch; its description in a tooltip | A button with the fountain pen, beside the RSS feed; `role="switch"`, filled in when on; the description in its tooltip (#8) |
| 24 (round 7) | Rhyme Magazine's cover is cropped: keep its full dimensions, and tilt it slightly on hover | Covers keep their own proportions (no more cropping to a fixed box); on hover they lift and lean toward the pointer in 3D, gentler on the wide Weekly banner, still for reduced motion. The tooltip moved inside the footer landmark, which axe asked for while it was open (#8) |

## Playbook for the next Eurth site

What this site settled, to reuse from the first day:

1. **Start from the Eurth design system** in Claude Design: its tokens, Libre Baskerville, Helvetica, JetBrains Mono, the globe sprite and Font Awesome. The site's frame is Eurth's (out of character); never brand in-character content.
2. **Light, night and auto from the start**, set before the page paints, with Deluminator's reveal and `fill: "forwards"` on its animation.
3. **AAA from the start.** Pick each theme's palette for 7:1 against both the page and the hover background, make every target 44px, and test with axe-core in every look and state, not just the default. Name any brand exception out loud.
4. **Respect reduced motion**: nothing moves for it. A Pause motion switch would meet WCAG 2.2.2 for everyone; it was tried in #6 and taken out in #7, as nobody had asked for it.
5. **Tooltips** that show on hover and focus, stay while pointed at, and go with Escape.
6. **Link previews**: Open Graph and X tags, a 1200 x 800 ShareCard, oEmbed JSON.
7. **The footer**: what the site is, Eurth's other sites, the periodicals, copyright and the third-party disclaimer.
8. **Rights**: "© Eurth. All rights reserved", a text-and-data-mining reservation (meta tag and `/.well-known/tdmrep.json`), members' work stays theirs.
9. **The turning globe** as favicon, Apple touch icon from the system.
10. **Check the live site** after every deploy.

## Ideas

Not planned yet, but worth keeping:

- Switch on the comments once eurth.org allows news.eurth.org under Admin › Embedding.
- An AAA version of the call to action: white on `eurth-blue-deep` (#1b6fa0) is 5.5:1.
- A quiet way to stop the turning globe and the seconds, to meet WCAG 2.2.2 for everyone again.
- Decide whether to keep loading images with `no-referrer`, which also gets around other websites' hotlink protection.
- Share cards drawn per story when there's no photo.
- An archive beyond the newest 25, and pages per agency and per nation.
- The GitHub repository's description still says "every 5 minutes".
