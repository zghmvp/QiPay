import type { RiderQuery } from '../../types/rider';

/** 远程搜索每页条数。不再一次性拉前 200 人。 */
export const RIDER_REMOTE_PAGE_SIZE = 50;

/** 旧算薪弹窗一次性拉取的上限，第 201 名及之后选不到。 */
export const LEGACY_RIDER_PAGE_SIZE = 200;

/** 算薪接口单次指定骑手的上限，超出则改为计算全部。 */
export const CALCULATE_RIDER_ID_LIMIT = 500;

export interface RiderSearchHit {
  id: number;
  job_no: string;
  name: string;
}

export interface RiderSelectOption {
  label: string;
  value: number;
}

/** 按站点远程搜索骑手。有关键字才带 keyword，避免把空串当成筛选。 */
export function buildRiderSearchQuery(input: {
  keyword?: string;
  page?: number;
  siteId: number;
}): RiderQuery {
  const keyword = input.keyword?.trim();
  return {
    page: input.page ?? 1,
    site_id: input.siteId,
    size: RIDER_REMOTE_PAGE_SIZE,
    ...(keyword ? { keyword } : {}),
  };
}

/** 与后端 keyword 一致：工号或姓名包含关键字，忽略大小写。 */
export function filterRidersByKeyword(
  riders: RiderSearchHit[],
  keyword: string,
): RiderSearchHit[] {
  const text = keyword.trim().toLowerCase();
  if (!text) return riders;
  return riders.filter(
    (item) =>
      item.job_no.toLowerCase().includes(text) ||
      item.name.toLowerCase().includes(text),
  );
}

/** 默认列表按 id 倒序时，名次从 1 开始。 */
export function ridersByNewestFirst(total: number): RiderSearchHit[] {
  return Array.from({ length: total }, (_, index) => {
    const id = total - index;
    return {
      id,
      job_no: `R${String(id).padStart(4, '0')}`,
      name: `骑手${id}`,
    };
  });
}

export function toRiderOption(item: {
  id: number;
  job_no?: null | string;
  name?: null | string;
}): RiderSelectOption {
  const label = [item.job_no, item.name].filter(Boolean).join(' ');
  return { label: label || String(item.id), value: item.id };
}

/** 已选骑手留在选项里，换关键字搜索时标签不会变成裸 ID。 */
export function mergeRiderOptions(
  pinned: RiderSelectOption[],
  fetched: RiderSelectOption[],
): RiderSelectOption[] {
  const seen = new Set<number>();
  const result: RiderSelectOption[] = [];
  for (const item of [...pinned, ...fetched]) {
    if (seen.has(item.value)) continue;
    seen.add(item.value);
    result.push(item);
  }
  return result;
}

export function pinSelectedRiders(
  selectedIds: number[],
  known: RiderSelectOption[],
): RiderSelectOption[] {
  const byId = new Map(known.map((item) => [item.value, item]));
  return selectedIds.map(
    (id) => byId.get(id) ?? { label: String(id), value: id },
  );
}

/** 名单不超过上限时只算这些人；超过上限改为不传 ID，即计算全部。 */
export function supplementCalculateParam(riderIds: number[]): {
  rider_ids: null | number[];
} {
  if (!riderIds.length || riderIds.length > CALCULATE_RIDER_ID_LIMIT) {
    return { rider_ids: null };
  }
  return { rider_ids: riderIds };
}
