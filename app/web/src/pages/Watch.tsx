import { Bell, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import { EntitySearch } from '../components/EntitySearch'
import { Card, ErrorBox, Loading, PageHeader } from '../components/ui'
import { useAsync } from '../hooks'
import type { SearchHit } from '../api'

const EVENT_TYPES = [
  ['new_mentions', 'Tin mới'],
  ['collaboration', 'Hợp tác'],
  ['release', 'Phát hành'],
  ['show', 'Biểu diễn / chương trình'],
  ['dispute', 'Tranh chấp'],
] as const
const KIND_LABEL: Record<string, string> = Object.fromEntries(EVENT_TYPES)

export function WatchPage() {
  const [selected, setSelected] = useState<SearchHit | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [error, setError] = useState<unknown>()
  const [scopeSteps, setScopeSteps] = useState(1)
  const [eventTypes, setEventTypes] = useState<string[]>([])
  const watched = useAsync(() => api.watchlists(), [refreshKey])
  const alerts = useAsync(() => api.alerts(scopeSteps, eventTypes.length ? eventTypes : undefined), [refreshKey, scopeSteps, eventTypes.join('|')])
  const add = async () => {
    if (!selected) return
    setError(undefined)
    try { await api.addWatch(selected.id); setSelected(null); setRefreshKey((v) => v + 1) } catch (e) { setError(e) }
  }
  const remove = async (id: string) => {
    setError(undefined)
    try { await api.removeWatch(id); setRefreshKey((v) => v + 1) } catch (e) { setError(e) }
  }
  const toggleEvent = (value: string) => setEventTypes((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value])

  return <div className="watch-page">
    <PageHeader title="Theo dõi và cảnh báo" subtitle="Theo dõi thực thể và lần theo bằng chứng trong mạng lân cận. Đột biến chỉ được đánh dấu khi nhật ký xác nhận đủ 28 ngày thu thập." />
    <Card title="Thêm vào danh sách theo dõi" subtitle="Danh sách được lưu cục bộ trong Neo4j của máy này.">
      <div className="flex flex-wrap items-end gap-3"><div className="w-full max-w-lg"><EntitySearch onSelect={setSelected} placeholder="Tìm nghệ sĩ, công ty, chương trình…" /></div><div className="pb-2 text-sm text-slate-600">{selected?.name ?? 'Chưa chọn thực thể'}</div><button type="button" disabled={!selected} onClick={add} className="h-10 rounded-lg bg-slate-900 px-4 text-sm font-medium text-white disabled:opacity-40">Theo dõi</button></div>
    </Card>
    {error ? <ErrorBox error={error} /> : null}
    <section className="watch-filters" aria-label="Phạm vi cảnh báo">
      <label>Phạm vi theo dõi<select value={scopeSteps} onChange={(event) => setScopeSteps(Number(event.target.value))}><option value={1}>Thực thể trực tiếp · 1 bước</option><option value={2}>Hàng xóm · tối đa 2 bước</option></select></label>
      <fieldset><legend>Loại sự kiện</legend>{EVENT_TYPES.map(([value, label]) => <label key={value}><input type="checkbox" checked={eventTypes.includes(value)} onChange={() => toggleEvent(value)} />{label}</label>)}<small>{eventTypes.length ? 'Đang lọc theo loại đã chọn.' : 'Đang xem mọi loại sự kiện.'}</small></fieldset>
    </section>
    <div className="grid gap-6 xl:grid-cols-2">
      <Card title="Danh sách đang theo dõi" subtitle={`${watched.data?.length ?? 0} thực thể`}>
        {watched.loading ? <Loading /> : watched.error ? <ErrorBox error={watched.error} /> : !watched.data?.length ? <p className="text-sm text-slate-500">Chưa có thực thể. Tìm tên ở trên để bắt đầu theo dõi.</p> : <ul className="divide-y divide-slate-100">{watched.data.map((row) => <li key={row.entity_id} className="flex items-center justify-between gap-3 py-3"><div><div className="font-medium text-slate-800">{row.name}</div><div className="text-xs text-slate-500">{row.type} · {row.entity_id}</div></div><button type="button" onClick={() => remove(row.entity_id)} aria-label={`Bỏ theo dõi ${row.name}`} className="rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900"><Trash2 className="h-4 w-4" /></button></li>)}</ul>}
      </Card>
      <Card title="Cảnh báo 7 ngày" subtitle="Đột biến = z-score ≥ 2 so với 28 ngày trước; lịch sử lấy từ nhật ký pipeline, không suy ra từ ngày có bài.">
        {alerts.loading ? <Loading /> : alerts.error ? <ErrorBox error={alerts.error} /> : !alerts.data?.length ? <p className="text-sm text-slate-500">Không có tài liệu mới phù hợp với phạm vi và bộ lọc hiện tại.</p> : <ul className="divide-y divide-slate-100">{alerts.data.map((item) => <li key={item.entity_id} className="flex items-start gap-3 py-3"><Bell className={`mt-0.5 h-4 w-4 ${item.anomaly ? 'text-amber-700' : 'text-slate-400'}`} /><div className="min-w-0"><div className="text-sm font-medium text-slate-800">{item.name}: {item.count_7d} tài liệu · {KIND_LABEL[item.kind] ?? 'Tin mới'}</div><div className="text-xs text-slate-500">{item.anomaly ? `Đột biến · z=${item.z_score}` : item.requires_more_history ? 'Chưa đủ 28 ngày thu thập thành công để đánh dấu đột biến' : `Trung bình nền ${item.baseline_daily_mean}/ngày`} · phạm vi {item.scope_steps ?? scopeSteps} bước</div>{item.sources?.length ? <ul className="mt-2 grid gap-2">{item.sources.map((source) => <li key={source.evidence_id} className="rounded-md border border-slate-100 px-2 py-2"><div className="text-xs text-slate-600">{(source.path ?? [item.name, source.related_name]).join(' → ')} · {source.relation} · {source.distance ?? 1} bước</div>{source.published_at && <time className="text-[10px] text-slate-500">{source.published_at.slice(0, 10)}</time>}{source.quote && <blockquote className="my-1 text-xs text-slate-600">“{source.quote}”</blockquote>}{source.url && <a href={source.url} target="_blank" rel="noreferrer" className="mt-1 block max-w-full truncate text-xs text-blue-700 underline underline-offset-2">{source.title || source.source || source.evidence_id}</a>}</li>)}</ul> : null}</div></li>)}</ul>}
      </Card>
    </div>
  </div>
}
