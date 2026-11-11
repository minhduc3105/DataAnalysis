import tempfile
import unittest
import csv
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from crawler import web, web_signals


class WebTests(unittest.TestCase):
    def test_article_scope(self):
        for url in ('file:///tmp/a', 'https://vi.wikipedia.org/wiki/Test',
                    'https://www.wikidata.org/wiki/Q1', 'https://vnexpress.net/',
                    'https://example.com/image.jpg'):
            self.assertFalse(web._is_article_url(url), url)
        self.assertTrue(web._is_article_url('https://znews.vn/article-post123456.html'))

    def test_source_domain_boundary(self):
        sources = [{'site_url': 'https://saostar.vn', 'source_name': 'SaoStar', 'source_type': 'báo điện tử'}]
        with patch.object(web, '_sources', return_value=sources):
            self.assertEqual(web._source_for_url('https://www.saostar.vn/a')['source_name'], 'SaoStar')
            self.assertEqual(web._source_for_url('https://fakesaostar.vn/a')['source_type'], 'website chưa xác minh')

    def test_publication_date_not_modified_date(self):
        html = '<script type="application/ld+json">{"datePublished":"2026-10-30","dateModified":"2026-11-02"}</script>'
        self.assertEqual(web._page_publication_dates(html)[2], '2026-10-30')
        self.assertEqual(web._page_publication_dates(html.replace('datePublished', 'dateModified'))[2], '')
        conflict = html + '<meta property="article:published_time" content="2026-10-29">'
        self.assertTrue(web._page_publication_dates(conflict)[3])
        self.assertEqual(web._page_publication_dates(conflict)[2], '')

    def test_plan_relation_directions(self):
        pair = web_signals._relation_pair
        self.assertEqual(pair('AMBASSADOR_OF', 'B', 'Brand', 'P', 'Person'), ('P', 'B'))
        self.assertEqual(pair('DISPUTED_WITH', 'C1', 'Company', 'C2', 'Company'), ('C1', 'C2'))
        self.assertEqual(pair('DISPUTED_WITH', 'P', 'Person', 'S', 'Show'), ('', ''))
        self.assertEqual(pair('COLLABORATED_WITH', 'P', 'Person', 'C', 'Company'), ('', ''))

    def test_missing_graph_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(web_signals, 'INTERIM_DIR', Path(tmp)), patch.object(web_signals, '_write') as write:
            self.assertTrue(web_signals.build(write=False).empty)
            write.assert_not_called()

    def test_signal_evidence_and_review_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'graph').mkdir()
            pd.DataFrame([
                {'entity_id': 'P1', 'entity_type': 'Person', 'canonical_name': 'Minh Anh'},
                {'entity_id': 'P2', 'entity_type': 'Person', 'canonical_name': 'Thanh Nam'},
                {'entity_id': 'B1', 'entity_type': 'Brand', 'canonical_name': 'Nhãn Việt'},
                {'entity_id': 'C1', 'entity_type': 'Company', 'canonical_name': 'Công Ty Một'},
                {'entity_id': 'C2', 'entity_type': 'Company', 'canonical_name': 'Công Ty Hai'},
            ]).to_csv(root / 'graph/entities.csv', index=False)
            def doc(i, content, **extra):
                return dict(document_id=str(i), title='', content=content, content_hash=str(i),
                            url=f'https://example.com/article/{i}', published_at='2026-10-20',
                            published_at_source='json-ld:datePublished', published_at_conflict='',
                            collected_at='2026-11-09', document_status='cần kiểm tra', **extra)
            docs = [
                doc(1, 'Minh Anh là đại sứ thương hiệu Nhãn Việt.'),
                doc(2, 'Tin đồn Minh Anh khởi kiện Thanh Nam.'),
                doc(3, 'Minh Anh và Thanh Nam mâu thuẫn.'),
                doc(4, 'Công Ty Một khởi kiện Công Ty Hai.'),
                doc(5, 'Minh Anh và Thanh Nam xuất hiện trong chương trình.'),
                doc(6, 'Minh Anh hợp tác với Thanh Nam trong MV mới.'),
                doc(7, 'Minh Anh khởi kiện Thanh Nam.'),
                doc(8, 'Minh Anh tố cáo Thanh Nam.'),
            ]
            duplicate_link = doc(9, docs[5]['content'])
            duplicate_link['content_hash'] = docs[5]['content_hash']
            duplicate_link['url'] = 'https://example.com/article/6?ref=second-link'
            docs.append(duplicate_link)
            docs[6]['document_status'] = 'loại bỏ'
            docs[7]['published_at'] = '2026-11-01'
            out = root / 'signals.csv'
            with patch.object(web_signals, 'INTERIM_DIR', root), patch.object(web_signals, 'OUT_PATH', out), patch.object(web, '_read_docs', return_value=docs):
                result = web_signals.build(write=False).set_index('document_id')
                self.assertEqual(set(result.index), {'1', '2', '3', '4', '6', '9'})
                self.assertEqual(result.loc['1', 'entity_a_id'], 'P1')
                self.assertEqual(result.loc['1', 'entity_b_id'], 'B1')
                for i in ('2', '3'):
                    self.assertEqual(result.loc[i, 'review_status'], 'cần kiểm tra')
                    self.assertNotEqual(result.loc[i, 'query_status'], 'chờ query')
                self.assertIn('đang tranh chấp', result.loc['4', 'role_detail'])
                self.assertEqual(result.loc['6', 'quote'], docs[5]['content'])
                self.assertEqual(result.loc['9', 'quote'], docs[5]['content'])
                self.assertNotEqual(result.loc['6', 'url'], result.loc['9', 'url'])
                self.assertFalse(out.exists())
                web_signals.build()
                reviewed = pd.read_csv(out, keep_default_na=False)
                reviewed.loc[reviewed.document_id == 6, 'review_status'] = 'đã duyệt'
                reviewed.to_csv(out, index=False)
                docs[5]['content_hash'] = 'changed'
                again = web_signals.build(write=False).set_index('document_id')
                self.assertEqual(again.loc['6', 'review_status'], 'cần kiểm tra lại')

    def test_manual_queue_is_idempotent_and_preserves_provenance(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(web, 'WEB_DIR', Path(tmp)), patch.object(web, 'DB_PATH', Path(tmp) / 'crawl.sqlite3'), patch.object(web, '_entities', return_value=[{'entity_id': 'P1'}]):
            url = 'https://example.com/announcement'
            web.add_urls([url], ['P1'])
            web.add_urls([url], ['P1'])
            db = web._db()
            try:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM urls').fetchone()[0], 1)
                self.assertEqual(db.execute('SELECT source_kind,subject_ids FROM url_provenance').fetchone(), ('manual article URL', 'P1'))
            finally:
                db.close()
            with self.assertRaises(ValueError):
                web.add_urls([url], ['unknown'])

    def test_url_deduplication_uses_the_exact_source_string(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(web, 'WEB_DIR', Path(tmp)), patch.object(web, 'DB_PATH', Path(tmp) / 'crawl.sqlite3'):
            db = web._db()
            try:
                variants = [
                    'https://bao.vn/bai-a',
                    'https://bao.vn/bai-a/',
                    'https://bao.vn/bai-a?utm_source=google',
                    'https://bao.vn/bai-a#noi-dung',
                    'http://bao.vn/bai-a',
                    'https://bao.vn/Bai-A',
                    'https://bao.vn/bai-a?b=2&a=1',
                    'https://bao.vn/bai-a?a=1&b=2',
                ]
                outcomes = [web._add_url(db, url, 'Google News RSS', 'P1', 'Google News', f'q{i}') for i, url in enumerate(variants)]
                self.assertEqual(outcomes, ['inserted'] * len(variants))
                self.assertEqual(web._add_url(db, variants[0], 'RSS', 'P2', 'Báo', 'feed'), 'exact_duplicate')
                self.assertEqual(db.execute('SELECT COUNT(*) FROM urls').fetchone()[0], len(variants))
                self.assertEqual(db.execute('SELECT COUNT(*) FROM url_provenance WHERE url=?', (variants[0],)).fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT subject_ids FROM urls WHERE url=?', (variants[0],)).fetchone()[0], 'P1,P2')
            finally:
                db.close()

    def test_google_news_rss_url_is_queued_and_invalid_inputs_are_recorded(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(web, 'WEB_DIR', Path(tmp)), patch.object(web, 'DB_PATH', Path(tmp) / 'crawl.sqlite3'):
            db = web._db()
            try:
                google_url = 'https://news.google.com/rss/articles/CBMiExample?oc=5'
                self.assertEqual(web._add_url(db, google_url, 'Google News RSS', 'P1', 'Google News', 'query'), 'inserted')
                self.assertEqual(web._add_url(db, 'https://vi.wikipedia.org/wiki/Test', 'RSS'), 'inserted')
                self.assertEqual(web._add_url(db, 'file:///tmp/story', 'RSS'), 'inserted')
                self.assertEqual(web._add_url(db, None, 'RSS'), 'missing_url')
                rows = dict(db.execute('SELECT url,state FROM urls'))
                self.assertEqual(rows[google_url], 'discovered')
                self.assertEqual(rows['https://vi.wikipedia.org/wiki/Test'], 'out_of_scope')
                self.assertEqual(rows['file:///tmp/story'], 'invalid_url')
                self.assertEqual(db.execute("SELECT outcome FROM discovery_events WHERE url='' ").fetchone()[0], 'missing_url')
            finally:
                db.close()

    def test_rss_date_outside_period_is_kept_with_its_hint(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(web, 'WEB_DIR', Path(tmp)), patch.object(web, 'DB_PATH', Path(tmp) / 'crawl.sqlite3'):
            db = web._db()
            try:
                url = 'https://example.com/story?edition=print'
                outcome = web._add_url(db, url, 'RSS', query='feed', published_at='2015-12-31', period_status='out_of_period')
                self.assertEqual(outcome, 'inserted')
                self.assertEqual(db.execute('SELECT state FROM urls WHERE url=?', (url,)).fetchone()[0], 'discovered')
                self.assertEqual(db.execute('SELECT period_status FROM discovery_events WHERE url=?', (url,)).fetchone()[0], 'out_of_period')
            finally:
                db.close()

    def test_google_news_host_check_is_exact(self):
        deceptive = 'https://news.google.com.attacker.example/rss/articles/id'
        with patch.object(web.requests, 'get') as get:
            self.assertEqual(web._resolve_news_url(deceptive), deceptive)
            get.assert_not_called()

    def test_google_news_intermediate_is_not_counted_as_article_when_unresolved(self):
        class Response:
            url = 'https://news.google.com/rss/articles/example?oc=5'
            text = ('<html><head><meta property="og:title" content="Tiêu đề bài báo">'
                    '<meta name="author" content="Tác giả thử nghiệm">'
                    '<meta property="og:description" content="Mô tả ngắn của bài báo."></head></html>')

        with patch.object(web, '_google_news_response', return_value=('', Response())):
            result = web._fetch_crawl_item(
                Response.url, '', 'PER_0001', 'Google News', 'Google News RSS', True,
                'RSS description must stay only as a hint', [], {}, [],
            )
        self.assertEqual(result['kind'], 'error')
        self.assertEqual(result['step'], 'resolve_http')
        self.assertIn('Chromium', result['error'])

    def test_article_extraction_uses_publisher_fields_and_separates_rss(self):
        html = '''<html><head><meta property="og:title" content="Tên báo - bài viết">
        <script type="application/ld+json">{"@type":"NewsArticle","headline":"Tiêu đề thật","datePublished":"2020-05-03T10:30:00+07:00","dateModified":"2020-05-04T10:30:00+07:00","description":"Sapo đã xác minh","author":{"name":"Tác giả"}}</script></head>
        <body><nav><p>Menu giả không được lấy.</p></nav><main><article><h1>H1 thật</h1><p class="sapo">Sapo trong bài.</p><p>Đoạn mở đầu thứ nhất của bài báo có nội dung đủ dài để nhận diện và kiểm tra được.</p><p>Đoạn thứ hai cũng thuộc nội dung bài.</p></article></main><aside><p>Bài liên quan giả.</p></aside></body></html>'''
        row = web._extract_article_html('https://example.com/news/story', html, ['P1'], [('P1', 'Nghệ sĩ', 'nghe si')])
        self.assertEqual(row['title'], 'Tiêu đề thật')
        self.assertEqual(row['title_source'], 'json-ld:headline')
        self.assertEqual(row['abstract'], 'Sapo đã xác minh')
        self.assertNotIn('Menu giả', row['article_lead'])
        self.assertNotIn('Bài liên quan giả', row['article_lead'])
        self.assertEqual(row['published'], '2020-05-03')
        self.assertEqual(row['published_iso'], '2020-05-03T10:30:00+07:00')

    def test_queue_filters_exact_entity_before_limit(self):
        rows = [
            ('u1', '', 'P2', '', '', 0, ''),
            ('u2', '', 'P1,P2', '', '', 0, ''),
            ('u3', '', 'P1', '', '', 0, ''),
        ]
        selected, total, deferred = web._filter_queue_rows(rows, ['P1'], 1)
        self.assertEqual([row[0] for row in selected], ['u2'])
        self.assertEqual((total, deferred), (2, 1))

    def test_unique_single_word_artist_alias_matches_headline_but_collision_does_not(self):
        entities = [
            {'entity_id': 'PER_0001', 'canonical_name': 'RHYDER', 'aliases': 'Quang Anh Rhyder'},
            {'entity_id': 'PER_0002', 'canonical_name': 'HIEUTHUHAI', 'aliases': 'HIEUTHUHAI'},
        ]
        terms = web._relevance_terms(entities)
        self.assertIn('PER_0001', web._relevance_matches('RHYDER ra mắt MV mới', 'RHYDER ra mắt MV mới', terms))
        collided = entities + [{'entity_id': 'PER_0003', 'canonical_name': 'Rhyder', 'aliases': ''}]
        collided_terms = web._relevance_terms(collided)
        self.assertNotIn('PER_0001', web._relevance_matches('RHYDER ra mắt MV mới', 'RHYDER ra mắt MV mới', collided_terms))

    def test_google_news_rss_metadata_text_is_readable(self):
        xml = b'''<rss><channel><item><title>Title &amp; source</title>
        <description><![CDATA[<p>Opening <b>summary</b>.</p>]]></description>
        <source>Publisher</source><link>https://news.google.com/rss/articles/id</link>
        <pubDate>Wed, 10 Jun 2020 12:00:00 GMT</pubDate></item></channel></rss>'''

        class Response:
            content = xml
            def raise_for_status(self):
                return None

        with patch.object(web, '_polite_get', return_value=Response()):
            item = next(web._xml_items('https://news.google.com/rss/search?q=test', include_metadata=True))
        self.assertEqual(item[2], 'Title & source')
        self.assertEqual(item[3], 'Opening summary.')
        self.assertEqual(item[4], 'Publisher')
        self.assertEqual(web._date(item[1]), '2020-06-10')

    def test_query_plan_uses_one_full_period_query_per_entity(self):
        entities = [
            {'entity_id': 'P1', 'entity_type': 'Person', 'canonical_name': 'Ca sĩ Một', 'aliases': ''},
            {'entity_id': 'P2', 'entity_type': 'Group', 'canonical_name': 'Nhóm Hai', 'aliases': ''},
        ]
        with patch.object(web, '_entities', return_value=entities):
            jobs = web._query_jobs(date_from='2016-01-01', date_to='2026-10-21')
        self.assertEqual([entity_id for entity_id, _ in jobs], ['P1', 'P2'])
        for _, query in jobs:
            self.assertIn('after:2015-12-31', query)
            self.assertIn('before:2026-10-22', query)

    def test_document_batches_append_without_rewriting_prior_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'web_raw_documents.csv'
            with patch.object(web, 'INTERIM_DIR', Path(tmp)), patch.object(web, 'DOCS_PATH', path):
                web._save_docs([{'document_id': 'D1', 'url': 'https://example.com/1'}])
                web._save_docs([{'document_id': 'D2', 'url': 'https://example.com/2'}])
                with path.open(encoding='utf-8-sig', newline='') as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual([row['document_id'] for row in rows], ['D1', 'D2'])


if __name__ == '__main__':
    unittest.main()
