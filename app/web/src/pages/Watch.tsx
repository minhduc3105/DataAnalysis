import { Bell, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import { EntitySearch } from '../components/EntitySearch'
import { Card, ErrorBox, Loading, PageHeader } from '../components/ui'
import { useAsync } from '../hooks'
import type { SearchHit } from '../api'

export function WatchPage() {
  const [selected, setSelected] = useState<SearchHit | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [error, setError] = useState<unknown>()
  const watched = useAsync(() => api.watchlists(), [refreshKey])
  const alerts = useAsync(() => api.alerts(), [refreshKey])
  const add = async () => {
    if (!selected) return
    setError(undefined)
    try { await api.addWatch(selected.id); setSelected(null); setRefreshKey((v) => v + 1) } catch (e) { setError(e) }
  }
  const remove = async (id: string) => {
    setError(undefined)
    try { await api.removeWatch(id); setRefreshKey((v) => v + 1) } catch (e) { setError(e) }
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Theo dõi và cảnh báo" subtitle="Chọn thực thể trong đồ thị; cảnh báo đột biến chỉ xuất hiện khi có đủ 28 ngày để so sánh." />
      <Card title="Thêm vào danh sách theo dõi" subtitle="Danh sách lưu cục bộ trong Neo4j của máy này.">
        <div className="flex flex-wrap items-end gap-3"><div className="w-full max-w-lg"><EntitySearch onSelect={setSelected} placeholder="Tìm nghệ sĩ, công ty, chương trình…" /></div><div className="pb-2 text-sm text-slate-600">{selected?.name ?? 'Chưa chọn thực thể'}</div><button type="button" disabled={!selected} onClick={add} className="h-10 rounded-lg bg-slate-900 px-4 text-sm font-medium text-white disabled:opacity-40">Theo dõi</button></div>
      </Card>
      {error ? <ErrorBox error={error} /> : null}
      <div className="grid gap-6 xl:grid-cols-2">
        <Card title="Danh sách đang theo dõi" subtitle={`${watched.data?.length ?? 0} thực thể`}>
          {watched.loading ? <Loading /> : watched.error ? <ErrorBox error={watched.error} /> : !watched.data?.length ? <p className="text-sm text-slate-500">Chưa có thực thể. Tìm tên ở trên để bắt đầu theo dõi.</p> : <ul className="divide-y divide-slate-100">{watched.data.map((row) => <li key={row.entity_id} className="flex items-center justify-between gap-3 py-3"><div><div className="font-medium text-slate-800">{row.name}</div><div className="text-xs text-slate-500">{row.type} · {row.entity_id}</div></div><button type="button" onClick={() => remove(row.entity_id)} aria-label={`Bỏ theo dõi ${row.name}`} className="rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900"><Trash2 className="h-4 w-4" /></button></li>)}</ul>}
        </Card>
        <Card title="Cảnh báo 7 ngày" subtitle="Đột biến = z-score ≥ 2 so với 28 ngày trước; chưa đủ lịch sử thì chỉ hiện số bài.">
          {alerts.loading ? <Loading /> : alerts.error ? <ErrorBox error={alerts.error} /> : !alerts.data?.length ? <p className="text-sm text-slate-500">Chưa có bài mới gắn với các thực thể đang theo dõi.</p> : <ul className="divide-y divide-slate-100">{alerts.data.map((item) => <li key={item.entity_id} className="flex items-start gap-3 py-3"><Bell className={`mt-0.5 h-4 w-4 ${item.anomaly ? 'text-amber-700' : 'text-slate-400'}`} /><div><div className="text-sm font-medium text-slate-800">{item.name}: {item.count_7d} bài mới</div><div className="text-xs text-slate-500">{item.anomaly ? `Đột biến · z=${item.z_score}` : item.requires_more_history ? 'Chưa đủ 28 ngày dữ liệu để đánh dấu đột biến' : `Trung bình nền ${item.baseline_daily_mean}/ngày`}</div>{item.sources?.length ? <div className="mt-2 flex flex-wrap gap-2">{item.sources.map((source) => source.url && <a key={source.evidence_id} href={source.url} target="_blank" rel="noreferrer" className="max-w-56 truncate text-xs text-blue-700 underline underline-offset-2">{source.title || source.source || source.evidence_id}</a>)}</div> : null}</div></li>)}</ul>}
        </Card>
      </div>
    </div>
  )
}
