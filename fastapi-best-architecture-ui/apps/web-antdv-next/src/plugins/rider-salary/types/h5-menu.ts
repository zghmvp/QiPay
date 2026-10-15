export interface H5Menu {
  show_adjustments: boolean;
  show_advance: boolean;
  show_notices: boolean;
  show_plan: boolean;
  show_home: boolean;
  show_home_pay: boolean;
  show_day_amount: boolean;
  show_estimate_net: boolean;
  show_advance_inflight: boolean;
  site_id: number;
  site_name: string;
  source: 'builtin' | 'global' | 'site';
}
