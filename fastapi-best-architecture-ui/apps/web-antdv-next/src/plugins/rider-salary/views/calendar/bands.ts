import type { CalendarPlanBand } from '../../types/calendar';

import { buildMonthMatrix } from '../../utils/date';

export interface BandSlice {
  color: string;
  colEnd: number;
  colStart: number;
  continued: boolean;
  end: string;
  key: string;
  label: string;
  planVersionId: null | number;
  shortName: string;
  start: string;
  tooltip: string;
  weekIndex: number;
}

function dateKey(value: string) {
  return String(value).slice(0, 10);
}

/** 将服务端 plan_bands 按周一行切开；填补格不画带；换周续接加 ↳ */
export function splitPlanBandsByWeek(
  month: string,
  bands: CalendarPlanBand[],
): BandSlice[] {
  const matrix = buildMonthMatrix(month);
  const slices: BandSlice[] = [];

  bands.forEach((band, bandIndex) => {
    if (band.plan_version_id == null) return;
    if (!band.color) return;
    const bandStart = dateKey(band.start);
    const bandEnd = dateKey(band.end);
    const shortName = (band.short_name || '方案').slice(0, 6);

    matrix.forEach((week, weekIndex) => {
      const cols: number[] = [];
      week.forEach((day, col) => {
        if (day.format('YYYY-MM') !== month) return;
        const key = day.format('YYYY-MM-DD');
        if (key >= bandStart && key <= bandEnd) cols.push(col);
      });
      if (cols.length === 0) return;

      let runStart = cols[0]!;
      let prev = cols[0]!;
      const flush = (from: number, to: number) => {
        const start = week[from]!.format('YYYY-MM-DD');
        const end = week[to]!.format('YYYY-MM-DD');
        const continued = start !== bandStart;
        slices.push({
          color: band.color as string,
          colEnd: to,
          colStart: from,
          continued,
          end,
          key: `${bandIndex}-${weekIndex}-${from}-${to}`,
          label: continued ? `↳ ${shortName}` : shortName,
          planVersionId: band.plan_version_id ?? null,
          shortName,
          start,
          tooltip: `${band.short_name || '方案'} · ${bandStart} ~ ${bandEnd}`,
          weekIndex,
        });
      };
      for (let i = 1; i < cols.length; i += 1) {
        const col = cols[i]!;
        if (col !== prev + 1) {
          flush(runStart, prev);
          runStart = col;
        }
        prev = col;
      }
      flush(runStart, prev);
    });
  });

  return slices;
}

export function slicesForWeek(slices: BandSlice[], weekIndex: number) {
  return slices.filter((item) => item.weekIndex === weekIndex);
}
