import { AudioLines } from 'lucide-react'

const portraits: Record<string, string> = {
  professional: 'anchor',
  energetic: 'commentator',
  casual: 'street',
  jarvis: 'jarvis',
}

export function SpeakerAvatar({ id }: { id: string }) {
  const portrait = portraits[id]
  return (
    <span className="speaker-avatar" aria-hidden="true">
      {portrait ? (
        <img src={`/speakers/${portrait}.webp`} alt="" width={256} height={256} />
      ) : (
        <AudioLines size={22} strokeWidth={1.4} />
      )}
    </span>
  )
}
