import { ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type Neighbor } from '../api'
import { EgoGraph } from '../components/EgoGraph'
import { Card, ErrorBox, Loading, PageHeader, Stat, TypeBadge } from '../components/ui'
import { useAsync } from '../hooks'
import { RELATION_LABEL, fmt } from '../labels'

export function EntityPage() {
  const { id = '' } = useParams()
  const ent = useAsync(() => api.entity(id, 60), [id])
  const [picked, setPicked] = useState<Neighbor | null>(null)
  const ev = useAsync(() => (picked ? api.evidence(picked.relation_id) : Promise.resolve([])), [picked?.relation_id])

  if (ent.error) return <ErrorBox error={ent.error} />
  if (ent.loading || !ent.data) return <Loading />
  const e = ent.data
  const p = e.props

  return (
    <div className="space-y-6">
      <PageHeader title={e.name} subtitle={(p.aliases as unknown as string[] | undefined)?.slice(0, 6).join(' · ')}>
        <TypeBadge type={e.type} />
      </PageHeader>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="Liên kết" value={fmt(e.relation_counts.reduce((s, r) => s + r.n, 0))} />
        <Stat label="PageRank" value={fmt(p.pagerank, 2)} hint="trong mạng hợp tác" />
        <Stat label="Cộng đồng" value={fmt(p.community)} />
        <Stat label="Lõi k-core" value={fmt(p.core)} />
        <Stat label="Tài liệu nhắc đến" value={fmt(p.n_documents)} />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Mạng quanh thực thể" subtitle="Bấm vào một nút hoặc cạnh để xem bằng chứng; kích thước theo PageRank">
          <EgoGraph center={e} neighbors={e.neighbors} onSelect={setPicked} />
          <div className="mt-3 flex flex-wrap gap-1.5">
            {e.relation_counts.map((r) => (
              <span key={r.relation} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-600">
                {RELATION_LABEL[r.relation] ?? r.relation}: <b className="tabular-nums">{r.n}</b>
              </span>
            ))}
          </div>
        </Card>
        <Card title="Bằng chứng" subtitle={picked ? `${e.name} — ${RELATION_LABEL[picked.relation] ?? picked.relation} — ${picked.name}` : 'Chọn một liên kết trên đồ thị'}>
          {!picked ? (
            <div className="text-sm text-slate-400">Mỗi cạnh trong đồ thị đều truy được về câu gốc trong bài báo, mô tả video hoặc dữ liệu Spotify.</div>
          ) : ev.loading ? (
            <Loading />
          ) : (
            <ul className="space-y-3">
              {(ev.data ?? []).map((x, i) => (
                <li key={i} className="rounded-xl bg-slate-50 p-3 text-sm">
                  <p className="text-slate-700">“{x.quote}”</p>
                  <a href={x.url} target="_blank" rel="noreferrer" className="mt-2 flex items-center gap-1 text-xs text-brand-600 hover:underline">
                    {x.source} · {x.published_at?.slice(0, 10)} <ExternalLink className="h-3 w-3" />
                  </a>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card title="Liên kết nổi bật">
        <table className="w-full text-sm">
          <tbody>
            {e.neighbors.slice(0, 30).map((n, i) => (
              <tr key={i} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setPicked(n)}>
                <td className="py-2 text-slate-500">{RELATION_LABEL[n.relation] ?? n.relation}</td>
                <td className="py-2">
                  <Link to={`/entity/${n.id}`} onClick={(ev) => ev.stopPropagation()} className="font-medium text-slate-800 hover:text-brand-600">
                    {n.name}
                  </Link>
                </td>
                <td className="py-2">
                  <TypeBadge type={n.type} />
                </td>
                <td className="py-2 text-right text-xs tabular-nums text-slate-400">{n.first_year ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
