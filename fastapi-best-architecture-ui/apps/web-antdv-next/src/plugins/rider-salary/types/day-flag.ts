export interface DayFlagResult {
  bad_weather: boolean;
  biz_date: string;
  created_time?: null | string;
  high_temp: boolean;
  id?: null | number;
  promo: boolean;
  remark?: null | string;
  site_id: number;
  updated_time?: null | string;
}

export interface DayFlagItem {
  bad_weather: boolean;
  biz_date: string;
  high_temp: boolean;
  promo: boolean;
  remark?: null | string;
}

export interface UpsertDayFlagParam {
  days: DayFlagItem[];
  site_id: number;
}
