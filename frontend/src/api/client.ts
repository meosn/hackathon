import { QueryClient, useQuery } from '@tanstack/react-query'
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 15000, refetchOnWindowFocus: false },
    mutations: { retry: 0 },
  },
})
const sessionKey = 'sourcera.session'
export const getToken = () => sessionStorage.getItem(sessionKey)
export const setToken = (token: string | null) => {
  if (token) sessionStorage.setItem(sessionKey, token)
  else sessionStorage.removeItem(sessionKey)
  queryClient.clear()
  window.dispatchEvent(new Event('sourcera-session'))
}
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}
export async function request(
  path: string,
  method = 'GET',
  data?: unknown,
  signal?: AbortSignal,
) {
  const headers = new Headers()
  const token = getToken()
  if (token) headers.set('Authorization', 'Bearer ' + token)
  let body: BodyInit | undefined
  if (data instanceof FormData) body = data
  else if (data !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(data)
  }
  const response = await fetch('/api/v1' + path, {
    method,
    body,
    headers,
    signal,
  })
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}))
    const detail = problem.detail ?? problem.error?.message ?? problem.message
    const message = Array.isArray(detail)
      ? detail.map((e) => e.msg).join('. ')
      : typeof detail === 'string'
        ? detail
        : 'Request failed (' + response.status + ')'
    if (
      response.status === 401 &&
      token === getToken() &&
      token &&
      !path.startsWith('/auth/login')
    )
      setToken(null)
    throw new ApiError(message, response.status)
  }
  return response
}
export async function api<T>(
  path: string,
  method = 'GET',
  data?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const r = await request(path, method, data, signal)
  if (r.status === 204) return undefined as T
  return r.json()
}
export const useApi = <T>(path: string, enabled = true) =>
  useQuery({
    queryKey: [path],
    queryFn: ({ signal }) => api<T>(path, 'GET', undefined, signal),
    enabled,
  })
export const label = (s: string) =>
  s.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
export type Health = {
  realtime_voice?: boolean
  news_reference_time?: string | null
  corpus?: string
}
export const clockTime = (s: number) => {
  const n = Math.max(0, Math.floor(Number.isFinite(s) ? s : 0))
  return Math.floor(n / 60) + ':' + String(n % 60).padStart(2, '0')
}
export const niceDate = (s: string) =>
  new Date(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

// Reuse prepared audio across player mounts and release it when its query expires or the session ends.
type BriefingAudio = { url: string }
queryClient.getQueryCache().subscribe((event) => {
  if (
    event.type === 'removed' &&
    event.query.queryKey[0] === 'briefing-audio'
  ) {
    const audio = event.query.state.data as BriefingAudio | undefined
    if (audio) URL.revokeObjectURL(audio.url)
  }
})
export const useBriefingAudio = (briefingId?: string) =>
  useQuery({
    queryKey: ['briefing-audio', briefingId],
    enabled: !!briefingId,
    staleTime: Infinity,
    gcTime: 5 * 60 * 1000,
    queryFn: async ({ signal }): Promise<BriefingAudio> => {
      const response = await request(
        '/briefings/' + briefingId + '/audio',
        'GET',
        undefined,
        signal,
      )
      const blob = await response.blob()
      signal.throwIfAborted()
      return { url: URL.createObjectURL(blob) }
    },
  })
