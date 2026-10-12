export interface NoticeResult {
  content: string;
  created_time: string;
  id: number;
  is_top: boolean;
  publish_time?: null | string;
  publisher_id: number;
  site_id?: null | number;
  status: string;
  status_label?: string;
  title: string;
  updated_time?: null | string;
}

export interface NoticeForm {
  content: string;
  is_top?: boolean;
  site_id?: null | number;
  title: string;
}

export interface NoticeQuery {
  page?: number;
  site_id?: number;
  size?: number;
  status?: string;
  title?: string;
}
