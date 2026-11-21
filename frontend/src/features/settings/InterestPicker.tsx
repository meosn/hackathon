import { useState } from 'react'
import { Check, Plus, X } from 'lucide-react'
import { label } from '../../api/client'

export function InterestPicker({ topics, selected, custom, onChange }: {
  topics: string[]; selected: string[]; custom: string[];
  onChange: (selected: string[], custom: string[]) => void
}) {
  const [adding, setAdding] = useState(false), [name, setName] = useState('')
  const options = [...new Set([...topics, ...custom, ...selected])]
  function add() {
    const topic = name.trim().toLowerCase().replace(/\s+/g, '_')
    if (!topic) return
    onChange([...new Set([...selected, topic])], topics.includes(topic) ? custom : [...new Set([...custom, topic])])
    setName('')
  }
  return <>
    <div className="interest-options">
      {options.map(topic => <span className="interest-option" key={topic}>
        <button type="button" aria-pressed={selected.includes(topic)} onClick={() => onChange(selected.includes(topic) ? selected.filter(t => t !== topic) : [...selected, topic], custom)}>
          {selected.includes(topic) && <Check size={14} />}{label(topic)}
        </button>
        {custom.includes(topic) && !topics.includes(topic) && <button type="button" className="delete-interest" aria-label={'Delete topic ' + label(topic)} title="Delete topic" onClick={() => onChange(selected.filter(t => t !== topic), custom.filter(t => t !== topic))}><X size={12} /></button>}
      </span>)}
    </div>
    {adding ? <div className="custom-interest">
      <label className="sr-only" htmlFor="custom-interest">Custom interest</label>
      <input autoFocus id="custom-interest" value={name} onChange={e => setName(e.target.value)} maxLength={100} placeholder="Enter a topic" onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); add() }; if (e.key === 'Escape') setAdding(false) }} />
      <button className="btn outline" type="button" disabled={!name.trim() || custom.length >= 50 || selected.length >= 50} onClick={add}>Add</button>
      <button type="button" className="icon" aria-label="Close custom interest" onClick={() => setAdding(false)}><X size={16} /></button>
    </div> : <button className="preference-text-button" type="button" onClick={() => setAdding(true)}><Plus size={15} /> Add your own topic</button>}
  </>
}
