import { Menu, Moon, Sun, X, Monitor } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { EntitySearch } from './EntitySearch'

const NAV = [
  { to: '/', label: 'Trang chủ' }, { to: '/feed', label: 'Tin mới' }, { to: '/artists', label: 'Nghệ sĩ' },
  { to: '/trends', label: 'Xu hướng' }, { to: '/watch', label: 'Theo dõi' },
]
const EXPLORE = [
  { to: '/explain', label: 'Vì sao liên quan?' }, { to: '/ask', label: 'Hỏi đáp có nguồn' }, { to: '/network', label: 'Mạng âm nhạc' },
]

export function Layout() {
  const navigate = useNavigate()
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
  return <div className="app-shell magazine-shell">
    <a href="#main-content" className="skip-link">Đến nội dung chính</a>
    <div className="mag-utility"><span>Âm nhạc Việt · Tin mới từ nguồn có bằng chứng</span><span>VN Music Radar / Giai đoạn 2</span></div>
    <header className="mag-header"><Link to="/" className="mag-brand" onClick={() => setMenuOpen(false)}>VN<span>Music</span>Radar<i>.</i></Link>
      <nav className="mag-nav" aria-label="Điều hướng chính">{NAV.map((item) => <NavLink end={item.to === '/'} key={item.to} to={item.to} className={({ isActive }) => isActive ? 'active' : ''}>{item.label}</NavLink>)}<div className="mag-explore"><button type="button">Khám phá</button><div>{EXPLORE.map((item) => <NavLink key={item.to} to={item.to}>{item.label}</NavLink>)}</div></div></nav>
      <div className="mag-header-tools"><div className="mag-search"><EntitySearch onSelect={(hit) => { navigate(`/entity/${hit.id}`); setMenuOpen(false) }} /></div><div className="theme-control" role="group" aria-label="Giao diện"><button aria-label="Theo hệ thống" title="Theo hệ thống" aria-pressed={theme === 'system'} onClick={() => setPreference('system')}><Monitor size={15} /></button><button aria-label="Giao diện sáng" title="Giao diện sáng" aria-pressed={theme === 'light'} onClick={() => setPreference('light')}><Sun size={15} /></button><button aria-label="Giao diện tối" title="Giao diện tối" aria-pressed={theme === 'dark'} onClick={() => setPreference('dark')}><Moon size={15} /></button></div><button className="mag-menu-button" aria-label={menuOpen ? 'Đóng menu' : 'Mở menu'} aria-expanded={menuOpen} aria-controls="mag-mobile-nav" onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? <X size={22} /> : <Menu size={22} />}</button></div>
    </header>
    {menuOpen && <nav id="mag-mobile-nav" className="mag-mobile-nav" aria-label="Điều hướng di động">{[...NAV, ...EXPLORE].map((item) => <NavLink end={item.to === '/'} key={item.to} to={item.to} onClick={() => setMenuOpen(false)}>{item.label}</NavLink>)}</nav>}
    <main id="main-content" tabIndex={-1} className="app-main"><div className="page-content"><Outlet /></div></main>
    <footer className="mag-footer"><Link to="/" className="mag-brand">VN<span>Music</span>Radar<i>.</i></Link><p>Tin, hoạt động và dữ liệu âm nhạc Việt. Mọi thông tin dẫn về nguồn đã thu thập.</p><div><Link to="/feed">Tin mới</Link><Link to="/trends">Xu hướng</Link><Link to="/network">Phân tích mạng</Link></div></footer>
  </div>
}
