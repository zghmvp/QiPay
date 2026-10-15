import type { H5Menu } from '../types/h5-menu';

import { requestClient } from '#/api/request';

const BASE = '/api/v1/rider-salary/h5-menus';

export async function getH5MenuApi(siteId: number) {
  return requestClient.get<H5Menu>(BASE, { params: { site_id: siteId } });
}

export async function saveH5MenuApi(data: Omit<H5Menu, 'site_name' | 'source'>) {
  return requestClient.put<H5Menu>(BASE, data);
}
