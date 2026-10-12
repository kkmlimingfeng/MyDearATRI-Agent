import { useEffect, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

const clamp = (value) => Math.max(1, Math.min(500, Math.trunc(value)));

export default function IterationStepper({ value = 5, onChange }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);

  const commit = () => {
    const parsed = Number(draft);
    const next = draft !== '' && Number.isFinite(parsed) ? clamp(parsed) : value;
    setDraft(String(next));
    if (next !== value) onChange(next);
  };
  const step = (amount) => {
    const parsed = Number(draft);
    const next = clamp((Number.isFinite(parsed) && draft !== '' ? parsed : value) + amount);
    setDraft(String(next));
    if (next !== value) onChange(next);
  };

  return <div className="iteration-stepper nodrag nowheel" onPointerDown={(event) => event.stopPropagation()}>
    <input type="text" inputMode="numeric" pattern="[0-9]*" value={draft} aria-label="最大循环次数" onChange={(event) => {
      if (/^\d*$/.test(event.target.value)) setDraft(event.target.value);
    }} onBlur={commit} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur(); }} />
    <div className="iteration-stepper-actions">
      <button type="button" title="增加一次" aria-label="增加一次" onClick={() => step(1)}><ChevronUp size={13} /></button>
      <button type="button" title="减少一次" aria-label="减少一次" onClick={() => step(-1)}><ChevronDown size={13} /></button>
    </div>
  </div>;
}
