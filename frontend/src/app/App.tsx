import { useSyncExternalStore } from 'react'
import { Routes, Route, Link, NavLink, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Info, LogOut, Settings2 } from 'lucide-react'
import { getToken, setToken, useApi } from '../api/client'
import type { User } from '../api/types'
import type { Health } from '../api/client'
import { Brand, ErrorNote, Loading } from '../components/UI'
import { NotificationInbox } from '../components/NotificationInbox'
import { Auth } from '../features/auth/Auth'
import {
  BriefingForm,
  BriefingView,
  History,
} from '../features/briefings/Briefings'
import { Explore, StoryView } from '../features/news/News'
import { Assistant } from '../features/assistant/Assistant'
import { Settings } from '../features/settings/Settings'
import { Analytics } from '../features/analytics/Analytics'
import { StudioHome } from '../features/briefings/StudioHome'
import { AgentCatalog } from '../features/voice/AgentCatalog'
import { About } from '../features/about/About'
import { usePlayer } from '../stores/player'

const subscribe = (callback: () => void) => {
  window.addEventListener('sourcera-session', callback)
  return () => window.removeEventListener('sourcera-session', callback)
}
export function App() {
  const token = useSyncExternalStore(subscribe, getToken)
  const user = useApi<User>('/auth/me', !!token)
  const health = useApi<Health>('/health')
  const location = useLocation()
  const navigate = useNavigate()
  const setActive = usePlayer((state) => state.setActive)
  if (location.pathname === '/about') return <About />
  if (!token) return <Auth />
  if (user.isPending && !user.data)
    return (
      <main className="splash">
        <Brand />
        <Loading>Opening listening room…</Loading>
      </main>
    )
  if (!user.data)
    return (
      <main className="splash">
        <ErrorNote error={user.error} />
        <button className="btn outline" onClick={() => user.refetch()}>
          Retry
        </button>
        <button className="btn quiet" onClick={() => { navigate('/login'); setToken(null) }}>
          Switch listener
        </button>
      </main>
    )
  const me = user.data
  if (location.pathname === '/login') return <Navigate to="/" replace />
  const home = location.pathname === '/'
  const settings = location.pathname === '/settings'
  return (
    <div className="music-home">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="music-header">
        <Link to="/" aria-label="Sourcera home">
          <Brand />
        </Link>
        <div className="music-header-actions">
          <Link to="/about" className="about-header-link">About us</Link>
          {me.is_guest && <button type="button" className="btn quiet" onClick={() => { setActive(null); navigate('/login'); setToken(null) }}>Create account</button>}
          <NotificationInbox/>
          <Link to="/settings" className="music-settings" aria-label="Settings">
            <Settings2 size={20} />
            <span>Settings</span>
          </Link>
          <button
            type="button"
            className="icon"
            aria-label="Switch listener"
            onClick={() => {
              setActive(null)
              navigate('/login')
              setToken(null)
            }}
          >
            <LogOut size={18} />
          </button>
        </div>
      </header>
      {health.data?.news_reference_time && (
        <details className="corpus-notice">
          <summary>
            <span className="archive-dot" /> Archive edition{' '}
            <span className="archive-date">
              ·{' '}
              {new Date(health.data.news_reference_time).toLocaleDateString(
                'en',
                { day: 'numeric', month: 'short', year: 'numeric' },
              )}
            </span>
            <Info size={12} />
          </summary>
          <p>
            Hackathon archive · Short source excerpts and AI-generated
            narration. News through{' '}
            {new Date(health.data.news_reference_time).toLocaleDateString()}.
          </p>
        </details>
      )}
      {home ? (
        <StudioHome user={me} />
      ) : (
        <main id="main" className="authenticated-content">
          {!settings && (
            <nav className="secondary-navigation" aria-label="Main navigation">
              <NavLink to="/" end>
                Listening room
              </NavLink>
              <NavLink to="/explore">Explore stories</NavLink>
              <NavLink to="/briefings">Briefing history</NavLink>
              <NavLink to="/assistant">Ask Sourcera</NavLink>
              {(me.is_admin || me.is_demo) && (
                <NavLink to="/transparency">Transparency</NavLink>
              )}
            </nav>
          )}
          <Routes>
            <Route path="/agent-catalogs" element={<AgentCatalog />} />
            <Route path="/explore" element={<Explore />} />
            <Route path="/stories/:id" element={<StoryView />} />
            <Route path="/briefings" element={<History />} />
            <Route path="/briefings/new" element={<BriefingForm />} />
            <Route path="/briefings/:id" element={<BriefingView />} />
            <Route path="/assistant" element={<Assistant user={me} />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/transparency" element={<Analytics />} />
            <Route
              path="*"
              element={
                <>
                  <h1>Page unavailable</h1>
                  <Link className="btn outline" to="/">
                    Return to listening room
                  </Link>
                </>
              }
            />
          </Routes>
        </main>
      )}
    </div>
  )
}
