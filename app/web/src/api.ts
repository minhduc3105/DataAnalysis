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
  collected_at?: string | null
  platform: string
  relations: { relation: string; relation_id: string; source: string; target: string; evidence: string }[]
}

export interface MagazineShow { id: string; name: string; year: string; source_status: string; artist_count: number; verified_artist_count: number }
export interface MagazineArtist { id: string; name: string; shows: string[]; verified_shows: string[] }
export interface MagazineArticle {
  document_id: string; title: string | null; url: string | null; source: string | null; platform: string | null
  published_at: string | null; collected_at: string | null; summary: string | null; excerpt: string | null
  image_url: string | null; image_credit: string | null; image_source_url: string | null; image_license: string | null
  artists: { id: string; name: string; shows: string[] }[]
  relations: { relation_id: string; relation: string; artist_id: string; artist_name: string; related_name: string; quote: string | null }[]
  activity: string[]
}
export interface MagazineBundle {
  shows: MagazineShow[]; items: MagazineArticle[]; total: number; period: { from: string; to: string; days: number }
  daily: { date: string; documents: number }[]; top_artists: { id: string; name: string; documents: number }[]
  activity: { name: string; documents: number }[]; roster_status: 'confirmed' | 'needs_review'
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
  scope_steps?: number
  count_7d: number
  baseline_daily_mean: number
  z_score: number | null
  anomaly: boolean
  requires_more_history: boolean
  sources?: { evidence_id: string; title: string; url: string; source: string; published_at?: string; relation: string; related_name: string; distance?: number; path?: string[]; quote?: string }[]
}

export interface TrendBundle {
  days: number
  daily: { date: string; documents: number }[]
  top_entities: { id: string; name: string; documents: number }[]
  total_documents: number
  comparison?: { current: number; previous: number; delta: number; change_percent: number | null; comparison: string }
  previous_daily?: { date: string; documents: number }[]
  coverage?: { status: string; current_days: number; previous_days: number }
  period?: { from: string; previous_from: string; to: string }
  top_communities?: { id: string; name: string; size: number; documents: number }[]
  topics?: { topic: string; documents: number }[]
  sentiment?: { sentiment: string; documents: number }[]
  classification_status?: { status?: string; model_version?: string | null }
}

export interface OverviewBundle {
  period: { days: number; from: string; to: string; previous_from: string; previous_to: string }
  generated_at: string
  latest_collected_at: string | null
  latest_published_at: string | null
  coverage: { status: string; note: string }
  metrics: Record<string, { current: number; previous: number; delta: number; change_percent: number | null; comparison: string }>
  daily: { date: string; documents: number }[]
  top_entities: { id: string; name: string; documents: number; previous_documents: number; delta: number }[]
  top_communities: { id: string; name: string; size: number; documents: number }[]
  analysis_snapshot: { graph_version: string | null; generated_at: string | null } | null
  recent_documents: FeedItem[]
  platforms: { platform: string; documents: number }[]
  topics: { status: string; items: { topic: string; documents: number }[] }
  sentiment: { status: string; interpretation: string; items: { sentiment: string; documents: number }[] }
  new_relations: { event_id: string; reviewed_at: string; relation: string; source: string; target: string; published_at: string; quote: string; url: string; title: string; source_name: string }[]
  source_document_limit: number | null
}

export interface ClassificationBundle {
  status: { status?: string; model_version?: string | null; classified?: number; failed?: number; remaining?: number }
  items: { document_id: string; title?: string; url?: string; source?: string; published_at?: string; classified_at?: string; model_version: string; status: string; topics: string[]; sentiment?: string; quote?: string; error?: string }[]
  offset: number
  limit: number
}

export interface UpdateStatus {
  timezone: string
  schedule: Record<string, string>
  checkpoints: Record<string, Record<string, unknown> | null>
  sources?: Record<string, { status: string; updated_at?: string; detail?: string }>
  reports: Record<string, Record<string, unknown> | null>
  pipeline?: { status?: string; updated_at?: string; steps?: Record<string, { status?: string; ready?: number; pending_review?: number; rejected?: number; error?: string }> } | null
  scheduler: { status: string; heartbeat_at?: string; next_runs?: Record<string, string | null>; age_seconds?: number }
  sentiment: string
  topics: string
  content_classification?: { status?: string; model_version?: string | null; classified?: number; failed?: number; remaining?: number; pending?: number }
  checked_at: string
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

async function get<T>(path: string, params: Record<string, string | number | string[] | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === '') return
    if (Array.isArray(value)) value.forEach((item) => qs.append(key, item))
    else qs.set(key, String(value))
  })
  const res = await fetch(`/api${path}${qs.size ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
  return res.json()
}

export const api = {
  magazineShows: () => get<MagazineShow[]>('/magazine/shows'),
  magazineArtists: (show_id?: string) => get<MagazineArtist[]>('/magazine/artists', { show_id }),
  magazineArticles: (params: { days?: number; show_id?: string; artist_id?: string; source?: string; activity?: string; date_from?: string; date_to?: string; limit?: number; offset?: number } = {}) => get<MagazineBundle>('/magazine/articles', params),
  magazineArticle: (documentId: string) => get<MagazineArticle>(`/magazine/articles/${encodeURIComponent(documentId)}`),
  network: (graph_version?: string) => get<NetworkBundle>('/network', { graph_version }),
  snapshots: () => get<AnalysisSnapshot[]>('/analysis/snapshots'),
  rankings: (measure: string, role?: string, limit = 30, graph_version?: string) => get<Row[]>('/rankings', { measure, role, limit, graph_version }),
  communities: (graph_version?: string) => get<Row[]>('/communities', { graph_version }),
  search: (q: string) => get<SearchHit[]>('/search', { q }),
  entity: (id: string, limit = 60) => get<EntityDetail>(`/entity/${encodeURIComponent(id)}`, { limit }),
  evidence: (relationId: string) => get<Evidence[]>(`/evidence/${encodeURIComponent(relationId)}`),
  path: (source: string, target: string, maxHops = 3) => get<PathResult>('/path', { source, target, max_hops: maxHops }),
  feed: (params: { entity_id?: string; source?: string; date_from?: string; date_to?: string; limit?: number; offset?: number }) => get<FeedItem[]>('/feed', params),
  watchlists: () => get<WatchedEntity[]>('/watchlists'),
  alerts: (scopeSteps = 1, eventTypes?: string[]) => get<AlertItem[]>('/alerts', { scope_steps: scopeSteps, event_types: eventTypes }),
  addWatch: async (entity_id: string) => {
    const res = await fetch('/api/watchlists', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ entity_id }) })
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
    return res.json() as Promise<WatchedEntity>
  },
  removeWatch: async (entity_id: string) => {
    const res = await fetch(`/api/watchlists/${encodeURIComponent(entity_id)}`, { method: 'DELETE' })
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
  },
  trends: (days = 30, entity_id?: string, source?: string, community_id?: string, topic?: string, sentiment?: string) => get<TrendBundle>('/trends', { days, entity_id, source, community_id, topic, sentiment }),
  overview: (days = 7, source?: string) => get<OverviewBundle>('/overview', { days, source }),
  classifications: (limit = 10, offset = 0) => get<ClassificationBundle>('/classifications', { limit, offset }),
  updateStatus: () => get<UpdateStatus>('/update-status'),
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
