/** Display formatting only. No number is ever produced here: values come from the API. */
export function fmt(value: number | null | undefined): string {
  return value === null || value === undefined ? 'n/a' : value.toFixed(2);
}

export function localDateTime(utc: string, timeZone: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone,
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(utc));
}

export function localHour(utc: string, timeZone: string): string {
  return new Intl.DateTimeFormat('en-GB', { timeZone, hour: '2-digit', minute: '2-digit', hour12: false }).format(
    new Date(utc),
  );
}

export function localDay(utc: string, timeZone: string): string {
  return new Intl.DateTimeFormat('en-GB', { timeZone, day: '2-digit', month: 'short', year: 'numeric' }).format(
    new Date(utc),
  );
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function num(value: unknown): number | null {
  return typeof value === 'number' ? value : null;
}
