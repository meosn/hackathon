import { useEffect } from 'react'
import { Lock } from 'lucide-react'
import './agent-catalog.css'

const characters = [
  { name: 'CJ', portrait: 'cj' },
  { name: 'Dexter Morgan', portrait: 'dexter-morgan' },
  { name: 'Walter White', portrait: 'walter-white' },
  { name: 'Leonardo DiCaprio', portrait: 'leonardo-dicaprio' },
  { name: 'Alucard', portrait: 'alucard' },
  { name: 'Sukuna', portrait: 'sukuna' },
  { name: 'Monkey D. Luffy', portrait: 'luffy' },
  { name: 'Jotaro Kujo', portrait: 'jojo-jotaro' },
  { name: 'Solaire of Astora', portrait: 'dark-souls-solaire' },
]

export function AgentCatalog() {
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [])

  return (
    <section className="agent-catalog" aria-labelledby="agent-catalog-title">
      <h1 id="agent-catalog-title">Agent Catalogs</h1>
      <p className="agent-catalog-status">Subscription coming soon</p>
      <p className="agent-catalog-description">
        These voice agents will be available exclusively to subscribers.
      </p>
      <ul className="agent-catalog-grid" aria-label="Upcoming character voices">
        {characters.map(({ name, portrait }) => (
          <li className="agent-catalog-card" key={portrait}>
            <img src={`${import.meta.env.BASE_URL}agent-catalog/${portrait}.webp`} alt="" loading="lazy" />
            <div className="agent-catalog-card-label">
              <strong>{name}</strong>
              <Lock size={16} role="img" aria-label="Subscription required" />
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
