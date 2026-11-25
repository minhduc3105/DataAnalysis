import cytoscape from 'cytoscape'
import { useEffect, useRef, useState } from 'react'
import type { Neighbor } from '../api'
import { RELATION_LABEL, TYPE_COLOR } from '../labels'

export function EgoGraph({ center, neighbors, onSelect, height = 460 }: { center: { id: string; name: string; type: string }; neighbors: Neighbor[]; onSelect: (n: Neighbor) => void; height?: number }) {
  const el = useRef<HTMLDivElement>(null)
  const select = useRef(onSelect)
  const [theme, setTheme] = useState(document.documentElement.dataset.theme ?? 'light')
  useEffect(() => {
    select.current = onSelect
  }, [onSelect])

  useEffect(() => {
    const observer = new MutationObserver(() => setTheme(document.documentElement.dataset.theme ?? 'light'))
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!el.current) return
    const seen = new Set<string>()
    const dark = theme === 'dark'
    const nodes = neighbors.filter((n) => !seen.has(n.id) && seen.add(n.id))
    const maxPr = Math.max(1, ...nodes.map((n) => n.pagerank ?? 0))
    const cy = cytoscape({
      container: el.current,
      elements: [
        { data: { id: center.id, label: center.name, color: TYPE_COLOR[center.type] ?? '#64748b', size: 56 }, classes: 'center' },
        ...nodes.map((n) => ({ data: { id: n.id, label: n.name, color: TYPE_COLOR[n.type] ?? '#64748b', size: 18 + 26 * ((n.pagerank ?? 0) / maxPr) } })),
        ...neighbors.map((n, i) => ({
          data: { id: `e${i}`, source: n.outgoing ? center.id : n.id, target: n.outgoing ? n.id : center.id, label: RELATION_LABEL[n.relation] ?? n.relation, idx: i },
        })),
      ],
      style: [
        {
          selector: 'node',
          style: {
            'background-color': 'data(color)', width: 'data(size)', height: 'data(size)', label: 'data(label)', 'font-size': 10,
            'font-family': 'Be Vietnam Pro', color: dark ? '#edf4f0' : '#263a32', 'text-valign': 'bottom', 'text-margin-y': 4, 'text-max-width': '120px', 'text-wrap': 'ellipsis',
            'text-background-color': dark ? '#1d2522' : '#ffffff', 'text-background-opacity': 0.94, 'text-background-padding': '2px',
            'border-width': 2, 'border-color': dark ? '#1d2522' : '#fff',
          },
        },
        { selector: 'node.center', style: { 'font-size': 13, 'font-weight': 600, color: dark ? '#fff' : '#0f172a', 'border-width': 4, 'border-color': dark ? '#344b40' : '#d9eee2' } },
        {
          selector: 'edge',
          style: { width: 1.2, 'line-color': dark ? '#66766e' : '#aebdb4', 'target-arrow-color': dark ? '#66766e' : '#aebdb4', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.7, 'curve-style': 'bezier' },
        },
        { selector: 'edge:selected, edge.hover', style: { 'line-color': dark ? '#6ec2a0' : '#246b55', 'target-arrow-color': dark ? '#6ec2a0' : '#246b55', width: 2.4, label: 'data(label)', 'font-size': 10, color: dark ? '#8bd4b3' : '#185541', 'text-background-color': dark ? '#1d2522' : '#fff', 'text-background-opacity': 1 } },
      ],
      layout: { name: 'cose', animate: false, randomize: false, idealEdgeLength: () => 110, nodeRepulsion: () => 12000, nodeOverlap: 20, gravity: 0.6, padding: 24 } as cytoscape.LayoutOptions,
      wheelSensitivity: 0.2,
    })
    cy.on('mouseover', 'edge', (e) => e.target.addClass('hover'))
    cy.on('mouseout', 'edge', (e) => e.target.removeClass('hover'))
    cy.on('tap', 'edge', (e) => select.current(neighbors[e.target.data('idx')]))
    cy.on('tap', 'node', (e) => {
      const i = neighbors.findIndex((n) => n.id === e.target.id())
      if (i >= 0) select.current(neighbors[i])
    })
    return () => cy.destroy()
  }, [center.id, center.name, center.type, neighbors, theme])

  return <div ref={el} style={{ height }} className="w-full rounded-xl bg-slate-50" />
}
