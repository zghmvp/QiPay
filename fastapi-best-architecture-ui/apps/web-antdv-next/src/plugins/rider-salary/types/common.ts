export interface PageParams {
  page?: number;
  size?: number;
}

export interface PageResult<T> {
  items: T[];
  links?: unknown;
  page: number;
  size: number;
  total: number;
  total_pages: number;
}

export type MoneyValue = null | number | string | undefined;
