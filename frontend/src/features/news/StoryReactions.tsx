import { useMutation } from '@tanstack/react-query'
import { ThumbsUp, ThumbsDown } from 'lucide-react'
import { api, queryClient, useApi } from '../../api/client'
import { ErrorNote } from '../../components/UI'

export function StoryReactions({ storyId }: { storyId: string }) {
  const saved = useApi<{ score: number }>('/feedback/' + storyId)
  const reaction = useMutation({
    mutationFn: ({ id, score }: { id: string; score: number }) => api('/feedback/' + id, 'PUT', { score }),
    onSuccess: (_, value) => {
      queryClient.setQueryData(['/feedback/' + value.id], { score: value.score })
      void queryClient.invalidateQueries({ predicate: q => String(q.queryKey[0]).startsWith('/recommendations') })
    },
  })
  return <div className="story-reactions" aria-label="Personalize future stories">
    <button type="button" title="More like this" aria-label="More like this" aria-pressed={saved.data?.score === 1} disabled={reaction.isPending} onClick={() => reaction.mutate({ id: storyId, score: saved.data?.score === 1 ? 0 : 1 })}><ThumbsUp size={15} /></button>
    <button type="button" title="Less like this" aria-label="Less like this" aria-pressed={saved.data?.score === -1} disabled={reaction.isPending} onClick={() => reaction.mutate({ id: storyId, score: saved.data?.score === -1 ? 0 : -1 })}><ThumbsDown size={15} /></button>
    <ErrorNote error={reaction.error} />
  </div>
}

export function coverageLabel(status?: string, publishers = 0) {
  if (status === 'conflicting') return 'Reports disagree · compare sources'
  if (status === 'corroborated') return 'Shared claims corroborated · ' + publishers + ' publishers'
  if (status === 'multiple_reports') return 'Compared across ' + publishers + ' publishers'
  return publishers === 1 ? 'Single publisher · not independently corroborated' : 'Not independently corroborated'
}
