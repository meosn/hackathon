import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation } from '@tanstack/react-query'
import { useNavigate, useLocation } from 'react-router-dom'
import { api, setToken } from '../../api/client'
import { Brand, Button, ErrorNote, Tabs } from '../../components/UI'
const credentials = z.object({
  name: z.string().trim().max(100).optional(),
  email: z.string().email(),
  password: z.string().min(1),
})
type Credentials = z.infer<typeof credentials>
export function Auth() {
  const [tab, setTab] = useState('login')
  const {
    register,
    handleSubmit,
    formState: { errors },
    setError,
  } = useForm<Credentials>({ resolver: zodResolver(credentials) })
  const navigate = useNavigate()
  const location = useLocation()
  const sign = useMutation({
    mutationFn: ({ path, data }: { path: string; data: unknown }) =>
      api<{ access_token: string }>('/auth/' + path, 'POST', data),
    onSuccess: (r) => {
      setToken(r.access_token)
      navigate(location.pathname === '/login' ? '/' : location.pathname + location.search, { replace: true })
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
            {tab === 'register' ? 'Create your profile' : 'Sign in'}
          </h1>
          <Tabs
            value={tab}
            onChange={(id) => {
              setTab(id)
              sign.reset()
            }}
            options={[
              { id: 'login', name: 'Sign in' },
              { id: 'register', name: 'Register' },
            ]}
          />
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
          <ErrorNote error={sign.error} />
        </div>
      </section>
    </main>
  )
}
