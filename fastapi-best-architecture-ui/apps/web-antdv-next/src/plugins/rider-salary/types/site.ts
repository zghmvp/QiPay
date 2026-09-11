export interface SiteResult {
  advance_limit?: null | number | string;
  code: string;
  created_time: string;
  cycle_config?: null | Record<string, unknown>;
  dept_id?: null | number;
  id: number;
  manager_count?: number;
  name: string;
  remark?: null | string;
  settle_cycle: string;
  settle_cycle_label?: string;
  status: string;
  status_label?: string;
  updated_time?: null | string;
}

export interface SiteForm {
  advance_limit?: null | number | string;
  code: string;
  cycle_config?: null | Record<string, unknown>;
  dept_id?: null | number;
  name: string;
  remark?: null | string;
  settle_cycle: string;
  status: string;
}

export interface SiteQuery {
  code?: string;
  name?: string;
  page?: number;
  size?: number;
  status?: string;
}

export interface SiteManagerResult {
  nickname: string;
  role: string;
  role_label?: string;
  user_id: number;
  username: string;
}

export interface SiteManagerItem {
  role: 'deputy' | 'owner';
  user_id: number;
}
