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
  edges: { relation: string; relation_id: string; source: string; target: string; quote: string | null; url: string | null; source_name: string | null }[]
}

export type NetworkBundle = Record<string, Row[]>

async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)]))
  const res = await fetch(`/api${path}${qs.size ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? res.statusText)
  return res.json()
}

export const api = {
  network: () => get<NetworkBundle>('/network'),
  rankings: (measure: string, role?: string, limit = 30) => get<Row[]>('/rankings', { measure, role, limit }),
  communities: () => get<Row[]>('/communities'),
  search: (q: string) => get<SearchHit[]>('/search', { q }),
  entity: (id: string, limit = 60) => get<EntityDetail>(`/entity/${encodeURIComponent(id)}`, { limit }),
  evidence: (relationId: string) => get<Evidence[]>(`/evidence/${encodeURIComponent(relationId)}`),
  path: (source: string, target: string, maxHops = 4) => get<PathResult>('/path', { source, target, max_hops: maxHops }),
}
