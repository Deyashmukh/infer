import { useState } from 'react'
import type { Carrier } from '../api'

interface CarrierSelectProps {
  onSelect: (carrier: Carrier) => void
}

export function CarrierSelect({ onSelect }: CarrierSelectProps) {
  const [carrier, setCarrier] = useState<Carrier | ''>('')

  function handleContinue() {
    if (carrier) onSelect(carrier)
  }

  return (
    <div className="step">
      <p className="step-label">Step 1 of 2</p>
      <h2>Select your carrier</h2>
      <p className="step-hint">
        Choose the insurer you want to pull your policy documents from.
      </p>

      <div className="field">
        <label htmlFor="carrier">Carrier</label>
        <div className="select-wrap">
          <select
            id="carrier"
            value={carrier}
            onChange={(e) => setCarrier(e.target.value as Carrier)}
          >
            <option value="" disabled>
              Select a carrier…
            </option>
            <option value="liberty_mutual">Liberty Mutual</option>
            <option value="geico">Geico</option>
          </select>
        </div>
      </div>

      <button className="btn-primary" disabled={!carrier} onClick={handleContinue}>
        Continue
      </button>
    </div>
  )
}
