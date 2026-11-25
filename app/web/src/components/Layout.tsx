import { Bell, Bot, Menu, Moon, Newspaper, Route, Share2, Sun, TrendingUp, X, Monitor } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { EntitySearch } from './EntitySearch'

const NAV = [
  { to: '/', label: 'Tổng quan hôm nay', icon: Newspaper, group: 'Khám phá' },
  { to: '/watch', label: 'Theo dõi & cảnh báo', icon: Bell },
  { to: '/trends', label: 'Xu hướng', icon: TrendingUp },
  { to: '/explain', label: 'Vì sao liên quan?', icon: Route, group: 'Đi sâu vào dữ liệu' },
  { to: '/ask', label: 'Hỏi đáp có nguồn', icon: Bot },
  { to: '/network', label: 'Chân dung mạng', icon: Share2 },
]

function RadarMark() {
  return <svg viewBox="0 0 40 40" fill="none" aria-hidden="true" className="radar-mark"><circle cx="20" cy="20" r="16" stroke="currentColor" strokeWidth="1.5" /><circle cx="20" cy="20" r="9" stroke="currentColor" strokeWidth="1.5" /><path d="M20 4v16l11 11" stroke="currentColor" strokeWidth="1.5" /><circle cx="20" cy="20" r="3" fill="currentColor" /><circle cx="9" cy="10" r="3" fill="currentColor" /></svg>
}

export function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  const [theme, setTheme] = useState<'system' | 'light' | 'dark'>(() => (localStorage.getItem('vnmr-theme') as 'system' | 'light' | 'dark') || 'system')
  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => { document.documentElement.dataset.theme = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme }
    apply()
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [theme])
  const setPreference = (value: 'system' | 'light' | 'dark') => { setTheme(value); localStorage.setItem('vnmr-theme', value) }
  const current = NAV.find((item) => item.to === location.pathname)?.label ?? (location.pathname === '/feed' ? 'Bảng tin âm nhạc' : location.pathname.startsWith('/entity/') ? 'Hồ sơ thực thể' : 'VN Music Radar')
  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">Đến nội dung chính</a>
      <aside className="app-sidebar">
        <Link to="/" className="brand"><RadarMark /><span><strong>VN Music Radar</strong><small>Lắng nghe qua bằng chứng</small></span></Link>
        <nav aria-label="Điều hướng chính" className="side-nav">
          {NAV.map(({ to, label, icon: Icon, group }) => <div key={to}>{group && <p className="nav-group">{group}</p>}<NavLink to={to} end={to === '/'} className={({ isActive }) => `nav-item ${isActive ? 'is-active' : ''}`}><Icon size={17} strokeWidth={1.7} />{label}</NavLink></div>)}
        </nav>
        <div className="sidebar-note"><span className="scope-symbol" aria-hidden="true">VN</span><div><strong>Mạng âm nhạc Việt</strong><p>Đề tài 23 · Phân tích mạng xã hội</p></div></div>
      </aside>
      <div className="app-workspace">
        <header className="app-topbar">
          <button className="mobile-menu" aria-label={menuOpen ? 'Đóng điều hướng' : 'Mở điều hướng'} aria-expanded={menuOpen} aria-controls="mobile-navigation" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={20} /> : <Menu size={20} />}</button>
          <span className="workspace-location">Không gian nghiên cứu <span>/</span> <strong>{current}</strong></span>
          <div className="global-search"><EntitySearch onSelect={(h) => { navigate(`/entity/${h.id}`); setMenuOpen(false) }} /></div>
          <div className="theme-control" role="group" aria-label="Giao diện">
            <button aria-label="Theo giao diện hệ thống" title="Theo giao diện hệ thống" aria-pressed={theme === 'system'} onClick={() => setPreference('system')}><Monitor size={15} /></button>
            <button aria-label="Giao diện sáng" title="Giao diện sáng" aria-pressed={theme === 'light'} onClick={() => setPreference('light')}><Sun size={15} /></button>
            <button aria-label="Giao diện tối" title="Giao diện tối" aria-pressed={theme === 'dark'} onClick={() => setPreference('dark')}><Moon size={15} /></button>
          </div>
        </header>
        {menuOpen && <nav id="mobile-navigation" aria-label="Điều hướng trên điện thoại" className="mobile-nav"><Link to="/" onClick={() => setMenuOpen(false)} className="mobile-brand">VN Music Radar</Link>{NAV.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === '/'} onClick={() => setMenuOpen(false)} className={({ isActive }) => `nav-item ${isActive ? 'is-active' : ''}`}><Icon size={17} />{label}</NavLink>)}</nav>}
        <main id="main-content" tabIndex={-1} className="app-main"><div className="page-content"><Outlet /></div></main>
      </div>
    </div>
  )
}
