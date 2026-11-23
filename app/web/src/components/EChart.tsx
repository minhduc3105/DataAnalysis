import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'

export function EChart({ option, height = 280 }: { option: echarts.EChartsCoreOption; height?: number }) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!el.current) return
    chart.current = echarts.init(el.current, undefined, { renderer: 'svg' })
    const ro = new ResizeObserver(() => chart.current?.resize())
    ro.observe(el.current)
    return () => {
      ro.disconnect()
      chart.current?.dispose()
    }
  }, [])

  useEffect(() => {
    chart.current?.setOption(
      { textStyle: { fontFamily: 'Be Vietnam Pro, sans-serif' }, grid: { left: 48, right: 16, top: 24, bottom: 36 }, ...option },
      true,
    )
  }, [option])

  return <div ref={el} style={{ height }} className="w-full" />
}
