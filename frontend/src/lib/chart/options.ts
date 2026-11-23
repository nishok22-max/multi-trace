/** ECharts options for the sensor proof. Nothing here is computed: the alarm band is
 *  `med +/- T* x s` with s = 1.4826 x MAD from the envelope the engine learned, and the readings
 *  are the stored ones. Every string that reaches an ECharts formatter is escaped first (channel
 *  names come from data, and ECharts renders tooltips as HTML). */
export const MAD_TO_SIGMA = 1.4826;

export function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export interface EnvelopeLike {
  med: Record<string, number>;
  mad: Record<string, number>;
  T_star: number;
}

export interface Band {
  low: number;
  high: number;
}

export function alarmBand(envelope: EnvelopeLike, channel: string, tStar: number = envelope.T_star): Band | null {
  const med = envelope.med[channel];
  const mad = envelope.mad[channel];
  if (med === undefined || mad === undefined || mad === 0) return null; // degenerate scale: no band
  const scale = MAD_TO_SIGMA * mad;
  return { low: med - tStar * scale, high: med + tStar * scale };
}

export type Row = Record<string, string | number | null>;

export interface SensorChartInput {
  rows: Row[];
  channels: string[];
  envelope: EnvelopeLike | null;
  /** Threshold of the claim being shown (a single-channel claim has its own T*). */
  tStar: number | null;
  tz: string;
}

function hourLabel(ts: string, tz: string): string {
  return new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false }).format(
    new Date(ts),
  );
}

export function tooltipFormatter(tz: string) {
  return (params: unknown): string => {
    const list = (Array.isArray(params) ? params : [params]) as Array<{
      axisValue?: string;
      seriesName?: string;
      value?: [string, number | null];
    }>;
    const head = list[0]?.axisValue ? escapeHtml(hourLabel(list[0].axisValue, tz)) : '';
    const lines = list
      .filter((p) => p.seriesName !== undefined && !p.seriesName.startsWith('band:'))
      .map((p) => `${escapeHtml(p.seriesName)}: ${escapeHtml(p.value?.[1] ?? 'no reading')}`);
    return [head, ...lines].join('<br/>');
  };
}

/** Line per channel, the alarm band as a shaded `markArea` per channel, missing hours as gaps
 *  (never interpolated: a missing hour is a hole, not a value). */
export function sensorChartOption(input: SensorChartInput): Record<string, unknown> {
  const { rows, channels, envelope, tStar, tz } = input;
  const series: Record<string, unknown>[] = channels.map((channel) => {
    const band = envelope ? alarmBand(envelope, channel, tStar ?? envelope.T_star) : null;
    return {
      name: channel,
      type: 'line',
      showSymbol: true,
      connectNulls: false,
      data: rows.map((r) => [String(r['ts']), typeof r[channel] === 'number' ? r[channel] : null]),
      ...(band
        ? {
            markArea: {
              silent: true,
              itemStyle: { color: 'rgba(100, 116, 139, 0.12)' },
              label: { show: false },
              data: [[{ yAxis: band.low, name: `band:${channel}` }, { yAxis: band.high }]],
            },
          }
        : {}),
    };
  });
  return {
    animation: false,
    tooltip: { trigger: 'axis', formatter: tooltipFormatter(tz) },
    legend: { top: 0 },
    grid: { left: 48, right: 16, top: 32, bottom: 28 },
    xAxis: {
      type: 'category',
      data: rows.map((r) => String(r['ts'])),
      axisLabel: { formatter: (value: string) => escapeHtml(hourLabel(value, tz)) },
    },
    yAxis: { type: 'value', scale: true },
    series,
  };
}
