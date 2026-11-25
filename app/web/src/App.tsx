import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'

const EntityPage = lazy(() => import('./pages/Entity').then((module) => ({ default: module.EntityPage })))
const ExplainPage = lazy(() => import('./pages/Explain').then((module) => ({ default: module.ExplainPage })))
const NetworkPage = lazy(() => import('./pages/Network').then((module) => ({ default: module.NetworkPage })))
const FeedPage = lazy(() => import('./pages/Feed').then((module) => ({ default: module.FeedPage })))
const WatchPage = lazy(() => import('./pages/Watch').then((module) => ({ default: module.WatchPage })))
const TrendsPage = lazy(() => import('./pages/Trends').then((module) => ({ default: module.TrendsPage })))
const AskPage = lazy(() => import('./pages/Ask').then((module) => ({ default: module.AskPage })))

export default function App() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-slate-500">Đang tải màn hình…</div>}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<FeedPage />} />
          <Route path="watch" element={<WatchPage />} />
          <Route path="trends" element={<TrendsPage />} />
          <Route path="ask" element={<AskPage />} />
          <Route path="explain" element={<ExplainPage />} />
          <Route path="network" element={<NetworkPage />} />
          <Route path="entity/:id" element={<EntityPage />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
