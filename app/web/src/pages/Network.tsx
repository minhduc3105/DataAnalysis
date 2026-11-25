import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Row } from '../api'
import { Card, Chip, ErrorBox, Loading, PageHeader, Stat } from '../components/ui'
import { EChart } from '../components/EChart'
import { useAsync } from '../hooks'
import { fmt } from '../labels'

const MEASURES = [
  { key: 'pagerank', label: 'PageRank' },
  { key: 'degree', label: 'Số cộng sự' },
  { key: 'betweenness', label: 'Cầu nối' },
  { key: 'eigenvector', label: 'Eigenvector' },
]
const ROLES = ['', 'Ca sĩ/rapper', 'Nhạc sĩ', 'Producer']

const metric = (rows: Row[] | undefined, prefix: string) => rows?.find((r) => String(r.metric).startsWith(prefix))?.value as number | undefined

export function NetworkPage() {
  const snapshots = useAsync(api.snapshots, [])
  const [graphVersion, setGraphVersion] = useState('')
  const selectedVersion = graphVersion || undefined
  const net = useAsync(() => api.network(selectedVersion), [selectedVersion])
  const comms = useAsync(() => api.communities(selectedVersion), [selectedVersion])
  const [measure, setMeasure] = useState('pagerank')
  const [role, setRole] = useState('')
  const ranks = useAsync(() => api.rankings(measure, role || undefined, 20, selectedVersion), [measure, role, selectedVersion])

  const sw = net.data?.small_world
  const overview = net.data?.overview
  const collab = net.data?.collab_summary?.[0]
  const louvain = net.data?.community_methods?.find((r) => r.method === 'Louvain')

  const distOption = useMemo(() => {
    const rows = net.data?.distance_distribution ?? []
    const cum = rows.reduce<[number, number[]]>(([total, values], row) => {
      const next = total + Number(row.share)
      return [next, [...values, next * 100]]
    }, [0, []])[1]
    return {
      tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v.toFixed(1)}%` },
      legend: { bottom: 0, itemWidth: 12, textStyle: { fontSize: 11 } },
      grid: { left: 44, right: 44, top: 16, bottom: 48 },
      xAxis: { type: 'category', data: rows.map((r) => `${r.distance} bước`) },
      yAxis: [
        { type: 'value', axisLabel: { formatter: '{value}%' }, splitLine: { lineStyle: { color: '#f1f5f9' } } },
        { type: 'value', max: 100, axisLabel: { formatter: '{value}%' }, splitLine: { show: false } },
      ],
      series: [
        { name: 'Tỉ lệ cặp nghệ sĩ', type: 'bar', data: rows.map((r) => Number(r.share) * 100), itemStyle: { color: '#6366f1', borderRadius: [6, 6, 0, 0] }, barWidth: '55%' },
        { name: 'Cộng dồn', type: 'line', yAxisIndex: 1, data: cum, smooth: true, symbolSize: 6, itemStyle: { color: '#f59e0b' } },
      ],
    }
  }, [net.data])

  const kcoreOption = useMemo(() => {
    const rows = net.data?.kcore_distribution ?? []
    return {
      tooltip: { trigger: 'axis' },
      grid: { left: 40, right: 12, top: 12, bottom: 32 },
      xAxis: { type: 'category', data: rows.map((r) => `k=${r.k}`) },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#f1f5f9' } } },
      series: [{ type: 'bar', data: rows.map((r) => r.n_nodes), itemStyle: { color: (p: { dataIndex: number }) => (p.dataIndex === rows.length - 1 ? '#4f46e5' : '#c7d2fe'), borderRadius: [4, 4, 0, 0] } }],
    }
  }, [net.data])

  if (net.error) return <ErrorBox error={net.error} />
  if (net.loading || !net.data) return <Loading />

  const L = metric(sw, 'Khoảng cách ngắn nhất trung bình')
  const C = metric(sw, 'Hệ số gom cụm trung bình')
  const compare = [
    { label: 'Mạng thật', L, C },
    { label: 'Ngẫu nhiên Erdős–Rényi', L: metric(sw, 'L ngẫu nhiên Erdős'), C: metric(sw, 'C ngẫu nhiên Erdős') },
    { label: 'Ngẫu nhiên giữ bậc', L: metric(sw, 'L ngẫu nhiên giữ'), C: metric(sw, 'C ngẫu nhiên giữ') },
  ]
  const kmax = net.data.kcore_distribution?.at(-1)
  const periods = [...new Set(net.data.pagerank_by_period.map((r) => String(r.period)))]
  const fullRanks = net.data.pagerank_song_company ?? []

  return (
    <div className="space-y-6">
      <PageHeader title="Chân dung mạng" subtitle="Cấu trúc mạng hợp tác ca sĩ, nhạc sĩ, producer Việt Nam: thế giới nhỏ, xếp hạng nút, cộng đồng và hạt nhân. Số liệu từ đồ thị tri thức trên Neo4j." />

      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <label>Snapshot đồ thị
          <select value={graphVersion} onChange={(e) => setGraphVersion(e.target.value)} className="ml-2 h-9 rounded-lg border border-slate-300 bg-white px-2 text-sm text-slate-800">
            <option value="">Mới nhất</option>
            {(snapshots.data ?? []).map((snapshot) => <option key={snapshot.graph_version} value={snapshot.graph_version}>{snapshot.graph_version} · {snapshot.generated_at?.slice(0, 10)}</option>)}
          </select>
        </label>
        {net.data?.overview?.length ? <span>{String(net.data.overview.find((row) => row.metric === 'Nút thực thể')?.value ?? '')} nút · graph {graphVersion || snapshots.data?.[0]?.graph_version || 'latest'}</span> : null}
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4 xl:grid-cols-6">
        <Stat label="Nút thực thể" value={fmt(metric(overview, 'Nút thực thể'))} hint="toàn đồ thị tri thức" />
        <Stat label="Cạnh có bằng chứng" value={fmt(metric(overview, 'Cạnh nghiệp vụ'))} hint={`${fmt(metric(overview, 'Loại quan hệ'))} loại quan hệ`} />
        <Stat label="Nghệ sĩ trong mạng hợp tác" value={fmt(collab?.nodes)} hint={`${fmt(collab?.edges)} cặp hợp tác`} />
        <Stat label="Khoảng cách trung bình" value={fmt(L, 2)} hint="bước giữa hai nghệ sĩ bất kỳ" accent />
        <Stat label="σ thế giới nhỏ" value={fmt(metric(sw, 'σ so với đồ thị giữ'), 1)} hint="> 1 là thế giới nhỏ" accent />
        <Stat label="Modularity (Louvain)" value={fmt(louvain?.modularity, 3)} hint={`${fmt(louvain?.communities)} cộng đồng`} />
      </div>

      <div className="grid gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3" title="Ai cũng chỉ cách nhau vài bước" subtitle="Phân phối khoảng cách ngắn nhất giữa mọi cặp nghệ sĩ trong thành phần liên thông lớn nhất">
          <EChart option={distOption} height={300} />
        </Card>
        <Card className="xl:col-span-2" title="So với mạng ngẫu nhiên cùng quy mô" subtitle="Ngắn như mạng ngẫu nhiên nhưng gom cụm cao hơn hàng chục lần">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="pb-2 font-medium" />
                <th className="pb-2 text-right font-medium">L</th>
                <th className="pb-2 text-right font-medium">C</th>
              </tr>
            </thead>
            <tbody>
              {compare.map((r, i) => (
                <tr key={r.label} className="border-t border-slate-100">
                  <td className={`py-2 ${i === 0 ? 'font-semibold text-slate-900' : 'text-slate-600'}`}>{r.label}</td>
                  <td className="py-2 text-right tabular-nums">{fmt(r.L, 2)}</td>
                  <td className="py-2 text-right tabular-nums">{fmt(r.C, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-4 grid grid-cols-3 gap-3 text-center">
            {[
              ['σ (Erdős–Rényi)', metric(sw, 'σ so với Erdős'), 1],
              ['ω', metric(sw, 'ω'), 2],
              ['Đường kính', metric(sw, 'Đường kính'), 0],
            ].map(([label, v, d]) => (
              <div key={label as string} className="rounded-xl bg-slate-50 py-3">
                <div className="text-lg font-semibold tabular-nums text-slate-900">{fmt(v, d as number)}</div>
                <div className="text-xs text-slate-500">{label}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        {(['Company', 'Song'] as const).map((kind) => <Card key={kind} title={kind === 'Company' ? 'Công ty theo PageRank' : 'Bài hát theo PageRank'} subtitle="Xếp hạng trên đồ thị tri thức đầy đủ, không chỉ mạng cộng tác nghệ sĩ.">
          <ol className="divide-y divide-slate-100">{fullRanks.filter((row) => row.entity_type === kind).slice(0, 10).map((row, index) => <li key={String(row.entity_id)} className="flex items-center justify-between gap-3 py-2 text-sm"><span className="truncate"><span className="mr-3 font-mono text-xs text-slate-400">{index + 1}</span><Link to={`/entity/${row.entity_id}`} className="font-medium text-slate-800 hover:text-brand-600">{row.name}</Link></span><span className="font-mono text-xs tabular-nums text-slate-500">{fmt(row.pagerank, 4)}</span></li>)}</ol>
          {!fullRanks.some((row) => row.entity_type === kind) && <p className="text-sm text-slate-500">Chưa có dữ liệu cho loại nút này.</p>}
        </Card>)}
      </div>

      <div className="grid gap-6 xl:grid-cols-5">
        <Card
          className="xl:col-span-3"
          title="Xếp hạng nút"
          subtitle="Mỗi thước đo trả lời một câu hỏi khác: ảnh hưởng, độ rộng quan hệ hay vai trò cầu nối"
          action={
            <div className="flex flex-wrap justify-end gap-1.5">
              {MEASURES.map((m) => (
                <Chip key={m.key} active={measure === m.key} onClick={() => setMeasure(m.key)}>
                  {m.label}
                </Chip>
              ))}
            </div>
          }
        >
          <div className="mb-3 flex flex-wrap gap-1.5">
            {ROLES.map((r) => (
              <Chip key={r || 'all'} active={role === r} onClick={() => setRole(r)}>
                {r || 'Mọi vai trò'}
              </Chip>
            ))}
          </div>
          {ranks.loading ? (
            <Loading />
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {(ranks.data ?? []).map((r, i) => {
                  const max = Number(ranks.data?.[0]?.[measure] ?? 1)
                  return (
                    <tr key={String(r.entity_id)} className="border-t border-slate-100">
                      <td className="w-8 py-2 text-xs tabular-nums text-slate-400">{i + 1}</td>
                      <td className="py-2">
                        <Link to={`/entity/${r.entity_id}`} className="font-medium text-slate-800 hover:text-brand-600">
                          {r.name}
                        </Link>
                        <div className="text-xs text-slate-400">
                          {r.main_role} · cộng đồng {r.community} · lõi k={r.core}
                        </div>
                      </td>
                      <td className="w-2/5 py-2">
                        <div className="flex items-center gap-2">
                          <div className="h-2 flex-1 rounded-full bg-slate-100">
                            <div className="h-2 rounded-full bg-brand-500" style={{ width: `${(Number(r[measure]) / max) * 100}%` }} />
                          </div>
                          <span className="w-16 text-right text-xs tabular-nums text-slate-600">{fmt(r[measure], measure === 'degree' ? 0 : 2)}</span>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </Card>
        <div className="space-y-6 xl:col-span-2">
          <Card title="Hạt nhân k-core" subtitle={`Lõi cứng nhất: k = ${kmax?.k}, gồm ${kmax?.n_nodes} nghệ sĩ`}>
            <EChart option={kcoreOption} height={200} />
          </Card>
          <Card title="Người dẫn đầu theo giai đoạn" subtitle="Top 3 PageRank trong mạng hợp tác của từng giai đoạn">
            <div className="grid grid-cols-2 gap-3">
              {periods.map((p) => (
                <div key={p} className="rounded-xl bg-slate-50 p-3">
                  <div className="text-xs font-semibold text-brand-700">{p}</div>
                  <ol className="mt-1 space-y-0.5 text-sm">
                    {net.data!.pagerank_by_period
                      .filter((r) => r.period === p && Number(r.rank) <= 3)
                      .map((r) => (
                        <li key={String(r.name)} className="truncate text-slate-700">
                          {r.rank}. {r.name}
                        </li>
                      ))}
                  </ol>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>

      <Card title="Cộng đồng và hạt nhân của từng cộng đồng" subtitle="Louvain trên mạng hợp tác có trọng số; hạt nhân = thành viên thuộc lõi k lớn nhất của cộng đồng">
        {comms.loading ? (
          <Loading />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {(comms.data ?? [])
              .filter((c) => Number(c.size) >= 20)
              .map((c) => (
                <div key={String(c.community)} className="rounded-xl border border-slate-200 p-4">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold text-slate-900">Cộng đồng {c.community}</div>
                    <div className="text-xs text-slate-500">{c.size} nghệ sĩ</div>
                  </div>
                  <div className="mt-0.5 text-xs text-slate-500">{c.main_genre || 'chưa rõ dòng nhạc'}</div>
                  <div className="mt-3 text-xs font-medium text-slate-500">Hạt nhân (k={c.max_core_in_community ?? '–'})</div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {String(c.nucleus ?? c.top_members ?? '')
                      .split('; ')
                      .filter(Boolean)
                      .slice(0, 8)
                      .map((n) => (
                        <span key={n} className="rounded-full bg-brand-50 px-2 py-0.5 text-xs text-brand-700">
                          {n}
                        </span>
                      ))}
                  </div>
                  {c.top_companies && <div className="mt-3 truncate text-xs text-slate-500">Công ty: {String(c.top_companies).split('; ').slice(0, 3).join(', ')}</div>}
                  {c.summary && <p className="mt-3 border-t border-slate-100 pt-3 text-sm leading-5 text-slate-700">{String(c.summary)}</p>}
                  {Array.isArray(c.summary_sources) && c.summary_sources.length > 0 && <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">{(c.summary_sources as { source_id: string; title?: string; url?: string }[]).map((source) => source.url ? <a key={source.source_id} href={source.url} target="_blank" rel="noreferrer" className="max-w-48 truncate text-xs text-blue-700 underline underline-offset-2">{source.title || source.source_id}</a> : null)}</div>}
                </div>
              ))}
          </div>
        )}
      </Card>

      <Card title="Cầu nối giữa cộng đồng" subtitle="Cạnh liên cộng đồng xếp theo betweenness có trọng số nghịch đảo của trọng số hợp tác.">
        {!(net.data.community_bridges ?? []).length ? <p className="text-sm text-slate-500">Không có cạnh cầu nối trong snapshot này.</p> : <ol className="grid gap-x-8 md:grid-cols-2">{(net.data.community_bridges ?? []).slice(0, 20).map((row, index) => <li key={String(row.relation_id)} className="flex items-center justify-between gap-3 border-t border-slate-100 py-2 text-sm"><span className="min-w-0 truncate"><span className="mr-2 font-mono text-xs text-slate-400">{index + 1}</span><Link to={`/entity/${row.a}`} className="text-slate-800 hover:text-brand-600">{row.a_name}</Link><span className="px-1 text-slate-400">↔</span><Link to={`/entity/${row.b}`} className="text-slate-800 hover:text-brand-600">{row.b_name}</Link><span className="ml-2 text-xs text-slate-400">{row.community_a}–{row.community_b}</span></span><span className="shrink-0 font-mono text-xs text-slate-500">{fmt(row.edge_betweenness, 4)}</span></li>)}</ol>}
      </Card>

      <Card title="Đường nối giữa các dòng nhạc" subtitle="Đường đi ngắn nhất giữa nghệ sĩ có PageRank cao nhất của mỗi dòng nhạc">
        <ul className="divide-y divide-slate-100 text-sm">
          {net.data.small_world_paths.map((p, i) => (
            <li key={i} className="flex flex-wrap items-center gap-2 py-2">
              <span className="w-14 shrink-0 text-xs text-slate-400">{p.hops} bước</span>
              <span className="text-slate-700">{p.path}</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
