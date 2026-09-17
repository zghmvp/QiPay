/** CDP: ops-calc-rider-picker-not-truncated — 未选=全量写死；第 201+ 人走 GET calc-riders */
import { siteLevelOpenPeriod, siteMonth } from '../cycle1-lib.mjs';
import {
  ALL_RIDERS_COPY,
  PICKER_RIDER_201_JOB,
  TRUNCATED_COPY,
  fetchPeriodCalcRiders,
} from '../cycle3-lib.mjs';

export const name = 'ops-calc-rider-picker-not-truncated';

const RIDER_201_ID = 9201;
const UNSELECTED_ALL = '未选 = 计算本周期全部骑手';
const TRUNCATED_HINT = '仅列出前 200 人，其余请搜索';

function riderRow(index) {
  const id = index === 201 ? RIDER_201_ID : 8000 + index;
  const job = index === 201 ? PICKER_RIDER_201_JOB : `FIX_C3_R${String(index).padStart(3, '0')}`;
  return {
    id,
    job_no: job,
    name: `选人夹具${index}`,
  };
}

function pagePayload({ keyword, pageNo, size }) {
  if (keyword.includes(PICKER_RIDER_201_JOB) || keyword.includes('R201') || keyword.includes('D0201')) {
    return {
      items: [riderRow(201)],
      total: 1,
      page: 1,
      size,
      listed_count: 1,
      truncated: false,
      truncated_hint: null,
      unselected_means_all: UNSELECTED_ALL,
    };
  }
  const start = (pageNo - 1) * size + 1;
  const items = [];
  for (let i = start; i < start + size && i <= 200; i += 1) {
    items.push(riderRow(i));
  }
  return {
    items,
    total: 201,
    page: pageNo,
    size,
    listed_count: items.length,
    truncated: true,
    truncated_hint: TRUNCATED_HINT,
    unselected_means_all: UNSELECTED_ALL,
  };
}

export async function run({ page, helpers, config }) {
  const admin = await helpers.swaggerLogin(config.username, config.password);
  await helpers.injectAdmin(page, admin.access_token, admin.user?.uuid ?? null);
  const token = admin.access_token;
  const { siteId, month } = siteMonth();
  const period = await siteLevelOpenPeriod({ apiUrl: config.apiUrl, token, siteId, month });
  if (!period?.id) throw new Error('本站无开放周期');

  const live = await fetchPeriodCalcRiders(config.apiUrl, token, period.id, {
    keyword: PICKER_RIDER_201_JOB,
    page: 1,
    size: 200,
  });
  if (!live.res.ok) {
    throw new Error(
      `GET /periods/{id}/calc-riders 失败 HTTP ${live.res.status}，不得 skip：${JSON.stringify(live.json).slice(0, 200)}`,
    );
  }

  const calcRiderUrls = [];
  page.on('request', (req) => {
    if (req.method() === 'GET' && /\/periods\/\d+\/calc-riders/.test(req.url())) {
      calcRiderUrls.push(req.url());
    }
  });

  await page.route('**/api/v1/rider-salary/periods/*/calc-riders**', async (route) => {
    const req = route.request();
    if (req.method() !== 'GET') {
      await route.continue();
      return;
    }
    const url = new URL(req.url());
    const keyword = url.searchParams.get('keyword') || '';
    const pageNo = Number(url.searchParams.get('page') || '1');
    const size = Number(url.searchParams.get('size') || '200');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        msg: '成功',
        data: pagePayload({ keyword, pageNo, size }),
      }),
    });
  });

  const calcBodies = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/periods\/\d+\/calculate$/.test(req.url())) {
      calcBodies.push(req.postData() || '');
    }
  });
  await page.route('**/api/v1/rider-salary/periods/*/calculate', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        msg: '成功',
        data: {
          calculated: 1,
          failed: [],
          queued: false,
          warnings: [],
          calculated_rider_ids: [RIDER_201_ID],
        },
      }),
    });
  });

  await page.goto(`${config.adminUrl}/rider-salary/period/${period.id}/calculate`, {
    waitUntil: 'networkidle',
    timeout: 60000,
  });

  const hint = page.getByTestId('period-calc-riders-unselected-all');
  try {
    await hint.waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    throw new Error(
      '未选骑手须中文写死「未选 = 计算本周期全部骑手」（period-calc-riders-unselected-all），不得 skip',
    );
  }
  const hintText = await hint.innerText();
  if (!ALL_RIDERS_COPY.test(hintText)) {
    throw new Error(`未选=全量文案须写死：${hintText}`);
  }

  const truncated = page.getByTestId('period-calc-riders-truncated');
  try {
    await truncated.waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    throw new Error('可见列表不是全集时须说明「仅列出前 N 人，其余请搜索」（period-calc-riders-truncated）');
  }
  const truncText = await truncated.innerText();
  if (!TRUNCATED_COPY.test(truncText)) {
    throw new Error(`截断说明须含「仅列出前 N 人，其余请搜索」：${truncText}`);
  }

  const picker = page.getByTestId('period-calc-riders');
  await picker.waitFor({ state: 'visible', timeout: 15000 });
  await picker.click();
  const search = page.locator('.ant-select-selection-search-input, input[type="search"]').last();
  if (await search.count()) {
    await search.fill(PICKER_RIDER_201_JOB);
  } else {
    await page.keyboard.type(PICKER_RIDER_201_JOB);
  }
  await page.waitForTimeout(400);
  const searched = calcRiderUrls.filter((url) => {
    try {
      return new URL(url).searchParams.get('keyword');
    } catch {
      return /keyword=/.test(url);
    }
  });
  if (!searched.length) {
    throw new Error(
      `搜索须走 GET /periods/{id}/calc-riders?keyword=。实际：${calcRiderUrls.join(' | ') || '(无)'}`,
    );
  }
  const opt = page
    .locator('.ant-select-dropdown:visible .ant-select-item-option')
    .filter({ hasText: new RegExp(PICKER_RIDER_201_JOB) })
    .first();
  try {
    await opt.waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    throw new Error(`搜索须能勾到第 201 人工号 ${PICKER_RIDER_201_JOB}。没有第 201 人可搜 = FAIL`);
  }
  await opt.click();

  const start = page.getByTestId('period-calc-start');
  if (await start.isEnabled().catch(() => false)) {
    await start.click();
  } else {
    await page.evaluate(() => {
      document.querySelector('[data-testid="period-calc-start"]')?.click();
    });
  }
  await page.waitForTimeout(500);
  if (!calcBodies.length) {
    throw new Error('选中第 201 人后须 POST /calculate');
  }
  const body = calcBodies[calcBodies.length - 1];
  let parsed = {};
  try {
    parsed = JSON.parse(body);
  } catch {
    parsed = {};
  }
  const ids = parsed.rider_ids;
  if (ids == null) {
    throw new Error('选中子集后不得 POST rider_ids=null 全量');
  }
  const list = Array.isArray(ids) ? ids : [ids];
  if (!list.map(Number).includes(RIDER_201_ID)) {
    throw new Error(`提交 rider_ids 须含第 201 人 id=${RIDER_201_ID}，实际 ${body}`);
  }

  helpers.assertNoPaymentTaxCopy(await page.locator('body').innerText());
  await helpers.shot(page, 'cdp-ops-calc-rider-picker-not-truncated');
}
