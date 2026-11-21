import { useEffect, useRef, useState } from 'react'
import { useApi } from '../../api/client'

type Identity = { initialize: (options: { client_id: string; nonce: string; callback: (r: { credential: string }) => void }) => void;
  renderButton: (element: HTMLElement, options: Record<string, unknown>) => void }
declare global { interface Window { google?: { accounts: { id: Identity } } } }
let script: Promise<void> | undefined
function loadGoogle() {
  if (window.google) return Promise.resolve()
  return script ??= new Promise<void>((resolve, reject) => {
    const el = document.createElement('script')
    el.src = 'https://accounts.google.com/gsi/client'
    el.async = true
    el.onload = () => resolve()
    el.onerror = () => { el.remove(); script = undefined; reject(new Error('Google could not be loaded. Please try again.')) }
    document.head.appendChild(el)
  })
}
export function GoogleSignIn({ onCredential }: { onCredential: (credential: string, nonce: string) => void }) {
  const config = useApi<{ google_client_id: string | null }>('/auth/providers')
  const container = useRef<HTMLDivElement>(null)
  const callback = useRef(onCredential)
  callback.current = onCredential
  const [error, setError] = useState('')
  useEffect(() => {
    if (!config.data?.google_client_id) return
    let active = true
    const clientId = config.data.google_client_id
    const nonce = crypto.randomUUID()
    void loadGoogle().then(() => {
      if (!active || !container.current || !window.google) return
      window.google.accounts.id.initialize({ client_id: clientId, nonce,
        callback: r => { if (active) callback.current(r.credential, nonce) } })
      window.google.accounts.id.renderButton(container.current, { theme: 'outline', size: 'large', shape: 'pill', width: Math.min(container.current.clientWidth || 300, 390), text: 'continue_with' })
    }).catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [config.data?.google_client_id])
  return <div className="google-access">
    <div ref={container} hidden={!config.data?.google_client_id} />
    {!config.data?.google_client_id && <>
      <button type="button" className="btn outline" disabled>Continue with Google</button>
      <small>{config.isPending ? 'Loading sign-in options…' : 'Google sign-in is not configured yet.'}</small>
    </>}
    {error && <p role="alert">{error}</p>}
  </div>
}
