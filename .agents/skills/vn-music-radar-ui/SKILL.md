---
name: vn-music-radar-ui
description: Use when designing, implementing, or reviewing the VN Music Radar interface in this repository, including its magazine pages and research tools.
---

# VN Music Radar UI

Read `PRODUCT.md` and `DESIGN.md` before modifying a screen. The frontend is in `app/web`; API data is in `app/api` and Neo4j. The magazine leads with recent artist documents, activity, data-derived digest and charts. Research routes for watch, explain, ask, network and entity details remain available.

Use the editorial tokens in `app/web/src/magazine.css`, Be Vietnam Pro, and the persisted system/light/dark theme. At desktop use horizontal navigation; at tablet and phone fold it into a menu. Keep the first article and its date visible early on a phone. Reuse existing data and graph components where appropriate.

The magazine scope is the nine selected shows in `app/api/magazine.py`. Only `CONTESTANT_ON` links qualify for the candidate roster; pending links must be labelled pending rather than presented as verified. Deduplicate artists by entity ID and documents by document ID. Show publication, collection, review and analysis timestamps separately. A recent document is not proof of a newly occurring event. Mention counts are not popularity, and relation-derived activity groups may overlap. Never invent an image or a summary. An image needs a source URL, credit and approved license value; otherwise use typography.

Every article, chart value and ranking must lead to source evidence or the contributing document list. Preserve existing API endpoints, the frozen research snapshot, review gates and the separate scheduler. A browser refresh only reads prepared data. Include loading, empty, error, keyboard, phone and theme behavior in UI checks. Run the frontend build and lint, and inspect real data at 1440, 768 and 390 CSS pixels.
