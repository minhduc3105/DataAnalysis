// Truy vấn mẫu cho Neo4j Browser (kịch bản demo Bước 13). Chạy sau `main.py neo4j load` và `main.py analyze`.

// 1. Một nghệ sĩ cùng tác phẩm, công ty, chương trình, cộng sự
MATCH (a:Entity {name: 'Hứa Kim Tuyền'})-[r]-(x:Entity)
RETURN a, r, x LIMIT 150;

// 2. Từ cạnh lần về nguồn: câu trích, URL, ngày đăng
MATCH (a:Entity {name: 'Hứa Kim Tuyền'})-[r]-(x:Entity)
MATCH (e:Evidence {relation_id: r.relation_id})-[:FROM_DOCUMENT]->(d:Document)
RETURN type(r) AS quan_he, x.name AS doi_tuong, e.quote AS trich_dan, e.extraction_method AS phuong_phap, d.url AS url, d.published_at AS ngay_dang
LIMIT 50;

// 3. Bài hát: ai trình bày, ai sáng tác/sản xuất, công ty nào phát hành
MATCH (s:Song)<-[r]-(p:Entity) WHERE s.name = 'Dữ Liệu Quý'
OPTIONAL MATCH (s)-[:RELEASED_BY]->(c:Company)
RETURN s, r, p, c;

// 4. Chuỗi hợp tác ngắn nhất giữa hai nghệ sĩ (Shortest Path)
MATCH p = shortestPath((a:Entity {name: 'Bùi Công Nam'})-[:COLLABORATED_WITH*..8]-(b:Entity {name: 'Karik'}))
RETURN p;

// 5. Top nghệ sĩ theo PageRank, kèm cộng đồng Louvain
MATCH (a:Entity) WHERE a.pagerank IS NOT NULL
RETURN a.name, a.community, round(a.pagerank, 3) AS pagerank, a.collab_degree AS cong_su, round(a.betweenness) AS betweenness
ORDER BY pagerank DESC LIMIT 20;

// 6. Vẽ một cộng đồng: thay số bằng community trong communities.csv
MATCH (a:Entity)-[r:COLLABORATED_WITH]-(b:Entity)
WHERE a.community = 0 AND b.community = 0
RETURN a, r, b;

// 7. Cầu nối: betweenness cao và nối nhiều cộng đồng
MATCH (a:Entity) WHERE a.betweenness IS NOT NULL
RETURN a.name, round(a.betweenness) AS betweenness, a.community
ORDER BY betweenness DESC LIMIT 20;

// 8. Công ty phát hành nhiều bài nhất (Song → Company)
MATCH (s:Song)-[:RELEASED_BY]->(c:Company)
RETURN c.name, count(DISTINCT s) AS so_bai ORDER BY so_bai DESC LIMIT 20;
