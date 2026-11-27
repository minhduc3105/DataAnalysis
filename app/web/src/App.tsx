import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'

const EntityPage = lazy(() => import('./pages/Entity').then((module) => ({ default: module.EntityPage })))
const ExplainPage = lazy(() => import('./pages/Explain').then((module) => ({ default: module.ExplainPage })))
const NetworkPage = lazy(() => import('./pages/Network').then((module) => ({ default: module.NetworkPage })))
const MagazineHome = lazy(() => import('./pages/Magazine').then((module) => ({ default: module.MagazineHome })))
const MagazineFeed = lazy(() => import('./pages/Magazine').then((module) => ({ default: module.MagazineFeed })))
const MagazineTrends = lazy(() => import('./pages/Magazine').then((module) => ({ default: module.MagazineTrends })))
const MagazineArtists = lazy(() => import('./pages/Magazine').then((module) => ({ default: module.MagazineArtists })))
const MagazineArtistPage = lazy(() => import('./pages/Magazine').then((module) => ({ default: module.MagazineArtistPage })))
const MagazineArticlePage = lazy(() => import('./pages/Magazine').then((module) => ({ default: module.MagazineArticlePage })))
const WatchPage = lazy(() => import('./pages/Watch').then((module) => ({ default: module.WatchPage })))
const AskPage = lazy(() => import('./pages/Ask').then((module) => ({ default: module.AskPage })))

export default function App() {
  return (
    <Suspense fallback={<div className="p-8 text-sm text-slate-500">Đang tải màn hình…</div>}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<MagazineHome />} />
          <Route path="feed" element={<MagazineFeed />} />
          <Route path="article/:id" element={<MagazineArticlePage />} />
          <Route path="artists" element={<MagazineArtists />} />
          <Route path="artists/:id" element={<MagazineArtistPage />} />
          <Route path="watch" element={<WatchPage />} />
          <Route path="trends" element={<MagazineTrends />} />
          <Route path="ask" element={<AskPage />} />
          <Route path="explain" element={<ExplainPage />} />
          <Route path="network" element={<NetworkPage />} />
          <Route path="entity/:id" element={<EntityPage />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
