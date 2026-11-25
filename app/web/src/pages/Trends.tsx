import { ArrowRight, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { SearchHit } from '../api'
import { EChart } from '../components/EChart'
import { EntitySearch } from '../components/EntitySearch'
import { Card, ErrorBox, Loading, PageHeader } from '../components/ui'
import { useAsync } from '../hooks'
import { fmt } from '../labels'

const TOPIC_CHOICES = ['phát hành', 'hợp tác', 'biểu diễn', 'chương trình', 'doanh nghiệp', 'thương hiệu', 'tranh chấp', 'khác', 'phát hành và tác phẩm', 'doanh nghiệp và thương hiệu']
const SENTIMENT_CHOICES = ['tích cực', 'trung tính', 'tiêu cực', 'hỗn hợp', 'chưa xác định']

export function TrendsPage() {
  const [days, setDays] = useState(30)
  const [source, setSource] = useState('')
  const [entity, setEntity] = useState<SearchHit | null>(null)
  const [topic, setTopic] = useState('')
  const [community, setCommunity] = useState('')
  const [sentiment, setSentiment] = useState('')
  const data = useAsync(() => api.trends(days, entity?.id, source || undefined, community || undefined, topic || undefined, sentiment || undefined), [days, entity?.id, source, community, topic, sentiment])
  const result = data.data
  const chartOption = useMemo(() => {
    const start = result?.period?.from ?? '2000-01-01'
    const prevStart = result?.period?.previous_from ?? '1999-12-01'
    const currentMap = new Map((result?.daily ?? []).map((r) => [r.date, r.documents]))
    const previousMap = new Map((result?.previous_daily ?? []).map((r) => [r.date, r.documents]))
    const dayAt = (base: string, index: number) => { const [year, month, day] = base.split('-').map(Number); return new Date(Date.UTC(year, month - 1, day + index)).toISOString().slice(0, 10) }
    const labels = Array.from({ length: days }, (_, i) => i)
    return {
      color: ['#16866b', '#9ba9a2'],
      tooltip: { trigger: 'axis' },
      legend: { top: 0, right: 4, textStyle: { color: '#66736e', fontSize: 11 } },
      grid: { left: 40, right: 16, top: 34, bottom: 34 },
      xAxis: { type: 'category', data: labels.map((i) => i % Math.max(1, Math.ceil(days / 7)) === 0 || i === days - 1 ? String(i + 1) : ''), name: 'Ngày trong kỳ', nameLocation: 'middle', nameGap: 25, axisLabel: { color: '#66736e' }, axisTick: { show: false } },
      yAxis: { type: 'value', minInterval: 1, name: 'Tài liệu', nameTextStyle: { color: '#66736e' }, axisLabel: { color: '#66736e' }, splitLine: { lineStyle: { color: '#e8eeeb' } } },
      series: [
        { name: 'Kỳ hiện tại', type: 'line', data: labels.map((i) => currentMap.get(dayAt(start, i)) ?? 0), showSymbol: false, lineStyle: { width: 2.5 } },
        { name: 'Kỳ trước', type: 'line', data: labels.map((i) => previousMap.get(dayAt(prevStart, i)) ?? 0), showSymbol: false, lineStyle: { width: 1.5, type: 'dashed' } },
      ],
    }
  }, [result, days])

  const comparison = result?.comparison
  const deltaLabel = comparison ? comparison.comparison === 'new' ? `Mới xuất hiện · +${fmt(comparison.delta)}` : `${comparison.delta > 0 ? '+' : ''}${fmt(comparison.delta)} tài liệu so với kỳ trước` : 'Chưa có kỳ so sánh'
  const coverageNote = result?.coverage?.status === 'complete' ? 'Nhật ký xác nhận đủ độ phủ cho cả hai kỳ; kết quả vẫn chỉ mô tả tập nguồn thu thập.' : `Chưa đủ độ phủ để kết luận xu hướng. Nhật ký: kỳ này ${result?.coverage?.current_days ?? 0}/${days} ngày, kỳ trước ${result?.coverage?.previous_days ?? 0}/${days} ngày.`

  return <div className="trends-page">
    <PageHeader title="Xu hướng" subtitle="Theo dõi nhịp tài liệu, thực thể và cộng đồng trong dữ liệu đã thu thập." />
    <section className="trend-filters" aria-label="Bộ lọc xu hướng">
      <label>Khoảng xem<select value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={7}>7 ngày</option><option value={30}>30 ngày</option><option value={90}>90 ngày</option></select></label>
      <label className="trend-source">Nguồn chứa tên<input value={source} onChange={(e) => setSource(e.target.value)} placeholder="Báo, kênh hoặc nền tảng" /></label>
      <div className="trend-entity"><span>Thực thể</span><EntitySearch key={entity?.id ?? 'none'} initialValue={entity?.name ?? ''} onSelect={setEntity} placeholder="Lọc theo nghệ sĩ…" /></div>
      <label>Chủ đề<select value={topic} onChange={(e) => setTopic(e.target.value)}><option value="">Mọi chủ đề quan hệ</option>{TOPIC_CHOICES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      <label>Sắc thái nguồn<select value={sentiment} onChange={(e) => setSentiment(e.target.value)}><option value="">Mọi sắc thái</option>{SENTIMENT_CHOICES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      <label>Cộng đồng<select value={community} onChange={(e) => setCommunity(e.target.value)}><option value="">Mọi cộng đồng</option>{(result?.top_communities ?? []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {(entity || topic || community || sentiment || source) && <button className="trend-clear" onClick={() => { setEntity(null); setTopic(''); setCommunity(''); setSentiment(''); setSource('') }}><Search size={14} /> Xóa bộ lọc</button>}
    </section>
    {data.loading ? <Loading label="Đang đối chiếu các kỳ…" /> : data.error ? <ErrorBox error={data.error} /> : result && <>
      <section className="trend-result-summary"><div><strong>{fmt(result.total_documents)}</strong><span>tài liệu trong {days} ngày</span></div><div><strong>{deltaLabel}</strong><span>{comparison?.previous ?? 0} trong kỳ liền trước</span></div><p>{coverageNote}</p></section>
      <Card title="Nhịp tin theo ngày" subtitle="Các điểm được căn theo thứ tự ngày trong mỗi kỳ; tài liệu tính một lần theo ID."><EChart option={chartOption} height={280} /></Card>
      <div className="trend-detail-grid">
        <Card title="Thực thể xuất hiện nhiều" subtitle="Đếm số tài liệu có ít nhất một bằng chứng gắn với thực thể.">{result.top_entities.length ? <ol className="trend-ranked-list">{result.top_entities.slice(0, 10).map((row, i) => <li key={row.id}><span className="trend-rank">{String(i + 1).padStart(2, '0')}</span><Link to={`/entity/${encodeURIComponent(row.id)}`}>{row.name}</Link><strong>{fmt(row.documents)}</strong></li>)}</ol> : <p className="quiet-empty">Không có thực thể trong bộ lọc này.</p>}</Card>
        <Card title="Cộng đồng được nhắc" subtitle="Gắn theo snapshot phân tích hiện tại; thành phần cộng đồng không được tính lại theo tuần.">{result.top_communities?.length ? <ol className="trend-ranked-list">{result.top_communities.slice(0, 10).map((row, i) => <li key={row.id}><span className="trend-rank">{String(i + 1).padStart(2, '0')}</span><span className="trend-community-name">{row.name}<small>{fmt(row.size)} nghệ sĩ trong snapshot</small></span><strong>{fmt(row.documents)}</strong></li>)}</ol> : <p className="quiet-empty">Chưa có liên kết giữa lượt nhắc và snapshot cộng đồng.</p>}</Card>
        <Card title="Chủ đề tài liệu" subtitle="Gồm nhãn bộ phân loại và nhóm suy ra từ quan hệ đã duyệt.">{result.topics?.length ? <ol className="trend-ranked-list">{result.topics.map((row) => <li key={row.topic}><span className="trend-rank">·</span><span>{row.topic}</span><strong>{fmt(row.documents)}</strong></li>)}</ol> : <p className="quiet-empty">Chưa có chủ đề khả dụng trong bộ lọc này.</p>}</Card>
        <Card title="Sắc thái nội dung" subtitle="Mô tả nội dung nguồn, không đại diện cảm xúc công chúng.">{result.sentiment?.length ? <ol className="trend-ranked-list">{result.sentiment.map((row) => <li key={row.sentiment}><span className="trend-rank">·</span><span>{row.sentiment}</span><strong>{fmt(row.documents)}</strong></li>)}</ol> : <p className="quiet-empty">{result.classification_status?.status === 'not_configured' ? 'Dịch vụ mô hình chưa được cấu hình.' : 'Chưa có kết quả phân loại sắc thái cho tài liệu.'}</p>}</Card>
      </div>
      <div className="trend-footer"><span>Kỳ: {result.period?.from ?? '—'} — {result.period?.to ?? '—'} · dữ liệu phân tích có thể chưa đồng bộ với luồng tin.</span><Link to="/network">Mở snapshot mạng <ArrowRight size={14} /></Link></div>
    </>}
  </div>
}
