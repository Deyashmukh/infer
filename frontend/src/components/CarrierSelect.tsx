import type { Carrier } from '../api'

interface CarrierSelectProps {
  onSelect: (carrier: Carrier) => void
}

export function CarrierSelect({ onSelect }: CarrierSelectProps) {
  return (
    <div className="carrier-select">
      <h2>Select your carrier</h2>
      <div className="carrier-list">
        <button
          className="carrier-btn active"
          onClick={() => onSelect('liberty_mutual')}
        >
          Liberty Mutual
        </button>
        <button className="carrier-btn disabled" disabled title="Coming soon">
          Geico — coming soon
        </button>
      </div>
    </div>
  )
}
