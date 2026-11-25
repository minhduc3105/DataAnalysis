import { ArrowDownRight, ArrowRight, ArrowUpRight, Clock3, FileText, Radio, RefreshCw, Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { EChart } from '../components/EChart'
import { ErrorBox, Loading, PageHeader } from '../components/ui'
import { useAsync } from '../hooks'
import { RELATION_LABEL, fmt } from '../labels'

const dayLabel = (value: string) => value.slice(5).replace('-', '/')
const platform = (value: string) => ({ youtube: 'YouTube', spotify: 'Spotify', web: 'Báo chí / web' })[value?.toLowerCase()] ?? (value || 'Nguồn khác')
const checkpointLabel = (value: Record<string, unknown> | null | undefined, property = 'updated_at') => {
  if (!value) return 'Chưa có checkpoint'
  if (value.status === 'skipped_missing_credentials' || value.status === 'skipped_no_api_key') return 'Thiếu cấu hình'
  if (value.checkpoint_advanced === false) return 'Chưa hoàn tất'
  return typeof value[property] === 'string' ? 'Đã chạy' : 'Chưa có mốc thành công'
}
const statusLabel = (value?: string) => ({ not_run: 'Chưa chạy', not_configured: 'Chưa cấu hình', skipped_missing_credentials: 'Thiếu thông tin xác thực', skipped_no_api_key: 'Thiếu API key', ok: 'Hoàn tất', running: 'Đang chạy', partial: 'Một phần', failed: 'Lỗi', awaiting_review: 'Chờ duyệt', awaiting_review_with_source_gaps: 'Chờ duyệt · thiếu nguồn', partial_failure: 'Lỗi một phần', preserved: 'Được giữ nguyên', manual_step_required: 'Chờ thao tác duyệt', awaiting_external_handoff: 'Chờ bàn giao trích xuất', waiting_for_extraction: 'Chờ trích xuất', pending_manual_review: 'Chờ người duyệt' })[value ?? ''] ?? (value || 'Chưa rõ')
const PIPELINE_STEPS = [
  ['web_discovery', 'Tìm tài liệu báo chí'], ['web_crawl', 'Thu thập nội dung báo chí'], ['normalize_and_review', 'Chuẩn hóa và kiểm tra'], ['youtube', 'Thu thập YouTube'], ['spotify', 'Thu thập Spotify'], ['live_documents', 'Tạo tài liệu luồng mới'], ['content_classification', 'Phân loại chủ đề / sắc thái'], ['relation_extraction', 'Trích xuất quan hệ'], ['validation', 'Kiểm tra quan hệ'], ['relation_review', 'Duyệt quan hệ'], ['import_approved', 'Nạp quan hệ được duyệt'], ['research_snapshot', 'Snapshot nghiên cứu'],
] as const

function Delta({ value }: { value: { delta: number; change_percent: number | null; comparison: string } }) {
  if (value.comparison === 'incomplete_coverage') return <span className="metric-note">Chưa đủ độ phủ để so sánh</span>
  if (value.comparison === 'new') return <span className="metric-change is-positive">Mới xuất hiện · +{fmt(value.delta)}</span>
  if (value.comparison === 'no_baseline') return <span className="metric-note">Chưa có kỳ trước</span>
  const positive = value.delta >= 0
  const Icon = positive ? ArrowUpRight : ArrowDownRight
  return <span className={`metric-change ${positive ? 'is-positive' : 'is-negative'}`}><Icon size={14} />{positive ? '+' : ''}{fmt(value.delta)} · {positive ? '+' : ''}{fmt(value.change_percent, 1)}%</span>
}

export function DashboardPage() {
  const [days, setDays] = useState(7)
  const [reload, setReload] = useState(0)
  const [statusReload, setStatusReload] = useState(0)
  const state = useAsync(() => api.overview(days), [days, reload])
  const status = useAsync(api.updateStatus, [statusReload])
  const alertState = useAsync(() => api.alerts(), [statusReload])
  const classificationState = useAsync(() => api.classifications(3), [statusReload])
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') setStatusReload((value) => value + 1)
    }, 5 * 60 * 1000)
    const updateWhenVisible = () => { if (document.visibilityState === 'visible') setStatusReload((value) => value + 1) }
    document.addEventListener('visibilitychange', updateWhenVisible)
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', updateWhenVisible) }
  }, [])
  const value = state.data
  const chartOption = {
    color: ['#16866b'],
    tooltip: { trigger: 'axis' },
    grid: { left: 36, right: 12, top: 20, bottom: 34 },
    xAxis: { type: 'category', data: value?.daily.map((row) => dayLabel(row.date)) ?? [], axisLabel: { color: '#66736e' }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#dce3df' } } },
    yAxis: { type: 'value', minInterval: 1, name: 'Tài liệu', nameTextStyle: { color: '#66736e' }, axisLabel: { color: '#66736e' }, splitLine: { lineStyle: { color: '#e8eeeb' } } },
    series: [{ type: 'line', data: value?.daily.map((row) => row.documents) ?? [], showSymbol: false, lineStyle: { width: 2.5 }, areaStyle: { opacity: 0.08 } }],
  }
  const documentCount = value?.metrics.documents.current ?? 0
  const newest = value?.recent_documents ?? []
  const summary = value ? `Trong ${days} ngày, hệ thống ghi nhận ${fmt(documentCount)} tài liệu có bằng chứng. ${value.coverage.status === 'complete' ? 'Hai kỳ đều có nhật ký thu thập đầy đủ.' : 'Độ phủ chưa đầy đủ; chênh lệch chỉ là số quan sát được, chưa thể kết luận mức tăng giảm.'}` : ''

  return <div className="dashboard-page">
    <PageHeader title="Tổng quan hôm nay" subtitle="Tin mới, nhịp thảo luận và những kết nối đang được ghi nhận trong dữ liệu âm nhạc Việt."><div className="dashboard-actions"><div className="period-switch" role="group" aria-label="Khoảng thời gian">{[7, 30, 90].map((option) => <button key={option} aria-pressed={days === option} onClick={() => setDays(option)}>{option} ngày</button>)}</div><button className="icon-action" onClick={() => setReload((n) => n + 1)} disabled={state.loading} aria-label="Làm mới tổng quan" title="Tải lại dữ liệu"><RefreshCw size={16} /></button></div></PageHeader>
    {state.loading && !value ? <Loading label="Đang tổng hợp tài liệu và xu hướng…" /> : state.error ? <ErrorBox error={state.error} onRetry={() => setReload((n) => n + 1)} /> : value && <>
      <section className="overview-lead"><div className="lead-mark"><Sparkles size={17} /></div><div><h2>Tâm điểm dữ liệu</h2><p>{summary}</p></div><span className="lead-period">{value.period.from} — {value.period.to}</span></section>
      <div className="overview-metrics" aria-label="Chỉ số trong khoảng thời gian"><article><span>Tài liệu có bằng chứng</span><strong>{fmt(value.metrics.documents.current)}</strong><Delta value={value.metrics.documents} /></article><article><span>Thực thể được nhắc</span><strong>{fmt(value.metrics.entities.current)}</strong><Delta value={value.metrics.entities} /></article><article><span>Quan hệ trong tài liệu</span><strong>{fmt(value.metrics.relations.current)}</strong><Delta value={value.metrics.relations} /></article><article className="updated-metric"><span><Clock3 size={14} /> Thu thập toàn bộ dữ liệu lần cuối</span><strong>{value.latest_collected_at ? new Date(value.latest_collected_at).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', dateStyle: 'short', timeStyle: 'short' }) : 'Chưa có mốc'}</strong><small>Tài liệu xuất bản mới nhất: {value.latest_published_at || 'Chưa rõ'}</small></article></div>
      <div className="overview-highlights">
        <section className="dashboard-panel fresh-panel"><div className="panel-heading"><div><h2>Tài liệu mới nhất</h2><p>Các tài liệu có quan hệ kèm bằng chứng đã duyệt</p></div><span className="result-count"><FileText size={14} />{fmt(newest.length)}</span></div>{newest.length ? <div className="fresh-list">{newest.map((doc) => <article key={doc.document_id}><div className="fresh-meta"><span>{platform(doc.platform)}</span><span>{doc.source || 'Chưa rõ nguồn'}</span><time>{doc.published_at?.slice(0, 10) || 'Chưa rõ ngày'}</time></div><h3>{doc.url ? <a href={doc.url} target="_blank" rel="noreferrer">{doc.title || doc.document_id}<ArrowRight size={14} /></a> : doc.title || doc.document_id}</h3><p>{doc.relations.slice(0, 2).map((rel) => <span className="fresh-relation" key={rel.relation_id}><b>{rel.source}</b> → {RELATION_LABEL[rel.relation] ?? rel.relation} → <b>{rel.target}</b></span>)}</p>{doc.relations[0]?.evidence && <blockquote>“{doc.relations[0].evidence}”</blockquote>}</article>)}</div> : <p className="quiet-empty">Chưa có tài liệu có bằng chứng trong kỳ này.</p>}<Link to="/feed" className="panel-footer-link">Mở toàn bộ bảng tin <ArrowRight size={14} /></Link></section>
        <div className="highlight-side">
          <section className="dashboard-panel entity-panel"><div className="panel-heading"><div><h2>Thực thể tăng lượt nhắc</h2><p>Chênh lệch quan sát theo ID so với kỳ liền trước; chưa đủ độ phủ để kết luận xu hướng thị trường.</p></div></div>{value.top_entities.length ? <ol>{value.top_entities.map((entity, i) => <li key={entity.id}><span className="rank-number">{String(i + 1).padStart(2, '0')}</span><Link to={`/entity/${encodeURIComponent(entity.id)}`}>{entity.name}</Link><span className="entity-doc-count is-rising">+{fmt(entity.delta)} · {fmt(entity.documents)} tài liệu</span></li>)}</ol> : <p className="quiet-empty">Chưa ghi nhận lượt nhắc tăng trong dữ liệu của kỳ này.</p>}</section>
          <section className="dashboard-panel alert-panel"><div className="panel-heading"><div><h2>Cảnh báo đáng chú ý</h2><p>Thực thể bạn đang theo dõi · quan hệ trực tiếp</p></div></div>{alertState.loading ? <p className="quiet-empty">Đang kiểm tra cảnh báo…</p> : alertState.error ? <p className="quiet-empty">Chưa đọc được cảnh báo; xem lại ở <Link to="/watch">Theo dõi</Link>.</p> : alertState.data?.length ? <ul>{alertState.data.slice(0, 3).map((item) => <li key={item.entity_id}><p><b>{item.name}</b> · {item.kind === 'new_mentions' ? 'tin mới' : item.kind === 'collaboration' ? 'hợp tác' : item.kind === 'release' ? 'phát hành' : item.kind === 'dispute' ? 'tranh chấp' : 'chương trình'} · {fmt(item.count_7d)} tài liệu</p><small>{item.anomaly ? `Đột biến · z=${item.z_score}` : item.requires_more_history ? 'Chưa đủ nhật ký thu thập để kiểm tra đột biến' : `Nền ${fmt(item.baseline_daily_mean, 2)} tài liệu/ngày`}</small>{item.sources?.[0]?.url && <a href={item.sources[0].url} target="_blank" rel="noreferrer">{item.sources[0].title || 'Mở bằng chứng'} ↗</a>}</li>)}</ul> : <p className="quiet-empty">Chưa có cảnh báo mới trong danh sách theo dõi.</p>}</section>
        </div>
      </div>
      <div className="dashboard-lower-grid">
        <section className="dashboard-panel trend-panel"><div className="panel-heading"><div><h2>Nhịp tin</h2><p>Tài liệu phân biệt theo ngày xuất bản</p></div><Link to="/trends" className="text-action">Phân tích xu hướng <ArrowRight size={14} /></Link></div><EChart option={chartOption} height={220} /></section>
        <aside className="dashboard-side">
          <section className="dashboard-panel source-panel"><div className="panel-heading"><div><h2>Nguồn dữ liệu</h2><p>Trong kết quả của kỳ đang xem</p></div><Radio size={16} /></div>{value.platforms.length ? <ul>{value.platforms.map((row) => <li key={row.platform}><span>{platform(row.platform)}</span><strong>{fmt(row.documents)}</strong></li>)}</ul> : <p className="quiet-empty">Chưa có nguồn trong kỳ.</p>}<div className="coverage-note">{value.coverage.note}</div></section>
          <section className="dashboard-panel topics-panel"><div className="panel-heading"><div><h2>Chủ đề và sắc thái</h2><p>{value.topics.status === 'relation_derived' ? 'Chủ đề suy ra từ loại quan hệ đã duyệt' : 'Phân loại theo nội dung tài liệu'}</p></div></div>{value.topics.items.length ? <ul>{value.topics.items.slice(0, 5).map((item) => <li key={item.topic}>{item.topic}<strong>{fmt(item.documents)}</strong></li>)}</ul> : <div className="feature-unavailable"><span>{value.topics.status === 'not_configured' ? 'Chưa cấu hình mô hình phân loại' : 'Chưa có dữ liệu chủ đề'}</span><p>{value.topics.status === 'relation_derived' ? 'Chưa có quan hệ đã duyệt trong kỳ.' : 'Thống kê tiếp tục hoạt động; nhãn không được tự điền khi mô hình thiếu hoặc lỗi.'}</p></div>}<p className="sentiment-note">{value.sentiment.interpretation} {value.sentiment.status === 'ready' ? value.sentiment.items.map((item) => `${item.sentiment}: ${fmt(item.documents)}`).join(' · ') : 'Phân loại sắc thái chưa sẵn sàng.'}</p>{classificationState.data?.items.filter((item) => item.status === 'ready' && item.quote).slice(0, 2).map((item) => <blockquote className="classification-example" key={`${item.document_id}-${item.classified_at}`}>“{item.quote}”<small>{item.topics.join(' · ') || 'Không gán chủ đề'} · {item.sentiment} · {item.model_version}</small>{item.url && <a href={item.url} target="_blank" rel="noreferrer">{item.source || item.title || 'Đối chiếu tài liệu'} ↗</a>}</blockquote>)}</section>
          <section className="dashboard-panel community-panel"><div className="panel-heading"><div><h2>Cộng đồng được nhắc</h2><p>Snapshot {value.analysis_snapshot?.graph_version ? value.analysis_snapshot.graph_version.slice(0, 12) : 'chưa xác định'} · không thay đổi theo kỳ tin</p></div></div>{value.top_communities.length ? <ul>{value.top_communities.slice(0, 4).map((community) => <li key={community.id}><span>{community.name}<small>{fmt(community.size)} nghệ sĩ trong snapshot</small></span><strong>{fmt(community.documents)} tài liệu</strong></li>)}</ul> : <p className="quiet-empty">Chưa thể gắn lượt nhắc với cộng đồng trong snapshot.</p>}</section>
          {value.new_relations.length > 0 && <section className="dashboard-panel approved-panel"><div className="panel-heading"><div><h2>Quan hệ mới được duyệt</h2><p>Ngày duyệt, độc lập với ngày sự kiện trong nguồn</p></div></div><ul>{value.new_relations.slice(0, 4).map((rel) => <li key={rel.event_id}><p><b>{rel.source}</b> → {RELATION_LABEL[rel.relation] ?? rel.relation} → <b>{rel.target}</b></p><blockquote>“{rel.quote}”</blockquote>{rel.url && <a href={rel.url} target="_blank" rel="noreferrer">{rel.source_name || rel.title} · Đối chiếu nguồn</a>}</li>)}</ul></section>}
          <section className="dashboard-panel pipeline-panel"><div className="panel-heading"><div><h2>Cập nhật dữ liệu</h2><p>Báo và YouTube 07:00 mỗi ngày · Spotify thứ Hai</p></div></div>{status.data ? <><ul><li>Báo chí <strong>{statusLabel(status.data.sources?.web?.status)} · {checkpointLabel(status.data.checkpoints.web)}</strong></li><li>YouTube <strong>{statusLabel(status.data.sources?.youtube?.status)} · {checkpointLabel(status.data.checkpoints.youtube, 'youtube_updated_at')}</strong></li><li>Spotify <strong>{statusLabel(status.data.sources?.spotify?.status)} · {checkpointLabel(status.data.checkpoints.spotify)}</strong></li></ul><p className="pipeline-footnote">Lượt gần nhất: {statusLabel(status.data.pipeline?.status)}{status.data.pipeline?.updated_at ? ` · ${new Date(status.data.pipeline.updated_at).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' })}` : ''}</p>{status.data.pipeline?.steps?.relation_review?.pending_review !== undefined && <p className="pipeline-footnote">{fmt(status.data.pipeline.steps.relation_review.pending_review)} quan hệ đang chờ duyệt. Luồng tự động không xác nhận quan hệ.</p>}<p className="pipeline-footnote">Phân loại chủ đề/sắc thái: {statusLabel(status.data.content_classification?.status)}{status.data.content_classification?.model_version ? ` · ${status.data.content_classification.model_version}` : ''}{status.data.content_classification?.failed ? ` · lỗi ${status.data.content_classification.failed}` : ''}</p><details className="pipeline-details"><summary>Chi tiết từng bước</summary><ul>{PIPELINE_STEPS.map(([key, label]) => <li key={key}><span>{label}</span><strong>{statusLabel(status.data?.pipeline?.steps?.[key]?.status)}</strong></li>)}</ul></details><p className="pipeline-footnote">Scheduler: {status.data.scheduler.status === 'running' ? 'đang hoạt động' : status.data.scheduler.status === 'stale' ? 'heartbeat đã cũ' : 'chưa chạy'}{status.data.scheduler.heartbeat_at ? ` · ${new Date(status.data.scheduler.heartbeat_at).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh' })}` : ''}. Giao diện chỉ đọc trạng thái.</p></> : <p className="quiet-empty">{status.loading ? 'Đang đọc trạng thái…' : 'Chưa đọc được trạng thái cập nhật.'}</p>}</section>
        </aside>
      </div>
    </>}
  </div>
}
