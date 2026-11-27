import { ArrowRight, ArrowUpRight, ExternalLink, RotateCcw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, type MagazineArticle, type MagazineBundle, type MagazineShow } from '../api'
import { EChart } from '../components/EChart'
import { ErrorBox, Loading } from '../components/ui'
import { useAsync, useDebounced } from '../hooks'
import { RELATION_LABEL } from '../labels'

const number = (value: number) => new Intl.NumberFormat('vi-VN').format(value)
const date = (value: string | null) => value && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10).split('-').reverse().join('/') : 'Chưa rõ ngày xuất bản'
const source = (item: MagazineArticle) => item.source || item.platform || 'Chưa rõ nguồn'
const title = (item: MagazineArticle) => item.title || `Tài liệu ${item.document_id}`
const showQuery = (showId: string, days = 30) => showId ? `?show_id=${encodeURIComponent(showId)}&days=${days}` : `?days=${days}`

function ScopeNote({ bundle }: { bundle: MagazineBundle }) {
  return <p className="mag-scope-note">{bundle.roster_status === 'needs_review' ? 'Danh sách tham gia show trong đồ thị còn liên kết chờ kiểm tra; tin và số liệu dưới đây chỉ là kết quả quan sát từ các liên kết đó.' : 'Danh sách nghệ sĩ dựa trên liên kết tham gia show đã xác nhận.'} Lượt nhắc là số tài liệu trong nguồn thu thập, không đo mức độ nổi tiếng.</p>
}

function ShowFilter({ shows, value, onChange }: { shows: MagazineShow[]; value: string; onChange: (value: string) => void }) {
  return <div className="mag-show-filter" role="group" aria-label="Lọc theo chương trình">
    <button aria-pressed={!value} onClick={() => onChange('')}>Tất cả show</button>
    {shows.map((show) => <button key={show.id} aria-pressed={value === show.id} onClick={() => onChange(show.id)}>{show.name}</button>)}
  </div>
}

function ArticleMedia({ item, className = '' }: { item: MagazineArticle; className?: string }) {
  return <Link to={`/article/${encodeURIComponent(item.document_id)}`} className={`mag-media ${item.image_url ? 'has-image' : 'is-typographic'} ${className}`} aria-label={`Đọc ${title(item)}`}>
    {item.image_url ? <img src={item.image_url} alt="" loading="lazy" /> : <><span className="mag-media-word">RADAR</span><span className="mag-media-activity">{item.activity[0] || 'Âm nhạc Việt'}</span><span className="mag-media-slash" aria-hidden="true" /></>}
  </Link>
}

function ArticleCard({ item, lead = false }: { item: MagazineArticle; lead?: boolean }) {
  return <article className={`mag-story ${lead ? 'is-lead' : ''} ${!item.image_url ? 'is-text-led' : ''}`}>
    <ArticleMedia item={item} />
    <div className="mag-story-body">
      <p className="mag-story-meta"><span>{item.activity[0] || 'Tin nghệ sĩ'}</span><span>{source(item)}</span><time>{date(item.published_at)}</time></p>
      <h3><Link to={`/article/${encodeURIComponent(item.document_id)}`}>{title(item)}</Link></h3>
      {(item.summary || item.excerpt) && <p className="mag-story-excerpt">{item.summary || `“${item.excerpt}”`}</p>}
      <div className="mag-story-artists">{item.artists.slice(0, lead ? 5 : 3).map((artist) => <Link key={artist.id} to={`/artists/${encodeURIComponent(artist.id)}`}>{artist.name}</Link>)}</div>
    </div>
  </article>
}

function PeriodFilter({ days, onChange }: { days: number; onChange: (days: number) => void }) {
  return <div className="mag-period" role="group" aria-label="Khoảng thời gian">{[7, 30, 90].map((value) => <button key={value} aria-pressed={days === value} onClick={() => onChange(value)}>{value} ngày</button>)}</div>
}

function DataSection({ bundle, showId, days }: { bundle: MagazineBundle; showId: string; days: number }) {
  const navigate = useNavigate()
  const [sortBy, setSortBy] = useState<'documents' | 'name'>('documents')
  const chart = useMemo(() => ({
    color: ['#F24D3D'],
    tooltip: { trigger: 'axis', formatter: (params: { name: string; value: number }[]) => `${params[0]?.name || ''}<br/>${params[0]?.value || 0} tài liệu` },
    grid: { left: 34, right: 12, top: 20, bottom: 38 },
    xAxis: { type: 'category', data: bundle.daily.map((row) => row.date), axisLabel: { color: '#697077', hideOverlap: true, formatter: (value: string) => value.slice(5).replace('-', '/') }, axisTick: { show: false } },
    yAxis: { type: 'value', minInterval: 1, axisLabel: { color: '#697077' }, splitLine: { lineStyle: { color: '#dedbd4' } } },
    series: [{ type: 'bar', data: bundle.daily.map((row) => row.documents), barMaxWidth: 16, itemStyle: { borderRadius: [2, 2, 0, 0] } }],
  }), [bundle.daily])
  const filterBase = showId ? `show_id=${encodeURIComponent(showId)}&` : ''
  return <section className="mag-data" aria-labelledby="mag-data-title">
    <div className="mag-section-head"><div><h2 id="mag-data-title">Âm nhạc qua số liệu</h2><p>{number(bundle.total)} tài liệu có bằng chứng · {bundle.period.from} đến {bundle.period.to}</p></div><Link to={`/trends${showQuery(showId, days)}`}>Xem toàn bộ xu hướng <ArrowRight size={17} /></Link></div>
    <div className="mag-data-grid"><div className="mag-chart"><h3>Nhịp tin theo ngày xuất bản</h3><p>Chọn một cột để mở tài liệu của ngày đó.</p><EChart option={chart} height={255} onClick={(params) => { if (params.name) navigate(`/feed?${filterBase}days=${days}&date_from=${params.name}&date_to=${params.name}`) }} /></div>
      <div className="mag-ranking"><h3>Nghệ sĩ được nhắc trong nguồn</h3>{bundle.top_artists.length ? <ol>{bundle.top_artists.slice(0, 6).map((artist, index) => <li key={artist.id}><span>{String(index + 1).padStart(2, '0')}</span><Link to={`/feed?${filterBase}days=${days}&artist_id=${encodeURIComponent(artist.id)}`}>{artist.name}</Link><strong>{number(artist.documents)}</strong><div className="mag-bar-track"><span style={{ width: `${artist.documents / bundle.top_artists[0].documents * 100}%` }} /></div></li>)}</ol> : <p>Chưa có lượt nhắc trong kỳ.</p>}</div></div>
    <div className="mag-activity"><h3>Loại hoạt động được ghi nhận</h3><p>Nhóm suy từ loại quan hệ có bằng chứng; một tài liệu có thể thuộc nhiều nhóm.</p><div>{bundle.activity.length ? bundle.activity.map((kind) => <Link key={kind.name} to={`/feed?${filterBase}days=${days}&activity=${encodeURIComponent(kind.name)}`}><span>{kind.name}</span><strong>{number(kind.documents)} tài liệu</strong><ArrowUpRight size={15} /><i className="mag-activity-bar" style={{ width: `${kind.documents / bundle.activity[0].documents * 100}%` }} /></Link>) : <p>Chưa có hoạt động được ghi nhận trong kỳ.</p>}</div></div>
    {bundle.top_artists.length > 0 && <div className="mag-data-table"><div><h3>Bảng lượt nhắc nghệ sĩ</h3><p>Đếm tài liệu phân biệt theo ID trong kỳ; chọn tên để xem tin.</p></div><div className="mag-table-scroll"><table><thead><tr><th><button onClick={() => setSortBy('name')} aria-label="Sắp xếp theo tên nghệ sĩ">Nghệ sĩ {sortBy === 'name' ? '↑' : ''}</button></th><th><button onClick={() => setSortBy('documents')} aria-label="Sắp xếp theo số tài liệu">Tài liệu {sortBy === 'documents' ? '↓' : ''}</button></th></tr></thead><tbody>{[...bundle.top_artists].sort((a, b) => sortBy === 'name' ? a.name.localeCompare(b.name, 'vi') : b.documents - a.documents || a.name.localeCompare(b.name, 'vi')).slice(0, 20).map((artist) => <tr key={artist.id}><td><Link to={`/feed?${filterBase}days=${days}&artist_id=${encodeURIComponent(artist.id)}`}>{artist.name}</Link></td><td>{number(artist.documents)}</td></tr>)}</tbody></table></div></div>}
    <ScopeNote bundle={bundle} />
  </section>
}

export function MagazineHome() {
  const [params, setParams] = useSearchParams()
  const showId = params.get('show_id') || ''
  const days = [7, 30, 90].includes(Number(params.get('days'))) ? Number(params.get('days')) : 30
  const [reload, setReload] = useState(0)
  const state = useAsync(() => api.magazineArticles({ days, show_id: showId || undefined, limit: 12 }), [days, showId, reload])
  const setFilter = (key: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); setParams(next) }
  const bundle = state.data
  return <div className="mag-page mag-home">
    <div className="mag-intro"><div><h1>Nhịp mới của <em>âm nhạc Việt.</em></h1><p>Theo dấu hoạt động của nghệ sĩ sau những sân khấu truyền hình, qua tài liệu và nguồn có thể đối chiếu.</p></div><button onClick={() => setReload((n) => n + 1)} disabled={state.loading} aria-label="Tải lại tin mới"><RotateCcw size={17} /> Tải lại</button></div>
    {bundle && <><ShowFilter shows={bundle.shows} value={showId} onChange={(value) => setFilter('show_id', value)} /><div className="mag-window"><span>Tin và hoạt động trong {days} ngày</span><PeriodFilter days={days} onChange={(value) => setFilter('days', String(value))} /></div>{bundle.roster_status === 'needs_review' && <p className="mag-roster-banner">Danh sách thí sinh trong đồ thị đang chờ kiểm tra. Tin dưới đây được lọc theo các liên kết hiện có.</p>}</>}
    {state.loading && !bundle ? <Loading label="Đang đọc tin nghệ sĩ…" /> : state.error ? <ErrorBox error={state.error} onRetry={() => setReload((n) => n + 1)} /> : bundle && <>
      <section className="mag-lead-section" aria-labelledby="mag-latest"><div className="mag-section-head"><div><h2 id="mag-latest">Tin mới nhất trong dữ liệu</h2><p>{bundle.items[0] ? `Nguồn xuất bản gần nhất: ${date(bundle.items[0].published_at)}` : 'Chưa có ngày xuất bản trong kỳ'} · có bằng chứng trong đồ thị</p></div><Link to={`/feed${showQuery(showId, days)}`}>Đọc tất cả tin <ArrowRight size={17} /></Link></div>
        {bundle.items.length ? <div className="mag-lead-grid"><ArticleCard item={bundle.items[0]} lead /><div className="mag-secondary-stories">{bundle.items.slice(1, 4).map((item) => <ArticleCard key={item.document_id} item={item} />)}</div></div> : <div className="mag-empty"><h3>Chưa có tin trong khoảng đang xem</h3><p>Thử chọn 90 ngày hoặc một show khác. Những liên kết tham gia chương trình hiện cũng đang được đối chiếu.</p></div>}
      </section>
      <section className="mag-activity-section" aria-labelledby="mag-activity-title"><div className="mag-section-head"><div><h2 id="mag-activity-title">Hoạt động nghệ sĩ</h2><p>Các tài liệu mới tiếp theo trong kỳ</p></div><Link to={`/artists${showQuery(showId, days)}`}>Xem nghệ sĩ <ArrowRight size={17} /></Link></div><div className="mag-story-row">{bundle.items.slice(4, 8).map((item) => <ArticleCard key={item.document_id} item={item} />)}{bundle.items.length > 0 && bundle.items.length < 5 && <p className="mag-small-empty">Chưa có thêm tin để hiển thị ở mục này.</p>}</div></section>
      <section className="mag-digest"><div><h2>Chuyển động trong kỳ</h2><p>Trong {days} ngày qua, nguồn đã thu thập có <strong>{number(bundle.total)} tài liệu</strong> liên quan đến phạm vi nghệ sĩ đang xem. {bundle.top_artists[0] ? <><Link to={`/feed?days=${days}${showId ? `&show_id=${showId}` : ''}&artist_id=${bundle.top_artists[0].id}`}>{bundle.top_artists[0].name}</Link> xuất hiện trong {number(bundle.top_artists[0].documents)} tài liệu.</> : 'Chưa có nghệ sĩ được ghi nhận trong kỳ.'} Đây là số quan sát được trong tập nguồn, không phải kết luận về thị trường.</p></div><Link to={`/trends${showQuery(showId, days)}`}>Đọc xu hướng <ArrowRight size={18} /></Link></section>
      <DataSection bundle={bundle} showId={showId} days={days} />
      <section className="mag-discover"><h2>Đi sâu vào câu chuyện</h2><div><Link to="/watch">Theo dõi nghệ sĩ <ArrowUpRight size={19} /></Link><Link to="/explain">Vì sao liên quan? <ArrowUpRight size={19} /></Link><Link to="/ask">Hỏi đáp có nguồn <ArrowUpRight size={19} /></Link><Link to="/network">Khám phá mạng âm nhạc <ArrowUpRight size={19} /></Link></div></section>
    </>}
  </div>
}

export function MagazineFeed() {
  const [params, setParams] = useSearchParams()
  const [sourceInput, setSourceInput] = useState(params.get('source') || '')
  const debouncedSource = useDebounced(sourceInput)
  const [reload, setReload] = useState(0)
  const days = [7, 30, 90].includes(Number(params.get('days'))) ? Number(params.get('days')) : 30
  const showId = params.get('show_id') || ''
  const artistId = params.get('artist_id') || ''
  const activity = params.get('activity') || ''
  const dateFrom = params.get('date_from') || ''
  const dateTo = params.get('date_to') || ''
  const offset = Number(params.get('offset') || 0)
  const state = useAsync(() => api.magazineArticles({ days, show_id: showId || undefined, artist_id: artistId || undefined, activity: activity || undefined, source: debouncedSource || undefined, date_from: dateFrom || undefined, date_to: dateTo || undefined, offset, limit: 20 }), [days, showId, artistId, activity, debouncedSource, dateFrom, dateTo, offset, reload])
  const people = useAsync(() => api.magazineArtists(showId || undefined), [showId])
  const update = (key: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); if (key !== 'offset') next.delete('offset'); setParams(next) }
  const bundle = state.data
  return <div className="mag-page mag-feed"><div className="mag-page-heading"><h1>Tin & hoạt động</h1><p>Chọn show, nghệ sĩ và nguồn để theo dõi những tài liệu có bằng chứng.</p></div>
    <div className="mag-filter-grid"><label>Show<select value={showId} onChange={(e) => update('show_id', e.target.value)}><option value="">Tất cả 9 show</option>{bundle?.shows.map((show) => <option value={show.id} key={show.id}>{show.name}</option>)}</select></label><label>Nghệ sĩ<select value={artistId} onChange={(e) => update('artist_id', e.target.value)}><option value="">Tất cả nghệ sĩ</option>{people.data?.map((artist) => <option value={artist.id} key={artist.id}>{artist.name}</option>)}</select></label><label>Khoảng xem<select value={days} onChange={(e) => update('days', e.target.value)}><option value={7}>7 ngày</option><option value={30}>30 ngày</option><option value={90}>90 ngày</option></select></label><label>Nguồn chứa tên<input value={sourceInput} onChange={(e) => setSourceInput(e.target.value)} placeholder="Báo hoặc kênh" /></label><label>Loại hoạt động<select value={activity} onChange={(e) => update('activity', e.target.value)}><option value="">Mọi hoạt động</option>{['Tác phẩm','Hợp tác','Biểu diễn','Chương trình','Tranh chấp','Thương hiệu','Hoạt động khác'].map((name) => <option key={name}>{name}</option>)}</select></label><label>Từ ngày<input type="date" value={dateFrom} onChange={(e) => update('date_from', e.target.value)} /></label><label>Đến ngày<input type="date" value={dateTo} onChange={(e) => update('date_to', e.target.value)} /></label></div>
    {state.loading && !bundle ? <Loading label="Đang lấy tin…" /> : state.error ? <ErrorBox error={state.error} onRetry={() => setReload((n) => n + 1)} /> : bundle && <><div className="mag-results-line"><strong>{number(bundle.total)} tài liệu</strong><span>{bundle.period.from} — {bundle.period.to}</span></div>{bundle.items.length ? <div className="mag-feed-list">{bundle.items.map((item) => <ArticleCard key={item.document_id} item={item} />)}</div> : <div className="mag-empty"><h2>Chưa có tin phù hợp</h2><p>Thử mở rộng ngày hoặc bỏ bớt bộ lọc.</p></div>}{bundle.total > 20 && <nav className="mag-pagination" aria-label="Phân trang"><button disabled={offset === 0} onClick={() => update('offset', String(Math.max(0, offset - 20)))}>Trang trước</button><span>Trang {Math.floor(offset / 20) + 1}</span><button disabled={offset + 20 >= bundle.total} onClick={() => { const next = new URLSearchParams(params); next.set('offset', String(offset + 20)); setParams(next) }}>Trang sau</button></nav>}<ScopeNote bundle={bundle} /></>}
  </div>
}

export function MagazineTrends() {
  const [params, setParams] = useSearchParams()
  const days = [7, 30, 90].includes(Number(params.get('days'))) ? Number(params.get('days')) : 30
  const showId = params.get('show_id') || ''
  const state = useAsync(() => api.magazineArticles({ days, show_id: showId || undefined, limit: 1 }), [days, showId])
  const update = (key: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); setParams(next) }
  return <div className="mag-page mag-trends"><div className="mag-page-heading"><h1>Xu hướng qua tài liệu</h1><p>Nhịp xuất bản và hoạt động được ghi nhận trong các nguồn của dự án.</p></div>{state.data && <><ShowFilter shows={state.data.shows} value={showId} onChange={(value) => update('show_id', value)} /><PeriodFilter days={days} onChange={(value) => update('days', String(value))} /></>}{state.loading && !state.data ? <Loading /> : state.error ? <ErrorBox error={state.error} /> : state.data && <DataSection bundle={state.data} showId={showId} days={days} />}</div>
}

export function MagazineArticlePage() {
  const { id = '' } = useParams()
  const state = useAsync(() => api.magazineArticle(id), [id])
  const item = state.data
  return <div className="mag-page mag-article-page"><Link to="/feed" className="mag-back">← Tất cả tin</Link>{state.loading ? <Loading /> : state.error ? <ErrorBox error={state.error} /> : item && <article><p className="mag-story-meta"><span>{item.activity.join(' · ') || 'Tin nghệ sĩ'}</span><span>{source(item)}</span><time>{date(item.published_at)}</time></p><h1>{title(item)}</h1>{item.summary && <p className="mag-article-summary">{item.summary}</p>}{item.image_url && <figure><img src={item.image_url} alt="" /><figcaption>Ảnh: <a href={item.image_source_url || '#'} target="_blank" rel="noreferrer">{item.image_credit}</a> · {item.image_license}</figcaption></figure>}<section><h2>Nghệ sĩ liên quan</h2><div className="mag-story-artists">{item.artists.map((artist) => <Link key={artist.id} to={`/artists/${encodeURIComponent(artist.id)}`}>{artist.name}</Link>)}</div></section><section><h2>Bằng chứng trong tài liệu</h2><ul className="mag-article-evidence">{item.relations.map((rel) => <li key={rel.relation_id}><p><Link to={`/artists/${encodeURIComponent(rel.artist_id)}`}>{rel.artist_name}</Link> · {RELATION_LABEL[rel.relation] || rel.relation} · {rel.related_name}</p>{rel.quote && <blockquote>“{rel.quote}”</blockquote>}</li>)}</ul></section>{item.url && <a className="mag-source-link" href={item.url} target="_blank" rel="noreferrer">Đọc tài liệu gốc <ExternalLink size={17} /></a>}<p className="mag-scope-note">Ngày trên trang là ngày xuất bản; ngày thu thập: {date(item.collected_at)}. Quan hệ tham gia show có thể đang chờ kiểm tra.</p></article>}</div>
}

export function MagazineArtists() {
  const [params, setParams] = useSearchParams()
  const showId = params.get('show_id') || ''
  const shows = useAsync(api.magazineShows, [])
  const artists = useAsync(() => api.magazineArtists(showId || undefined), [showId])
  return <div className="mag-page mag-artists"><div className="mag-page-heading"><h1>Nghệ sĩ từ các show</h1><p>Danh sách dựa trên quan hệ thí sinh trong đồ thị; trạng thái xác minh được hiển thị cho từng người.</p></div>{shows.data && <ShowFilter shows={shows.data} value={showId} onChange={(value) => { const next = new URLSearchParams(); if (value) next.set('show_id', value); setParams(next) }} />}{artists.loading ? <Loading /> : artists.error ? <ErrorBox error={artists.error} /> : <><p className="mag-results-line"><strong>{number(artists.data?.length || 0)} nghệ sĩ</strong></p><div className="mag-artist-list">{artists.data?.map((artist) => <Link key={artist.id} to={`/artists/${encodeURIComponent(artist.id)}`}><strong>{artist.name}</strong><span>{shows.data?.filter((show) => artist.shows.includes(show.id)).map((show) => show.name).join(' · ')}</span><small>{artist.verified_shows.length ? 'Có liên kết đã xác nhận' : 'Liên kết tham gia chờ kiểm tra'}</small><ArrowUpRight size={18} /></Link>)}</div></>}</div>
}

export function MagazineArtistPage() {
  const { id = '' } = useParams()
  const artists = useAsync(() => api.magazineArtists(), [])
  const state = useAsync(() => api.magazineArticles({ days: 90, artist_id: id, limit: 50 }), [id])
  const artist = artists.data?.find((row) => row.id === id)
  const shows = state.data?.shows.filter((show) => artist?.shows.includes(show.id)) || []
  return <div className="mag-page mag-artist-page"><Link to="/artists" className="mag-back">← Nghệ sĩ</Link>{state.loading || artists.loading ? <Loading /> : state.error || artists.error ? <ErrorBox error={state.error || artists.error} /> : !artist ? <div className="mag-empty"><h1>Không tìm thấy nghệ sĩ</h1><p>Người này chưa có liên kết thí sinh trong 9 show.</p></div> : <><div className="mag-page-heading"><h1>{artist.name}</h1><p>{shows.map((show) => show.name).join(' · ') || 'Chưa rõ show'}</p></div><p className="mag-scope-note">{artist.verified_shows.length ? 'Một số liên kết tham gia đã xác nhận.' : 'Liên kết tham gia show đang chờ kiểm tra.'} Trong 90 ngày: {number(state.data?.total || 0)} tài liệu có bằng chứng.</p><div className="mag-profile-actions"><Link to={`/feed?days=90&artist_id=${encodeURIComponent(id)}`}>Xem mọi tin <ArrowRight size={16} /></Link><Link to={`/entity/${encodeURIComponent(id)}`}>Xem mạng quan hệ <ArrowRight size={16} /></Link></div><h2 className="mag-subhead">Hoạt động gần đây</h2>{state.data?.items.length ? <div className="mag-feed-list">{state.data.items.map((item) => <ArticleCard key={item.document_id} item={item} />)}</div> : <p className="mag-small-empty">Chưa có tài liệu mới trong 90 ngày.</p>}</>}</div>
}
