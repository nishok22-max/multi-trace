import type { Schemas } from '../lib/api/client';
import { asRecord, fmt, localDay, localHour, num } from '../lib/format';

type Claim = Schemas['ClaimRecord'];

function Confidence({ claim }: { claim: Claim }) {
  return (
    <p className="conf" data-testid="confidence">
      Confidence <strong className="num">{fmt(claim.confidence.value)}</strong>
      <span className={`badge ${claim.confidence.calibrated ? 'badge-ok' : 'badge-warn'}`}>
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
    <section aria-label="Text claim" data-testid="text-claim" className="claim">
      <p className="eyebrow">Written note</p>
      <h3>
        <span data-testid="claim-label">{claim.label ?? claim.claim_id}</span>
        {synthetic ? <span className="badge badge-warn">synthetic (written for the demo)</span> : null}
      </h3>
      <p className="says">
        Says: {dayLabel(claim, tz)}, operating state “{String(claim.value)}”
      </p>
      {span ? (
        <>
          <blockquote data-testid="quote">{span.quote}</blockquote>
          <p className="pointer">
            {span.source_id} · page {span.page ?? 'n/a'} · line {span.line ?? 'n/a'} · chars {span.char_start}–{span.char_end}
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
    <section aria-label="Sensor claim" data-testid="sensor-claim" className="claim">
      <p className="eyebrow">Sensor day</p>
      <h3>
        <span data-testid="claim-label">{claim.label ?? claim.claim_id}</span>
        <span className="badge">sensor units (undocumented)</span>
      </h3>
      <p className="says">
        {dayLabel(claim, tz)}, state “{String(value?.['state'] ?? 'n/a')}”
      </p>
      <dl className="kv" data-testid="sensor-numbers">
        <dt>T_D (robust max-z)</dt>
        <dd data-testid="t-d">{fmt(num(value?.['T_D']))}</dd>
        <dt>T* (conformal threshold)</dt>
        <dd data-testid="t-star">{fmt(threshold ?? num(value?.['T_star']))}</dd>
        {peak ? (
          <>
            <dt>Peak</dt>
            <dd data-testid="peak">
              {String(peak['channel'])} {fmt(num(peak['reading']))}
              {peakStart ? ` at ${localHour(peakStart, tz)}` : ''}
            </dd>
            <dt>Alarm band</dt>
            <dd>
              {fmt(num(peak['band_low']))} to {fmt(num(peak['band_high']))}
            </dd>
          </>
        ) : null}
        {window ? (
          <>
            <dt>Coverage</dt>
            <dd>
              {window.n_points} of {window.expected_points} readings
            </dd>
          </>
        ) : null}
      </dl>
      <Confidence claim={claim} />
    </section>
  );
}
