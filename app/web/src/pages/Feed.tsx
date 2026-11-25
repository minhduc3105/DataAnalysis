import { ExternalLink, Filter } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import type { SearchHit } from '../api'
import { EntitySearch } from '../components/EntitySearch'
import { Card, ErrorBox, Loading, PageHeader, TypeBadge } from '../components/ui'
import { useAsync } from '../hooks'
import { RELATION_LABEL } from '../labels'

export function FeedPage() {
  const [source, setSource] = useState('')
  const [entity, setEntity] = useState<SearchHit | null>(null)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const state = useAsync(() => api.feed({ entity_id: entity?.id, source: source || undefined, date_from: from || undefined, date_to: to || undefined, limit: 80 }), [source, from, to, entity?.id])

  return (
    <div className="space-y-6">
      <PageHeader title="Bảng tin" subtitle="Bài báo mới có quan hệ và câu bằng chứng đã được duyệt trong đồ thị." />
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-slate-500">Nguồn chứa tên<input value={source} onChange={(e) => setSource(e.target.value)} placeholder="VD: VnExpress" className="mt-1 block h-10 min-w-48 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-800" /></label>
          <label className="text-xs text-slate-500">Từ ngày<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="mt-1 block h-10 rounded-lg border border-slate-300 px-3 text-sm text-slate-800" /></label>
          <label className="text-xs text-slate-500">Đến ngày<input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="mt-1 block h-10 rounded-lg border border-slate-300 px-3 text-sm text-slate-800" /></label>
          <div className="w-full max-w-xs"><label className="text-xs text-slate-500">Thực thể</label><EntitySearch onSelect={setEntity} placeholder="Tìm và lọc theo thực thể" /></div>
          {entity && <button type="button" onClick={() => setEntity(null)} className="h-10 text-xs text-slate-600 underline">Bỏ lọc {entity.name}</button>}
          <div className="ml-auto flex items-center gap-2 pb-2 text-xs text-slate-500"><Filter className="h-4 w-4" />{state.data?.length ?? 0} bài trong kết quả</div>
        </div>
      </Card>
      {state.loading && <Loading label="Đang lấy bài có bằng chứng…" />}
      {state.error ? <ErrorBox error={state.error} /> : null}
      {!state.loading && state.data?.length === 0 && <Card title="Chưa có bài trong bộ lọc"><p className="text-sm text-slate-500">Bảng tin hiện chỉ hiển thị tài liệu đã có quan hệ được duyệt và câu bằng chứng trong Neo4j.</p></Card>}
      <div className="space-y-3">
        {(state.data ?? []).map((item) => (
          <article key={item.document_id} className="rounded-lg border border-slate-200 bg-white p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><div className="text-xs text-slate-500">{item.source || 'Nguồn chưa rõ'} · {item.published_at?.slice(0, 10) || 'ngày chưa rõ'}</div><h2 className="mt-1 text-base font-semibold text-slate-900">{item.title || item.document_id}</h2></div>
              {item.url && <a className="inline-flex items-center gap-1 text-sm text-blue-700 hover:underline" href={item.url} target="_blank" rel="noreferrer">Mở bài <ExternalLink className="h-3.5 w-3.5" /></a>}
            </div>
            <ul className="mt-4 divide-y divide-slate-100">
              {item.relations.slice(0, 4).map((r) => (
                <li key={`${r.relation_id}-${r.evidence}`} className="grid gap-2 py-3 md:grid-cols-[auto_1fr] md:items-start">
                  <TypeBadge type={RELATION_LABEL[r.relation] ?? r.relation} />
                  <div><div className="text-sm text-slate-800">{r.source} <span className="font-medium">{RELATION_LABEL[r.relation] ?? r.relation}</span> {r.target}</div><p className="mt-1 text-sm text-slate-600">“{r.evidence}”</p></div>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </div>
  )
}
