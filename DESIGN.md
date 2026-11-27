# VN Music Radar design system

## Art direction

VN Music Radar is an energetic Vietnamese music magazine that remains source-first. The opening screen names recent artist activity from the collected dataset; the editorial path then moves from stories to observed patterns and charts. Every article has a route back to its source and evidence. The magazine covers artists linked as main contestants to nine selected show seasons. Pending show memberships are explicitly labelled pending.

## Color and type

Light: paper `#f8f6f0`, near-black ink `#10131a`, coral `#e94234`, quiet rules. Dark: charcoal ground `#17191c`, pale ink, brighter coral `#ff7467`. The tokens live in `app/web/src/magazine.css` and extend the existing theme contract. Be Vietnam Pro carries both display and body text; tabular numerals make counts legible. The theme remains system/light/dark and persists locally.

## Composition

A compact utility bar and wordmark sit above horizontal navigation. The home route opens with a strong typographic headline, show filter, and the latest story. The main article receives the largest frame; secondary stories form a compact editorial rail. Artist activity follows, then a data-derived digest, then charts and tables. On narrow screens, the story and its title arrive before the deeper sections; navigation folds into a menu. The page uses typography, solid fields, rules, and a designed typographic media treatment when licensed imagery is unavailable.

## Data and media

Show membership comes from `CONTESTANT_ON` and is not silently upgraded from pending to verified. Counts refer to distinct document IDs in the selected date window. Daily charts follow publication dates; collection timestamps are labelled separately. The top-artist list counts documents, not popularity. Activity groups derive from relation types and can overlap, so group totals need not sum to the document total. Chart and ranking links open the documents they count.

A photograph is shown only when the document has an image URL, source URL, credit and approved license/permission value. Without those fields the article uses the typographic treatment. An article summary is optional and drawn from the stored document when available; otherwise an actual evidence quotation is displayed as a quote. No synthetic claim, placeholder portrait or fake current event is inserted.

## Interface behavior

The primary routes are home, feed, artists, trends, watch, explain, ask, network and graph entity profile. The feed filters by show, artist, source, publication date, period and activity. Every data view handles loading, empty and error states. Research tools retain their API behavior and use the shared palette. Use visible keyboard focus, labelled controls, high contrast, reduced motion, responsive navigation and no page-level horizontal overflow.

Review at 1440, 768 and 390 CSS pixels, in light and dark themes. Verify article-to-source links, chart-to-feed filters, show and artist deduplication, and the pending-roster notice against real API results.
