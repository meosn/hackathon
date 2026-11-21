import { Lock } from 'lucide-react'
import { Button, Modal } from '../../components/UI'

export function PremiumNotice({ onClose }: { onClose: () => void }) {
  return <Modal title="Premium character" onClose={onClose}>
    <div className="premium-message"><Lock size={28} /><p>This character is available with Premium only.</p></div>
    <Button onClick={onClose}>Got it</Button>
  </Modal>
}
