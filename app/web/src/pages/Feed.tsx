import { ArrowRight, ExternalLink, SlidersHorizontal, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { FeedItem, SearchHit } from '../api'
import { EntitySearch } from '../components/EntitySearch'
import { ErrorBox, Loading, PageHeader } from '../components/ui'
import { useAsync, useDebounced } from '../hooks'
import { RELATION_LABEL } from '../labels'

const platformLabel = (platform: string) => ({ youtube: 'YouTube', spotify: 'Spotify', web: 'Báo chí / web' })[platform.toLowerCase()] ?? (platform || 'Nguồn khác')
const dateLabel = (value: string) => /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10).split('-').reverse().join('/') : 'Chưa rõ ngày'

function EvidenceDocument({ item }: { item: FeedItem }) {
  const [expanded, setExpanded] = useState(false)
  const relations = expanded ? item.relations : item.relations.slice(0, 2)
  return <article className="evidence-document">
    <div className="document-meta"><span className="platform-label">{platformLabel(item.platform)}</span><span>{item.source || 'Chưa rõ nguồn'}</span><time>{dateLabel(item.published_at)}</time></div>
    <h2>{item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.title || item.document_id}<ExternalLink size={15} aria-label="Mở nguồn trong tab mới" /></a> : item.title || item.document_id}</h2>
    <ul className="evidence-list">{relations.map((r, index) => <li key={`${r.relation_id}-${index}`}><p className="relation-sentence"><strong>{r.source}</strong><span><ArrowRight size={13} aria-hidden="true" />{RELATION_LABEL[r.relation] ?? r.relation}</span><strong>{r.target}</strong></p><blockquote>{r.evidence ? `“${r.evidence}”` : 'Chưa có câu trích dẫn.'}</blockquote></li>)}</ul>
    {item.relations.length > 2 && <button className="text-action" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>{expanded ? 'Thu gọn quan hệ' : `Xem thêm ${item.relations.length - 2} quan hệ`}</button>}
  </article>
}

export function FeedPage() {
  const [source, setSource] = useState('')
  const sourceQuery = useDebounced(source)
  const [entity, setEntity] = useState<SearchHit | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [page, setPage] = useState<{ filterKey: string; offset: number }>({ filterKey: '', offset: 0 })
  const [filtersOpen, setFiltersOpen] = useState(false)
  const invalidDates = Boolean(from && to && from > to)
  const filterKey = [sourceQuery, from, to, entity?.id ?? ''].join('|')
  const offset = page.filterKey === filterKey ? page.offset : 0
  const state = useAsync(() => invalidDates ? Promise.resolve([]) : api.feed({ entity_id: entity?.id, source: sourceQuery || undefined, date_from: from || undefined, date_to: to || undefined, limit: 80, offset }), [sourceQuery, from, to, entity?.id, refresh, invalidDates, offset])
  const items = state.data ?? []
  const ready = !state.loading && !state.error && !invalidDates
  const filtered = Boolean(source || entity || from || to)
  const sources = Object.entries(items.reduce<Record<string, number>>((counts, item) => { const key = platformLabel(item.platform); counts[key] = (counts[key] ?? 0) + 1; return counts }, {})).sort((a, b) => b[1] - a[1])
  const clear = () => { setSource(''); setEntity(null); setFrom(''); setTo('') }

  return <div className="feed-page">
    <PageHeader title="Bảng tin âm nhạc" subtitle="Những kết nối trong âm nhạc Việt, đọc từ nguồn và bằng chứng."><Link to="/explain" className="secondary-action">Khám phá đường nối <ArrowRight size={15} /></Link></PageHeader>
    <section className="feed-toolbar" aria-label="Bộ lọc bảng tin">
      <div className="feed-toolbar-heading"><div className="inline-flex items-center gap-2"><SlidersHorizontal size={16} /><span>Lọc tài liệu</span>{filtered && <span className="filter-applied">Đang lọc</span>}</div><button className="filter-toggle text-action" aria-expanded={filtersOpen} aria-controls="feed-filters" onClick={() => setFiltersOpen(!filtersOpen)}>{filtersOpen ? 'Thu gọn' : 'Mở bộ lọc'}</button><button className="refresh-action" onClick={() => setRefresh((value) => value + 1)} disabled={state.loading} aria-label="Làm mới bảng tin"><RotateCcw size={15} /><span>Làm mới</span></button></div>
      <div id="feed-filters" className={`feed-filters ${filtersOpen ? 'is-open' : ''}`}>
        <label>Nguồn chứa tên<input value={source} onChange={(e) => setSource(e.target.value)} placeholder="Tên kênh hoặc tờ báo" /></label>
        <div className="entity-filter"><span className="field-label">Nghệ sĩ / thực thể</span><EntitySearch key={entity?.id ?? 'none'} initialValue={entity?.name ?? ''} onSelect={setEntity} placeholder="Tìm tên trong đồ thị…" />{entity && <button className="text-action" onClick={() => setEntity(null)}>Bỏ lọc {entity.name}</button>}</div>
        <label>Từ ngày<input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>Đến ngày<input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></label>
      </div>
      {invalidDates && <p role="alert" className="date-error">Ngày kết thúc phải bằng hoặc sau ngày bắt đầu.</p>}
    </section>
    <div className="feed-grid">
      <section className="feed-stream" aria-label="Tài liệu có bằng chứng" aria-busy={state.loading}>
        <div className="section-heading"><h2>Tài liệu có bằng chứng</h2><span aria-live="polite">{ready ? `${items.length === 80 ? 'Tối đa ' : ''}${items.length} tài liệu` : state.loading ? 'Đang tải…' : 'Chưa có kết quả'}</span></div>
        {state.loading ? <Loading label="Đang lấy tài liệu có bằng chứng…" /> : state.error ? <ErrorBox error={state.error} onRetry={() => setRefresh((value) => value + 1)} /> : invalidDates ? null : items.length ? items.map((item) => <EvidenceDocument key={item.document_id} item={item} />) : <div className="feed-empty"><h3>Chưa có tài liệu phù hợp</h3><p>{filtered ? 'Thử mở rộng khoảng ngày hoặc bỏ bớt bộ lọc.' : 'Tài liệu sẽ xuất hiện khi đồ thị có quan hệ được duyệt kèm bằng chứng.'}</p>{filtered && <button className="secondary-action" onClick={clear}>Xóa bộ lọc</button>}</div>}
        {ready && (items.length > 0 || offset > 0) && <nav className="feed-pagination" aria-label="Phân trang bảng tin"><button className="secondary-action" disabled={offset === 0} onClick={() => setPage({ filterKey, offset: Math.max(0, offset - 80) })}>Trang trước</button><span>Trang {Math.floor(offset / 80) + 1} · tối đa 80 tài liệu mỗi trang</span><button className="secondary-action" disabled={items.length < 80} onClick={() => setPage({ filterKey, offset: offset + 80 })}>Trang tiếp</button></nav>}
      </section>
      <aside className="feed-context" aria-label="Ngữ cảnh bảng tin">
        <section><h2>Nguồn trong kết quả</h2><p className="context-description">Phân bố của tập tài liệu đang xem.</p>{ready ? sources.length ? <ul className="source-breakdown">{sources.map(([label, count]) => <li key={label}><div><span>{label}</span><strong>{count}</strong></div><div className="source-track"><span style={{ width: `${count / items.length * 100}%` }} /></div></li>)}</ul> : <p className="context-description">Chưa có nguồn trong kết quả.</p> : <p className="context-description">{state.loading ? 'Đang tải nguồn…' : 'Chưa thể thống kê nguồn.'}</p>}</section>
        <section className="evidence-guide"><h2>Đọc một kết nối</h2><p>Ai kết nối với ai, qua quan hệ nào?</p><p>Câu trích dẫn nằm ngay dưới mỗi quan hệ. Mở tiêu đề tài liệu để đối chiếu với nguồn gốc.</p><Link to="/ask" className="text-action">Đặt câu hỏi có nguồn <ArrowRight size={14} /></Link></section>
        <Link to="/network" className="context-link"><span><strong>Nhìn rộng hơn</strong><small>Khám phá cộng đồng và vai trò cầu nối</small></span><ArrowRight size={18} /></Link>
      </aside>
    </div>
  </div>
}
