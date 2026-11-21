import { AudioLines, Glasses } from 'lucide-react'

const portraits: Record<string, string> = {
  professional: 'anchor',
  energetic: 'commentator',
  gangsta: 'street',
  jarvis: 'jarvis',
}

export function SpeakerAvatar({ id }: { id: string }) {
  const portrait = portraits[id]
  return (
    <span className="speaker-avatar" aria-hidden="true">
      {id === 'granny' ? <Glasses size={30} strokeWidth={1.4} /> : portrait ? (
        <img src={`/speakers/${portrait}.webp`} alt="" width={256} height={256} />
      ) : (
        <AudioLines size={22} strokeWidth={1.4} />
      )}
    </span>
  )
}
