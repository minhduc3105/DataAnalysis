import { useEffect, useRef, useState } from 'react'

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const depsKey = JSON.stringify(deps)
  const fnRef = useRef(fn)
  const [state, setState] = useState<{ key: string; data?: T; error?: unknown; loading: boolean }>({ key: depsKey, loading: true })

  useEffect(() => {
    fnRef.current = fn
  }, [fn])

  useEffect(() => {
    let alive = true
    fnRef.current().then(
      (data) => alive && setState({ key: depsKey, data, loading: false }),
      (error) => alive && setState({ key: depsKey, error, loading: false }),
    )
    return () => {
      alive = false
    }
  }, [depsKey])
  return state.key === depsKey ? state : { ...state, key: depsKey, loading: true, error: undefined }
}

export function useDebounced<T>(value: T, ms = 250) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}
