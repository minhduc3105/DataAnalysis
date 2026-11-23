import cytoscape from 'cytoscape'
import { useEffect, useRef } from 'react'
import type { Neighbor } from '../api'
import { RELATION_LABEL, TYPE_COLOR } from '../labels'

export function EgoGraph({ center, neighbors, onSelect, height = 460 }: { center: { id: string; name: string; type: string }; neighbors: Neighbor[]; onSelect: (n: Neighbor) => void; height?: number }) {
  const el = useRef<HTMLDivElement>(null)
  const select = useRef(onSelect)
  select.current = onSelect

  useEffect(() => {
    if (!el.current) return
    const seen = new Set<string>()
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
            'font-family': 'Be Vietnam Pro', color: '#334155', 'text-valign': 'bottom', 'text-margin-y': 4, 'text-max-width': '120px', 'text-wrap': 'ellipsis',
            'text-background-color': '#f8fafc', 'text-background-opacity': 0.85, 'text-background-padding': '1px',
            'border-width': 2, 'border-color': '#fff',
          },
        },
        { selector: 'node.center', style: { 'font-size': 13, 'font-weight': 600, color: '#0f172a', 'border-width': 4, 'border-color': '#e0e7ff' } },
        {
          selector: 'edge',
          style: { width: 1.2, 'line-color': '#cbd5e1', 'target-arrow-color': '#cbd5e1', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.7, 'curve-style': 'bezier' },
        },
        { selector: 'edge:selected, edge.hover', style: { 'line-color': '#6366f1', 'target-arrow-color': '#6366f1', width: 2.4, label: 'data(label)', 'font-size': 10, color: '#4338ca', 'text-background-color': '#fff', 'text-background-opacity': 1 } },
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
  }, [center.id, center.name, center.type, neighbors])

  return <div ref={el} style={{ height }} className="w-full rounded-xl bg-slate-50" />
}
