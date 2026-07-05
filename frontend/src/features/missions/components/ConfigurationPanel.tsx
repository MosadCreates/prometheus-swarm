'use client';

import { useState } from 'react';
import { Input, Select, Switch } from '@/shared/ui';
import { priorities, executionModes, outputOptions, resourcePresets } from '../constants/mock';

export function ConfigurationPanel() {
  const [name, setName] = useState('');
  const [priority, setPriority] = useState('normal');
  const [mode, setMode] = useState('balanced');
  const [resource, setResource] = useState('medium');
  const [outputs, setOutputs] = useState<string[]>(['code', 'model']);
  const [notify, setNotify] = useState(true);

  const toggleOutput = (val: string) => {
    setOutputs((prev) =>
      prev.includes(val) ? prev.filter((v) => v !== val) : [...prev, val],
    );
  };

  const selectedResource = resourcePresets.find((r) => r.value === resource);

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-3">Configuration</h3>
      </div>

      <Input label="Mission name" placeholder="Optional name" value={name} onChange={(e) => setName(e.target.value)} />

      <Select label="Priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
        {priorities.map((p) => (
          <option key={p.value} value={p.value}>{p.label}</option>
        ))}
      </Select>

      <Select label="Execution mode" value={mode} onChange={(e) => setMode(e.target.value)}>
        {executionModes.map((m) => (
          <option key={m.value} value={m.value}>{m.label}</option>
        ))}
      </Select>

      <div>
        <Select label="Compute" value={resource} onChange={(e) => setResource(e.target.value)}>
          {resourcePresets.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </Select>
        {selectedResource && (
          <div className="flex gap-3 mt-1.5 text-[11px] text-[var(--color-text-muted)]">
            <span>{selectedResource.cpu}</span>
            <span>{selectedResource.memory}</span>
            <span>{selectedResource.storage}</span>
          </div>
        )}
      </div>

      <div>
        <p className="text-[var(--text-label)] font-medium text-[var(--color-text-primary)] mb-2">Expected outputs</p>
        <div className="flex flex-wrap gap-1.5">
          {outputOptions.map((o) => {
            const selected = outputs.includes(o.value);
            return (
              <button
                key={o.value}
                onClick={() => toggleOutput(o.value)}
                className={`text-xs px-2.5 py-1 rounded-[var(--radius-sm)] border transition-all ${
                  selected
                    ? 'bg-[var(--color-primary)]/10 text-[var(--color-primary)] border-[var(--color-primary)]/20'
                    : 'bg-transparent text-[var(--color-text-muted)] border-[var(--color-border)] hover:border-[var(--color-primary)]/30'
                }`}
              >
                {o.label}
              </button>
            );
          })}
        </div>
      </div>

      <Switch checked={notify} onChange={setNotify} label="Notify on completion" />
    </div>
  );
}
