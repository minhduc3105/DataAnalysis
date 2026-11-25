import { useState } from 'react'
import type { FormEvent } from 'react'
import { ExternalLink, GitBranch, Search } from 'lucide-react'
import { api, type AnswerResult } from '../api'
import { Card, Chip, ErrorBox, Loading, PageHeader } from '../components/ui'
import { RELATION_LABEL } from '../labels'

const EXAMPLES = ['Ai từng hợp tác với Hoàng Dũng và gần đây có tin mới?', 'Công ty nào phát hành bài của nghệ sĩ thuộc cộng đồng này?']

export function AskPage() {
  const [question, setQuestion] = useState('')
  const [method, setMethod] = useState<'graph' | 'vector'>('graph')
  const [maxHops, setMaxHops] = useState(3)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [relationTypes, setRelationTypes] = useState<string[]>([])
  const [result, setResult] = useState<AnswerResult | null>(null)
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!question.trim()) return
    setLoading(true); setResult(null); setError(undefined)
    try { setResult(await api.ask({ question: question.trim(), method, max_hops: maxHops, relation_types: relationTypes.length ? relationTypes : undefined, date_from: dateFrom || undefined, date_to: dateTo || undefined })) } catch (e) { setError(e) } finally { setLoading(false) }
  }
  return (
    <div className="space-y-6">
      <PageHeader title="Hỏi đáp có nguồn" subtitle="So sánh truy xuất GraphRAG tối đa 3 bước với tìm kiếm vector trên cùng kho bằng chứng." />
      <form onSubmit={submit}>
        <Card>
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} maxLength={1200} placeholder="Đặt câu hỏi về nghệ sĩ, tác phẩm, công ty hoặc tin mới…" className="w-full resize-y rounded-lg border border-slate-300 p-3 text-sm text-slate-900 placeholder:text-slate-400 focus:border-blue-700 focus:outline-none" />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-end gap-2"><div className="flex items-center gap-2"><Chip active={method === 'graph'} onClick={() => setMethod('graph')}><span className="inline-flex items-center gap-1"><GitBranch className="h-3.5 w-3.5" />GraphRAG</span></Chip><Chip active={method === 'vector'} onClick={() => setMethod('vector')}><span className="inline-flex items-center gap-1"><Search className="h-3.5 w-3.5" />Vector</span></Chip></div><label className="text-xs text-slate-500">Bước<select value={maxHops} onChange={(e) => setMaxHops(Number(e.target.value))} className="ml-1 h-9 rounded-lg border border-slate-300 bg-white px-2 text-sm text-slate-800">{[1, 2, 3].map((h) => <option key={h} value={h}>{h}</option>)}</select></label><label className="text-xs text-slate-500">Từ<input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className="ml-1 h-9 rounded-lg border border-slate-300 px-2 text-sm text-slate-800" /></label><label className="text-xs text-slate-500">Đến<input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className="ml-1 h-9 rounded-lg border border-slate-300 px-2 text-sm text-slate-800" /></label></div>
            <button disabled={loading || question.trim().length < 4} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">Tìm bằng chứng</button>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">{EXAMPLES.map((example) => <button key={example} type="button" onClick={() => setQuestion(example)} className="text-left text-xs text-blue-800 underline decoration-blue-200 underline-offset-2">{example}</button>)}</div>
        </Card>
      </form>
      <details className="rounded-lg border border-slate-200 bg-white px-4 py-3">
        <summary className="cursor-pointer text-sm font-medium text-slate-700">Lọc loại quan hệ {relationTypes.length ? `(${relationTypes.length})` : '(tất cả)'}</summary>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{Object.entries(RELATION_LABEL).map(([key, label]) => <label key={key} className="flex items-center gap-2 text-xs text-slate-600"><input type="checkbox" checked={!relationTypes.length || relationTypes.includes(key)} onChange={(e) => setRelationTypes((current) => {
          const selected = current.length ? current : Object.keys(RELATION_LABEL)
          const next = e.target.checked ? [...selected, key] : selected.filter((type) => type !== key)
          return next.length === Object.keys(RELATION_LABEL).length ? [] : next
        })} />{label}</label>)}</div>
      </details>
      {loading && <Loading label="Đang truy xuất bằng chứng và gọi dịch vụ trả lời…" />}
      {error ? <ErrorBox error={error} /> : null}
      {result && <Card title={result.status === 'ok' ? 'Trả lời' : 'Chưa đủ cơ sở'} subtitle={method === 'graph' ? 'Đường đi trên đồ thị tối đa ba bước' : 'Các câu bằng chứng gần nhất theo embedding'}>
        <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">{result.answer}</p>
        {result.sources?.length ? <div className="mt-5 border-t border-slate-200 pt-4"><h3 className="text-xs font-medium text-slate-500">Nguồn được trích</h3><ul className="mt-2 space-y-3">{result.sources.map((source) => <li key={source.source_id} className="text-sm"><p className="text-slate-700">“{source.text}”</p><a href={source.url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs text-blue-800 hover:underline">{source.title || source.source_id}<ExternalLink className="h-3 w-3" /></a></li>)}</ul></div> : null}
        {result.status !== 'ok' && <p className="mt-3 text-xs text-slate-500">Kiểm tra Ollama/API mô hình, chỉ mục vector và đồ thị đã nạp bằng chứng.</p>}
      </Card>}
    </div>
  )
}
