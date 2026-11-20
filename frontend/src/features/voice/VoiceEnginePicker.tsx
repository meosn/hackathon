import { useApi } from '../../api/client'
import { ErrorNote } from '../../components/UI'
import type { VoiceEngine } from './voiceChoice'

type Engine = { id: VoiceEngine; name: string; available: boolean; description: string }

export function VoiceEnginePicker({ value, onChange, disabled = false }: {
  value: string; onChange: (engine: VoiceEngine) => void; disabled?: boolean
}) {
  const engines = useApi<Engine[]>('/voice-engines')
  return (
    <div className="voice-engine-picker">
      <div className="voice-engine-options" role="group" aria-label="Voice model">
        {(engines.data || []).map(engine => (
          <button type="button" key={engine.id} aria-pressed={value === engine.id}
            disabled={disabled || !engine.available} onClick={() => onChange(engine.id)}
            title={engine.available ? engine.description : 'This voice provider is not configured yet.'}>
            {engine.name}
          </button>
        ))}
      </div>
      <ErrorNote error={engines.error} />
    </div>
  )
}
