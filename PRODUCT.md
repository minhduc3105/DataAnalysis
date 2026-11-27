# VN Music Radar

VN Music Radar is a Vietnamese-language music magazine grounded in collected documents and a knowledge graph. It follows recent activity of artists from nine selected television-show seasons, while letting readers trace each item to its source and researchers inspect the underlying evidence.

## Scope and information model

The graph covers artists and groups, songs and albums, companies, shows, events, and brands. Documents come from journalism, YouTube, Spotify, and other collected sources. “Tài liệu” is the general term; a Spotify release or YouTube video is not a newspaper article.

The application keeps two data lanes distinct:

- The research lane is a frozen, versioned snapshot used for network structure, PageRank, communities, and k-core analysis.
- The live lane holds newer collected documents, their review status, and approved relations. Updating it must not rewrite the research snapshot.

An extraction candidate is not a confirmed relation. Only reviewed, approved relations enter the graph. Every asserted connection should retain a relation type, quotation, and source URL. Publication, first collection, human review, and analysis generation are different timestamps.

## Main workflows

The home route leads with the latest published documents in the collected dataset, then artist activity, a data-derived digest, and charts. Readers can filter by show and 7/30/90-day period, open article details and artist pages, and follow chart values back to the underlying documents. Counts are deduplicated by stable document or entity ID. A latest item in the dataset is not necessarily a current event.

The magazine scope is the main contestants linked to Anh Trai Say Hi seasons 1–2, Tinh Hà Say Hi season 1, Anh Trai Vượt Ngàn Chông Gai 2024 and 2026, Tân Binh Toàn Năng season 1, Chị Đẹp Đạp Gió Rẽ Sóng season 1, Chị Đẹp Đạp Gió season 2, and Em Xinh Say Hi season 1. It follows their activity outside the shows as well. Existing `CONTESTANT_ON` links remain pending review in the current graph; the magazine labels this limitation and never presents those memberships as confirmed.

Researchers can follow entities and source-linked alerts, compare trends, inspect why two entities are connected, ask a cited question, and open graph entity profiles. The network screen keeps its analysis snapshot selector and structural metrics.

Topics can be derived from approved relation types or classified from document text. The classifier records its model version, content hash, processing status, and a literal source quotation. Sentiment labels describe the source text, not audience opinion. Missing model output stays unavailable; it is never filled with neutral labels.

## Interpretation rules

PageRank, communities, and k-core describe network structure. They do not measure popularity, streaming, or market share. Mention counts describe only the sources and periods collected by this project. Missing collection coverage is not a zero-article day. A newly recorded relation is not proof that the described event just happened.

Spotify API use is budgeted; this project does not provide streaming counts. Live refresh in the interface reads prepared data and update status only. The scheduler runs separately, preserves pending review, and does not initiate from a browser tab.

## Implementation

The React, TypeScript, and Vite interface is in `app/web`; FastAPI routes are in `app/api/main.py`; collection and analysis tasks are in `crawler`. Neo4j stores reviewed graph data. Snapshot tables are generated under `data/interim/analysis` and its versioned `snapshots` directory. Operational instructions and service setup are in [HUONG_DAN_CHAY_DUC.md](HUONG_DAN_CHAY_DUC.md).
