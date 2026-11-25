import { Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type SearchHit } from '../api'
import { useDebounced } from '../hooks'
import { TypeBadge } from './ui'

export function EntitySearch({ onSelect, placeholder = 'Tìm nghệ sĩ, bài hát, công ty…', initialValue = '' }: { onSelect: (hit: SearchHit) => void; placeholder?: string; initialValue?: string }) {
  const [q, setQ] = useState(initialValue)
  const [hits, setHits] = useState<SearchHit[]>([])
  const [open, setOpen] = useState(false)
  const debounced = useDebounced(q)
  const visibleHits = debounced.trim() && debounced !== initialValue ? hits : []
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!debounced.trim() || debounced === initialValue) return
    let alive = true
    api.search(debounced).then((h) => alive && setHits(h), () => alive && setHits([]))
    return () => {
      alive = false
    }
  }, [debounced, initialValue])

  useEffect(() => {
    const close = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  return (
    <div ref={box} className="relative w-full">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <input
        value={q}
        onChange={(e) => {
          setQ(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        placeholder={placeholder}
        className="w-full rounded-xl border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm outline-none transition focus:border-brand-500 focus:ring-2 focus:ring-brand-100"
      />
      {open && visibleHits.length > 0 && (
        <ul className="absolute z-30 mt-1 max-h-80 w-full overflow-auto rounded-xl border border-slate-200 bg-white py-1 shadow-lg">
          {visibleHits.map((h) => (
            <li key={h.id}>
              <button
                type="button"
                onClick={() => {
                  onSelect(h)
                  setQ(h.name)
                  setOpen(false)
                }}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-slate-50"
              >
                <span className="truncate font-medium text-slate-800">{h.name}</span>
                <span className="flex shrink-0 items-center gap-2 text-xs text-slate-400">
                  {h.degree} liên kết <TypeBadge type={h.type} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
