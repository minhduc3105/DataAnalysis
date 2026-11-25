import { useState } from 'react'
import { api } from '../api'
import { EChart } from '../components/EChart'
import { EntitySearch } from '../components/EntitySearch'
import { Card, ErrorBox, Loading, PageHeader } from '../components/ui'
import { useAsync } from '../hooks'
import type { SearchHit } from '../api'

export function TrendsPage() {
  const [days, setDays] = useState(30)
  const [source, setSource] = useState('')
  const [entity, setEntity] = useState<SearchHit | null>(null)
  const data = useAsync(() => api.trends(days, entity?.id, source || undefined), [days, entity?.id, source])
  const option = {
    color: ['#1d5fbf'],
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 16, top: 20, bottom: 34 },
    xAxis: { type: 'category', data: (data.data?.daily ?? []).map((r) => r.date.slice(5)), axisLabel: { color: '#64748b' } },
    yAxis: { type: 'value', minInterval: 1, name: 'Bài có bằng chứng', nameTextStyle: { color: '#64748b' }, splitLine: { lineStyle: { color: '#e8ebef' } } },
    series: [{ type: 'line', data: (data.data?.daily ?? []).map((r) => r.documents), showSymbol: false, lineStyle: { width: 2 } }],
  }
  return (
    <div className="space-y-6">
      <PageHeader title="Xu hướng" subtitle="Số bài có bằng chứng theo ngày và thực thể được nhắc trong các quan hệ đã duyệt." />
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs text-slate-500">Khoảng xem<select value={days} onChange={(e) => setDays(Number(e.target.value))} className="mt-1 block h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-800"><option value={30}>30 ngày</option><option value={90}>90 ngày</option><option value={180}>180 ngày</option><option value={365}>365 ngày</option></select></label>
        <label className="text-xs text-slate-500">Nguồn chứa tên<input value={source} onChange={(e) => setSource(e.target.value)} placeholder="Mọi nguồn" className="mt-1 block h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-800" /></label>
        <div className="w-full max-w-sm"><EntitySearch onSelect={setEntity} placeholder="Lọc theo thực thể" /></div>
        {entity && <button type="button" onClick={() => setEntity(null)} className="h-10 px-2 text-sm text-slate-600 underline">Xóa lọc: {entity.name}</button>}
      </div>
      {data.loading ? <Loading /> : data.error ? <ErrorBox error={data.error} /> : <>
        <div className="flex items-baseline gap-3"><span className="font-mono text-3xl text-slate-900">{data.data?.total_documents ?? 0}</span><span className="text-sm text-slate-500">bài trong {days} ngày</span></div>
        <Card title="Nhịp tin có bằng chứng" subtitle="Mỗi điểm là số tài liệu khác nhau trong ngày."><EChart option={option} height={300} /></Card>
        <Card title="Thực thể xuất hiện nhiều" subtitle="Đếm tài liệu có ít nhất một bằng chứng gắn với thực thể.">
          {!data.data?.top_entities.length ? <p className="text-sm text-slate-500">Chưa có dữ liệu trong khoảng này.</p> : <ol className="grid gap-x-8 md:grid-cols-2">{data.data.top_entities.map((row, i) => <li key={row.name} className="flex justify-between border-t border-slate-100 py-2 text-sm"><span className="truncate pr-4"><span className="mr-3 font-mono text-xs text-slate-400">{i + 1}</span>{row.name}</span><span className="font-mono tabular-nums text-slate-600">{row.documents}</span></li>)}</ol>}
        </Card>
      </>}
    </div>
  )
}
