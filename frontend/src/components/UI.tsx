import {
  useEffect,
  useRef,
  type ReactNode,
  type ButtonHTMLAttributes,
} from 'react'
import {
  AudioLines,
  CheckCheck,
  TriangleAlert,
  LoaderCircle,
  ChevronDown,
  X,
  ExternalLink,
} from 'lucide-react'
import type { Citation } from '../api/types'
import { label } from '../api/client'
export function Brand() {
  return (
    <span className="brand">
      <span className="mark">
        <AudioLines size={23} strokeWidth={2.5} />
      </span>
      Sourcera<span className="brand-period">.</span>
    </span>
  )
}
export function Button({
  children,
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'outline' | 'quiet'
}) {
  return (
    <button {...props} className={`btn ${variant} ${props.className || ''}`}>
      {children}
    </button>
  )
}
export function Card({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <section className={'panel ' + className}>{children}</section>
}
export function Badge({
  children,
  tone = '',
}: {
  children: ReactNode
  tone?: string
}) {
  return <span className={'badge ' + tone}>{children}</span>
}
export function Tabs({
  value,
  options,
  onChange,
}: {
  value: string
  options: { id: string; name: string }[]
  onChange: (s: string) => void
}) {
  return (
    <div className="tabs">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={value === o.id}
          className={value === o.id ? 'active' : ''}
          onClick={() => onChange(o.id)}
        >
          {o.name}
        </button>
      ))}
    </div>
  )
}
export function Dropdown({
  label: name,
  value,
  onChange,
  children,
}: {
  label: string
  value: string
  onChange: (s: string) => void
  children: ReactNode
}) {
  return (
    <label className="field">
      <span>{name}</span>
      <span className="select-wrap">
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          {children}
        </select>
        <ChevronDown size={16} />
      </span>
    </label>
  )
}
export function ErrorNote({ error }: { error: unknown }) {
  return error ? (
    <p className="error" role="alert">
      {error instanceof Error ? error.message : String(error)}
    </p>
  ) : null
}
export function Loading({ children = 'Loading…' }: { children?: ReactNode }) {
  return (
    <p role="status" className="muted flex items-center gap-2">
      <LoaderCircle className="spin" size={16} />
      {children}
    </p>
  )
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}
export function VerificationIndicator({ status }: { status: string }) {
  const ok = status === 'supported'
  return (
    <Badge tone={ok ? 'green' : 'amber'}>
      {ok ? <CheckCheck size={14} /> : <TriangleAlert size={14} />}{' '}
      {label(status)}
    </Badge>
  )
}
export function SourceCitation({ citation }: { citation: Citation }) {
  let url: URL | undefined
  try {
    const candidate = new URL(citation.url)
    if (['http:', 'https:'].includes(candidate.protocol)) url = candidate
  } catch {
    /* render excerpt even without a usable link */
  }
  const demo =
    citation.is_synthetic ||
    url?.hostname.endsWith('.example') ||
    url?.hostname.endsWith('.invalid')
  return (
    <div className="citation">
      <strong>{citation.source || citation.title || 'Source article'}</strong>
      <q>{citation.excerpt}</q>
      {url && !demo && (
        <a href={url.href} rel="noreferrer" target="_blank">
          Original article <ExternalLink size={13} />
        </a>
      )}
      {demo && <small>Synthetic source</small>}
    </div>
  )
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string
  children: ReactNode
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    ref.current?.showModal()
  }, [])
  return (
    <dialog ref={ref} className="modal" onCancel={onClose} aria-label={title}>
      <div className="section-heading">
        <h2>{title}</h2>
        <button className="icon" aria-label="Close dialog" onClick={onClose}>
          <X />
        </button>
      </div>
      {children}
    </dialog>
  )
}
