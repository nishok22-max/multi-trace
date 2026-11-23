import ReactECharts from 'echarts-for-react';
import { sensorChartOption, type EnvelopeLike, type Row } from '../lib/chart/options';

interface Props {
  rows: Row[];
  channels: string[];
  envelope: EnvelopeLike | null;
  tStar: number | null;
  tz: string;
}

/** The sensor proof: readings, the learned alarm band (med +/- T*·s), missing hours as holes.
 *  The band is the alarm threshold, labelled as such; the readings are in undocumented sensor units. */
export default function SensorChart({ rows, channels, envelope, tStar, tz }: Props) {
  const option = sensorChartOption({ rows, channels, envelope, tStar, tz });
  return (
    <figure data-testid="sensor-chart" aria-label="Sensor readings with the alarm band">
      <ReactECharts option={option} style={{ height: 280, width: '100%' }} notMerge opts={{ renderer: 'canvas' }} />
      <figcaption className="text-xs text-slate-700">
        Shaded band = alarm threshold (median ± T*·s), not the typical range. Sensor units (undocumented). A missing hour is a gap,
        never a value.
      </figcaption>
    </figure>
  );
}
