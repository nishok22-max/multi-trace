import type { Schemas } from '../lib/api/client';
import { asRecord, fmt, localDay, localHour, num } from '../lib/format';

type Claim = Schemas['ClaimRecord'];

function Confidence({ claim }: { claim: Claim }) {
  return (
    <p className="text-sm" data-testid="confidence">
      Confidence {fmt(claim.confidence.value)}{' '}
      <span className="rounded bg-slate-200 px-1 text-xs font-semibold">
        {claim.confidence.calibrated ? 'calibrated' : 'uncalibrated'}
      </span>
    </p>
  );
}

function dayLabel(claim: Claim, tz: string): string {
  const vt = claim.temporal.valid_time;
  return 'start' in vt ? localDay(vt.start, tz) : 'time unknown';
}

/** The note side: the quoted sentence and exactly where it sits in the document. */
export function TextClaimPanel({
  claim,
  synthetic,
  tz,
}: {
  claim: Claim;
  synthetic: boolean;
  tz: string;
}) {
  const ev = claim.evidence;
  const span = ev && ev.kind === 'text_span' ? ev : null;
  return (
    <section aria-label="Text claim" data-testid="text-claim" className="rounded border border-slate-400 bg-white p-3">
      <h3 className="font-bold">
        <span data-testid="claim-label">{claim.label ?? claim.claim_id}</span> · written note
        {synthetic ? (
          <span className="ml-2 rounded bg-amber-100 px-1 text-xs font-semibold text-amber-900">
            synthetic (written for the demo)
          </span>
        ) : null}
      </h3>
      <p className="text-sm text-slate-700">Says: {dayLabel(claim, tz)}, operating state “{String(claim.value)}”</p>
      {span ? (
        <>
          <blockquote data-testid="quote" className="my-2 border-l-4 border-slate-500 pl-2 italic">
            {span.quote}
          </blockquote>
          <p className="font-mono text-xs text-slate-700">
            {span.source_id} · page {span.page ?? 'n/a'} · line {span.line ?? 'n/a'} · chars {span.char_start}–
            {span.char_end}
          </p>
        </>
      ) : null}
      <Confidence claim={claim} />
    </section>
  );
}

/** The sensor side. Every figure is read from the claim values the engine computed. */
export function SensorClaimPanel({
  claim,
  child,
  threshold,
  tz,
}: {
  claim: Claim;
  child: Claim | undefined;
  threshold: number | null | undefined;
  tz: string;
}) {
  const value = asRecord(claim.value);
  const peak = child ? asRecord(child.value) : null;
  const ev = claim.evidence;
  const window = ev && ev.kind === 'sensor_window' ? ev : null;
  const peakStart = child && 'start' in child.temporal.valid_time ? child.temporal.valid_time.start : null;
  return (
    <section aria-label="Sensor claim" data-testid="sensor-claim" className="rounded border border-slate-400 bg-white p-3">
      <h3 className="font-bold">
        <span data-testid="claim-label">{claim.label ?? claim.claim_id}</span> · sensor day
        <span className="ml-2 rounded bg-slate-200 px-1 text-xs font-semibold">sensor units (undocumented)</span>
      </h3>
      <p className="text-sm text-slate-700">
        {dayLabel(claim, tz)}, state “{String(value?.['state'] ?? 'n/a')}”
      </p>
      <dl className="my-2 grid grid-cols-2 gap-x-3 gap-y-1 text-sm" data-testid="sensor-numbers">
        <dt>T_D (robust max-z)</dt>
        <dd data-testid="t-d" className="font-mono font-semibold">
          {fmt(num(value?.['T_D']))}
        </dd>
        <dt>T* (conformal threshold)</dt>
        <dd data-testid="t-star" className="font-mono font-semibold">
          {fmt(threshold ?? num(value?.['T_star']))}
        </dd>
        {peak ? (
          <>
            <dt>Peak</dt>
            <dd data-testid="peak" className="font-mono font-semibold">
              {String(peak['channel'])} {fmt(num(peak['reading']))}
              {peakStart ? ` at ${localHour(peakStart, tz)}` : ''}
            </dd>
            <dt>Alarm band</dt>
            <dd className="font-mono">
              {fmt(num(peak['band_low']))} to {fmt(num(peak['band_high']))}
            </dd>
          </>
        ) : null}
        {window ? (
          <>
            <dt>Coverage</dt>
            <dd className="font-mono">
              {window.n_points} of {window.expected_points} readings
            </dd>
          </>
        ) : null}
      </dl>
      <Confidence claim={claim} />
    </section>
  );
}
