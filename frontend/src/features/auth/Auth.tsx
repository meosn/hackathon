import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Cpu, ChartNoAxesCombined, Headphones } from 'lucide-react'
import { api, setToken } from '../../api/client'
import { Brand, Button, ErrorNote, Tabs } from '../../components/UI'
const credentials = z.object({
  name: z.string().trim().max(100).optional(),
  email: z.string().email(),
  password: z.string().min(1),
})
type Credentials = z.infer<typeof credentials>
export function Auth({ demoMode = true }: { demoMode?: boolean }) {
  const [tab, setTab] = useState(demoMode ? 'demo' : 'login')
  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm<Credentials>({ resolver: zodResolver(credentials) })
  const navigate = useNavigate()
  const sign = useMutation({
    mutationFn: ({ path, data }: { path: string; data: unknown }) =>
      api<{ access_token: string }>('/auth/' + path, 'POST', data),
    onSuccess: (r) => {
      setToken(r.access_token)
      navigate('/', { replace: true })
    },
  })
  function submit(data: Credentials) {
    if (tab === 'register' && !data.name?.trim()) {
      setError('name', { message: 'Enter your name.' })
      return
    }
    if (tab === 'register' && data.password.length < 8) {
      setError('password', { message: 'Use at least 8 characters.' })
      return
    }
    sign.mutate({
      path: tab,
      data:
        tab === 'register'
          ? data
          : { email: data.email, password: data.password },
    })
  }
  return (
    <main className="listener-access">
      <section className="auth-form">
        <div className="auth-body">
          <Brand />
          <h1>
            {tab === 'demo'
              ? 'Choose a listener'
              : tab === 'register'
                ? 'Create your profile'
                : 'Sign in'}
          </h1>
          <Tabs
            value={tab}
            onChange={(id) => {
              setTab(id)
              sign.reset()
            }}
            options={[
              ...(demoMode ? [{ id: 'demo', name: 'Demo profiles' }] : []),
              { id: 'login', name: 'Sign in' },
              { id: 'register', name: 'Register' },
            ]}
          />
          {tab === 'demo' ? (
            <>
              <p className="muted">
                Try a listener profile with its own interests, language and briefing.
              </p>
              {[
                { id: 'tech', name: 'Technology enthusiast', icon: Cpu },
                {
                  id: 'finance',
                  name: 'Financial analyst',
                  icon: ChartNoAxesCombined,
                },
              ].map((p) => (
                <button
                  key={p.id}
                  className="profile-option"
                  disabled={sign.isPending}
                  onClick={() =>
                    sign.mutate({ path: 'demo', data: { profile: p.id } })
                  }
                >
                  <span className="profile-icon">
                    <p.icon size={22} />
                  </span>
                  <strong>{p.name}</strong>
                  <Headphones size={17} />
                </button>
              ))}
            </>
          ) : (
            <form onSubmit={handleSubmit(submit)} className="form-stack">
              {tab === 'register' && (
                <label className="field">
                  Name
                  <input autoComplete="name" {...register('name')} />
                  {errors.name && <small>{errors.name.message}</small>}
                </label>
              )}
              <label className="field">
                Email
                <input
                  type="email"
                  autoComplete="email"
                  {...register('email')}
                />
                {errors.email && <small>{errors.email.message}</small>}
              </label>
              <label className="field">
                Password
                <input
                  type="password"
                  autoComplete={
                    tab === 'register' ? 'new-password' : 'current-password'
                  }
                  {...register('password')}
                />
                {errors.password && <small>{errors.password.message}</small>}
              </label>
              <Button disabled={sign.isPending}>
                {tab === 'register' ? 'Create profile' : 'Sign in'}
              </Button>
            </form>
          )}
          <ErrorNote error={sign.error} />
        </div>
      </section>
    </main>
  )
}
