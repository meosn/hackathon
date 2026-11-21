import { useState } from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { InterestPicker } from './InterestPicker'
afterEach(cleanup)
it('keeps a custom topic when deselected and deletes it only through its separate button', () => {
  function Form() {
    const [selected, setSelected] = useState<string[]>([]), [custom, setCustom] = useState<string[]>([])
    return <InterestPicker topics={['politics']} selected={selected} custom={custom} onChange={(s, c) => { setSelected(s); setCustom(c) }} />
  }
  render(<Form />)
  fireEvent.click(screen.getByRole('button', { name: 'Add your own topic' }))
  fireEvent.change(screen.getByRole('textbox', { name: 'Custom interest' }), { target: { value: 'Space Law' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add' }))
  const topic = screen.getByRole('button', { name: 'Space law' })
  expect(topic).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(topic)
  expect(topic).toBeVisible(); expect(topic).toHaveAttribute('aria-pressed', 'false')
  fireEvent.click(topic)
  expect(topic).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Delete topic Space law' }))
  expect(screen.queryByRole('button', { name: 'Space law' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Politics' })).toBeVisible()
})
