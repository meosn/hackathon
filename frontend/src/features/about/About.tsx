import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { ArrowDown, ArrowUpRight, AudioLines, BookOpen, Headphones, Mic, Radio, Sparkles } from 'lucide-react'
import { Brand } from '../../components/UI'
import './about.css'

const steps = [
  { icon: BookOpen, title: 'Start with the source.', text: 'Stories are gathered, related coverage is grouped, and claims are linked to supporting evidence.' },
  { icon: Headphones, title: 'Make it your edition.', text: 'Choose your interests, listening preferences and narrator. Set a routine for your daily briefing.' },
  { icon: Mic, title: 'Stay curious.', text: 'Ask a follow-up while you listen. Explore the context, then return to your briefing.' },
]

export function About() {
  const page = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const elements = page.current?.querySelectorAll<HTMLElement>('[data-reveal]')
    if (!elements || !('IntersectionObserver' in window)) return
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible')
          observer.unobserve(entry.target)
        }
      })
    }, { threshold: 0.12 })
    elements.forEach(element => { element.classList.add('will-reveal'); observer.observe(element) })
    return () => observer.disconnect()
  }, [])

  return <div className="about-page" ref={page}>
    <a className="skip" href="#about-main">Skip to content</a>
    <header className="about-nav">
      <Link to="/" aria-label="Sourcera home"><Brand /></Link>
      <span className="about-nav-label">A little about us</span>
      <Link className="about-nav-cta" to="/">Open listening room <ArrowUpRight size={16} /></Link>
    </header>
    <main id="about-main">
      <section className="about-hero">
        <div className="about-hero-copy">
          <p className="about-eyebrow"><span /> THE LIQUID BRIEFING</p>
          <h1>Less scrolling.<br />More <em>understanding.</em></h1>
          <p className="about-intro">The world moves fast. We’re building a more human way to keep up — personal audio news you can listen to, question and explore.</p>
          <Link className="about-primary" to="/">Find your frequency <ArrowUpRight size={20} /></Link>
          <a className="about-scroll" href="#about-story"><ArrowDown size={14} /> Meet Sourcera</a>
        </div>
        <div className="about-signal" aria-hidden="true">
          <div className="about-orbit orbit-one" /><div className="about-orbit orbit-two" /><div className="about-orbit orbit-three" />
          <span className="about-signal-tag tag-source"><span /> Source connected</span>
          <div className="about-disc"><AudioLines size={60} strokeWidth={1} /><span>tune into the world.</span></div>
          <span className="about-signal-tag tag-listening"><Headphones size={15} /> Made for listening</span>
          <div className="about-wave">{Array.from({ length: 35 }, (_, i) => <i key={i} style={{ height: `${12 + Math.sin(i * 0.7) ** 2 * 44}px`, animationDelay: `${i * -0.13}s` }} />)}</div>
          <span className="about-signal-caption">NEWS → CONTEXT → CONVERSATION</span>
        </div>
      </section>
      <div className="about-ticker" aria-hidden="true"><div>{Array.from({ length: 4 }, (_, i) => <span key={i}>A world worth understanding <Sparkles size={20} /> A voice that feels like you <Sparkles size={20} /></span>)}</div></div>
      <section className="about-story about-section" id="about-story" data-reveal>
        <p className="about-eyebrow">01 / WHY WE’RE HERE</p>
        <div><h2>Your attention is precious.<br /><em>Let’s make it count.</em></h2><p>Keeping up shouldn’t mean keeping a dozen tabs open. Sourcera turns news coverage into a personal listening experience, with the sources close at hand.</p><p>On a walk, on your commute, or between everything else — make a little room for what matters to you.</p></div>
      </section>
      <section className="about-section about-how">
        <div className="about-section-heading" data-reveal><p className="about-eyebrow">02 / HOW IT FLOWS</p><h2>From the headline<br />to the <em>whole picture.</em></h2></div>
        <div className="about-steps">{steps.map(({ icon: Icon, title, text }, i) => <article key={title} data-reveal style={{ transitionDelay: `${i * 90}ms` }}><div className="about-step-top"><Icon size={27} strokeWidth={1.3} /><span>0{i + 1}</span></div><h3>{title}</h3><p>{text}</p></article>)}</div>
      </section>
      <section className="about-principles about-section" data-reveal>
        <div className="about-principles-art" aria-hidden="true"><div /><BookOpen size={58} strokeWidth={1} /><span>Follow the story.<br /><em>Keep the source.</em></span></div>
        <div><p className="about-eyebrow">03 / WHAT WE BELIEVE</p><h2>Curiosity deserves<br /><em>something solid.</em></h2><p>Every great listening experience starts with a reason to trust it.</p><ul><li><strong>Evidence within reach</strong><span>Explore supporting sources and the transcript behind your briefing.</span></li><li><strong>Your rhythm, your voice</strong><span>Choose the topics, narrator and listening routine that fit your day.</span></li><li><strong>Clear about AI</strong><span>Narration and conversational replies use AI. Sources matter, and generated answers can make mistakes.</span></li></ul></div>
      </section>
      <section className="about-team about-section" data-reveal><p className="about-eyebrow">04 / THE PEOPLE BEHIND THE SIGNAL</p><Radio size={30} strokeWidth={1.2} /><h2>Small team.<br /><em>Wide-open curiosity.</em></h2><p>We’re <strong>B2B AI SaaS 67</strong>, the team building Sourcera for MAIN AI Hackathon 2026. Our idea is simple: make staying informed feel more like a conversation.</p><span className="about-team-badge">Built with curiosity · Designed for listening</span></section>
      <section className="about-end" data-reveal><p className="about-eyebrow">YOUR NEXT LISTEN STARTS HERE</p><h2>The world has stories.<br /><em>Make time for yours.</em></h2><Link className="about-primary" to="/">Let’s listen <ArrowUpRight size={20} /></Link></section>
    </main>
    <footer className="about-footer"><Link to="/" aria-label="Sourcera home"><Brand /></Link><span>Personal news. An open conversation.</span><span>MAIN AI Hackathon · 2026</span></footer>
  </div>
}
