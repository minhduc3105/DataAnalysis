export type Row = Record<string, string | number | boolean | null>

export interface SearchHit {
  id: string
  name: string
  type: string
  degree: number
  pagerank: number | null
}

export interface Neighbor {
  id: string
  name: string
  type: string
  relation: string
  outgoing: boolean
  relation_id: string
  n_documents: number | null
  first_year: number | null
  weight: number | null
  pagerank: number | null
  community: number | null
}

export interface EntityDetail {
  id: string
  name: string
  type: string
  props: Row
  neighbors: Neighbor[]
  relation_counts: { relation: string; n: number }[]
}

export interface Evidence {
  quote: string
  location: string
  method: string
  confidence: number | null
  title: string
  url: string
  source: string
  platform: string
  published_at: string
}

export interface PathResult {
  found: boolean
  hops?: number
  nodes: { id: string; name: string; type: string }[]
  edges: { relation: string; relation_id: string; source: string; target: string; quote?: string | null; url?: string | null; source_name?: string | null; evidence?: { quote: string; url: string; title: string; source: string; published_at: string }[] }[]
}

export interface FeedItem {
  document_id: string
  title: string
  url: string
  source: string
  published_at: string
  platform: string
  relations: { relation: string; relation_id: string; source: string; target: string; evidence: string }[]
}

export interface WatchedEntity {
  entity_id: string
  name: string
  type: string
  pagerank?: number | null
}

export interface AlertItem {
  entity_id: string
  name: string
  kind: string
  count_7d: number
  baseline_daily_mean: number
  z_score: number | null
  anomaly: boolean
  requires_more_history: boolean
  sources?: { evidence_id: string; title: string; url: string; source: string; relation: string; related_name: string }[]
}

export interface TrendBundle {
  days: number
  daily: { date: string; documents: number }[]
  top_entities: { name: string; documents: number }[]
  total_documents: number
}

export interface AnalysisSnapshot {
  graph_version: string
  analysis_run_id: string
  generated_at: string
  graph_nodes: number
  graph_relations: number
  periods?: number[][]
}

export interface AnswerResult {
  status: string
  answer: string
  source_ids: string[]
  sources?: { source_id: string; text: string; url: string; title: string }[]
  retrieval?: Record<string, unknown>
}

export type NetworkBundle = Record<string, Row[]>

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)]))
  const res = await fetch(`/api${path}${qs.size ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
  return res.json()
}

export const api = {
  network: (graph_version?: string) => get<NetworkBundle>('/network', { graph_version }),
  snapshots: () => get<AnalysisSnapshot[]>('/analysis/snapshots'),
  rankings: (measure: string, role?: string, limit = 30, graph_version?: string) => get<Row[]>('/rankings', { measure, role, limit, graph_version }),
  communities: (graph_version?: string) => get<Row[]>('/communities', { graph_version }),
  search: (q: string) => get<SearchHit[]>('/search', { q }),
  entity: (id: string, limit = 60) => get<EntityDetail>(`/entity/${encodeURIComponent(id)}`, { limit }),
  evidence: (relationId: string) => get<Evidence[]>(`/evidence/${encodeURIComponent(relationId)}`),
  path: (source: string, target: string, maxHops = 3) => get<PathResult>('/path', { source, target, max_hops: maxHops }),
  feed: (params: { entity_id?: string; source?: string; date_from?: string; date_to?: string; limit?: number }) => get<FeedItem[]>('/feed', params),
  watchlists: () => get<WatchedEntity[]>('/watchlists'),
  alerts: () => get<AlertItem[]>('/alerts'),
  addWatch: async (entity_id: string) => {
    const res = await fetch('/api/watchlists', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ entity_id }) })
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
    return res.json() as Promise<WatchedEntity>
  },
  removeWatch: async (entity_id: string) => {
    const res = await fetch(`/api/watchlists/${encodeURIComponent(entity_id)}`, { method: 'DELETE' })
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
  },
  trends: (days = 30, entity_id?: string, source?: string) => get<TrendBundle>('/trends', { days, entity_id, source }),
  explain: (body: { source: string; target: string; max_hops: number; relation_types?: string[]; date_from?: string; date_to?: string }) =>
    fetch('/api/explain', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(async (res) => {
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
      return (await res.json()) as PathResult
    }),
  ask: (body: { question: string; method: 'graph' | 'vector'; max_hops: number; relation_types?: string[]; date_from?: string; date_to?: string }) =>
    fetch('/api/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(async (res) => {
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
      return (await res.json()) as AnswerResult
    }),
}
