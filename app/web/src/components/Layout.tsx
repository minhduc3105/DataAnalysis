import { Bell, Bot, Newspaper, Route, Share2, TrendingUp, Waves } from 'lucide-react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { EntitySearch } from './EntitySearch'

const NAV = [
  { to: '/', label: 'Bảng tin', icon: Newspaper },
  { to: '/watch', label: 'Theo dõi & cảnh báo', icon: Bell },
  { to: '/trends', label: 'Xu hướng', icon: TrendingUp },
  { to: '/explain', label: 'Vì sao liên quan?', icon: Route },
  { to: '/ask', label: 'Hỏi đáp', icon: Bot },
  { to: '/network', label: 'Chân dung mạng', icon: Share2 },
]

export function Layout() {
  const navigate = useNavigate()
  return (
    <div className="flex h-full bg-[#f2f4f7]">
      <aside className="hidden w-60 shrink-0 flex-col bg-[#f2f4f7] md:flex">
        <div className="flex items-center gap-2 px-5 py-6">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-white">
            <Waves className="h-5 w-5" strokeWidth={1.6} />
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-900">VN Music Radar</div>
            <div className="text-xs text-slate-500">Lắng nghe mạng âm nhạc Việt</div>
          </div>
        </div>
        <nav className="flex flex-col gap-1 px-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${isActive ? 'bg-[#e6e8eb] text-slate-900' : 'text-slate-600 hover:bg-white/70 hover:text-slate-900'}`
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-5 py-4 text-xs text-slate-400">Đề tài 23 · Phân tích mạng xã hội</div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-4 border-b border-slate-200 bg-[#f2f4f7] px-4 py-3 md:px-6">
          <div className="w-full max-w-xl">
            <EntitySearch onSelect={(h) => navigate(`/entity/${h.id}`)} />
          </div>
        </header>
        <nav aria-label="Điều hướng" className="flex gap-1 overflow-x-auto border-b border-slate-200 bg-[#f2f4f7] px-3 py-2 md:hidden">
          {NAV.map(({ to, label }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `shrink-0 rounded-md px-3 py-2 text-xs ${isActive ? 'bg-[#e6e8eb] font-medium text-slate-900' : 'text-slate-600'}`}>{label}</NavLink>)}
        </nav>
        <main className="min-w-0 flex-1 overflow-auto px-4 py-6 md:px-7">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
