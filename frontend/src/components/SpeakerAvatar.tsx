import { AudioLines } from 'lucide-react'

const portraits: Record<string, string> = {
  granny: 'granny.jpg',
  professional: 'anchor.webp',
  energetic: 'commentator.webp',
  gangsta: 'street.webp',
  jarvis: 'jarvis.webp',
}

export function SpeakerAvatar({ id }: { id: string }) {
  const portrait = portraits[id]
  return (
    <span className="speaker-avatar" aria-hidden="true">
      {portrait ? (
        <img src={`/speakers/${portrait}`} alt="" width={256} height={256} />
      ) : (
        <AudioLines size={22} strokeWidth={1.4} />
      )}
    </span>
  )
}
