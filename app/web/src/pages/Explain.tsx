import { ArrowDown, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type PathResult, type SearchHit } from '../api'
import { EntitySearch } from '../components/EntitySearch'
import { Card, ErrorBox, Loading, PageHeader, TypeBadge } from '../components/ui'
import { RELATION_LABEL } from '../labels'

const RELATIONS = Object.entries(RELATION_LABEL)

export function ExplainPage() {
  const [a, setA] = useState<SearchHit | null>(null)
  const [b, setB] = useState<SearchHit | null>(null)
  const [hops, setHops] = useState(3)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [relationTypes, setRelationTypes] = useState<string[]>([])
  const [res, setRes] = useState<{ data?: PathResult; error?: unknown; loading?: boolean }>({})

  const run = () => {
    if (!a || !b) return
    setRes({ loading: true })
    api.explain({ source: a.id, target: b.id, max_hops: hops, relation_types: relationTypes.length ? relationTypes : undefined, date_from: dateFrom || undefined, date_to: dateTo || undefined }).then((data) => setRes({ data }), (error) => setRes({ error }))
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Vì sao liên quan?" subtitle="Suy luận nhiều bước trên đồ thị: tìm chuỗi quan hệ ngắn nhất nối một thực thể trong tin với chủ đề bạn đang theo dõi, mỗi bước kèm câu bằng chứng." />
      <Card>
        <div className="grid items-end gap-4 md:grid-cols-2 xl:grid-cols-[1fr_1fr_auto_auto_auto_auto]">
          <label className="text-xs font-medium text-slate-500">
            Thực thể trong tin
            <div className="mt-1">
              <EntitySearch onSelect={setA} placeholder="VD: Phúc Du" />
            </div>
          </label>
          <label className="text-xs font-medium text-slate-500">
            Chủ đề đang theo dõi
            <div className="mt-1">
              <EntitySearch onSelect={setB} placeholder="VD: HOÀNG DŨNG" />
            </div>
          </label>
          <label className="text-xs font-medium text-slate-500">
            Tối đa
            <select value={hops} onChange={(e) => setHops(Number(e.target.value))} className="mt-1 block rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
              {[1, 2, 3].map((h) => (
                <option key={h} value={h}>
                  {h} bước
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-slate-500">Từ ngày<input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="mt-1 block w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm" /></label>
          <label className="text-xs font-medium text-slate-500">Đến ngày<input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="mt-1 block w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm" /></label>
          <button type="button" disabled={!a || !b} onClick={run} className="rounded-xl bg-brand-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-700 disabled:opacity-40">
            Tìm đường nối
          </button>
        </div>
      </Card>

      <details className="rounded-lg border border-slate-200 bg-white px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium text-slate-700">Lọc loại quan hệ {relationTypes.length ? `(${relationTypes.length})` : '(tất cả)'}</summary>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{RELATIONS.map(([key, label]) => <label key={key} className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={!relationTypes.length || relationTypes.includes(key)} onChange={(e) => setRelationTypes((current) => {
          const selected = relationTypes.length ? current : RELATIONS.map(([type]) => type)
          const next = e.target.checked ? [...selected, key] : selected.filter((type) => type !== key)
          return next.length === RELATIONS.length ? [] : next
        })} />{label}</label>)}</div>
      </details>

      {res.loading && <Loading label="Đang suy luận trên đồ thị…" />}
      {res.error ? <ErrorBox error={res.error} /> : null}
      {res.data && !res.data.found && <Card>Không tìm thấy đường nối trong {hops} bước.</Card>}
      {res.data?.found && (
        <Card title={`Liên quan qua ${res.data.hops} bước`} subtitle="Đọc từ trên xuống; mỗi mũi tên là một quan hệ có nguồn">
          <ol className="space-y-1">
            {res.data.nodes.map((n, i) => {
              const edge = res.data!.edges[i]
              const name = (id: string) => res.data!.nodes.find((x) => x.id === id)?.name ?? id
              return (
                <li key={n.id}>
                  <div className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
                    <TypeBadge type={n.type} />
                    <Link to={`/entity/${n.id}`} className="font-semibold text-slate-900 hover:text-brand-600">
                      {n.name}
                    </Link>
                  </div>
                  {edge && (
                    <div className="ml-6 flex gap-3 border-l-2 border-brand-100 py-2 pl-5">
                      <ArrowDown className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" />
                      <div className="text-sm">
                        <div className="text-slate-700">
                          {name(edge.source)} <span className="font-semibold text-brand-700">{RELATION_LABEL[edge.relation] ?? edge.relation}</span> {name(edge.target)}
                        </div>
                        {(edge.evidence ?? (edge.quote ? [{ quote: edge.quote, url: edge.url ?? '', title: edge.source_name ?? 'nguồn', source: edge.source_name ?? 'nguồn', published_at: '' }] : [])).map((ev, index) => <div key={`${edge.relation_id}-${index}`}><p className="mt-1 text-slate-600">“{ev.quote}”</p>{ev.url && <a href={ev.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs text-brand-600 hover:underline">{ev.source || ev.title || 'nguồn'} <ExternalLink className="h-3 w-3" /></a>}</div>)}
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ol>
        </Card>
      )}
    </div>
  )
}
