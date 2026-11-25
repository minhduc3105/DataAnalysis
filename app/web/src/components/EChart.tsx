import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, SVGRenderer])

export function EChart({ option, height = 280 }: { option: echarts.EChartsCoreOption; height?: number }) {
  const el = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!el.current) return
    chart.current = echarts.init(el.current, undefined, { renderer: 'svg' })
    const ro = new ResizeObserver(() => chart.current?.resize())
    ro.observe(el.current)
    const mo = new MutationObserver(() => apply())
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    const apply = () => {
      const dark = document.documentElement.dataset.theme === 'dark'
      const css = getComputedStyle(document.documentElement)
      const map: Record<string, string> = dark ? {
        '#1d5fbf': css.getPropertyValue('--accent').trim(), '#3474c4': css.getPropertyValue('--accent').trim(),
        '#6366f1': '#a5b4fc', '#4f46e5': '#a5b4fc', '#c7d2fe': '#4f46e5', '#f59e0b': '#fbbf24',
        '#e8ebef': css.getPropertyValue('--chart-grid').trim(), '#f1f5f9': css.getPropertyValue('--chart-grid').trim(),
        '#64748b': css.getPropertyValue('--muted').trim(), '#334155': css.getPropertyValue('--ink').trim(),
        '#fff': css.getPropertyValue('--surface').trim(), '#ffffff': css.getPropertyValue('--surface').trim(),
      } : {}
      const recolor = (input: unknown): unknown => {
        if (typeof input === 'string') return map[input.toLowerCase()] ?? input
        if (Array.isArray(input)) return input.map(recolor)
        if (input && typeof input === 'object') return Object.fromEntries(Object.entries(input).map(([key, value]) => [key, recolor(value)]))
        return input
      }
      const themed = recolor(option) as echarts.EChartsCoreOption
      chart.current?.setOption({ textStyle: { fontFamily: 'Be Vietnam Pro, sans-serif', color: css.getPropertyValue('--muted').trim() }, grid: { left: 48, right: 16, top: 24, bottom: 36 }, ...themed }, true)
    }
    apply()
    return () => {
      ro.disconnect()
      mo.disconnect()
      chart.current?.dispose()
    }
  }, [option])

  return <div ref={el} style={{ height }} className="w-full" />
}
