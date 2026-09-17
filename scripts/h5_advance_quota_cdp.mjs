import { chromium } from 'playwright'

const H5 = process.env.H5_BASE || 'http://localhost:5174'
const API = process.env.API_BASE || 'http://127.0.0.1:8000'
const ACCESS = process.env.RIDER_TOKEN || ''

function envelope(data) {
  return { code: 200, msg: 'OK', data }
}

function moneyLimit() {
  return {
    limit: 3000,
    used_pending_amount: 0,
    available: 3000,
    monthly_advance_limit: 1,
    used: 0,
    remaining: 1,
    month: '2026-09',
  }
}

function quotaPayload(quota) {
  return {
    monthly_advance_limit: quota.monthly_advance_limit,
    used: quota.used,
    remaining: quota.remaining,
    month: quota.month,
    limit: quota.monthly_advance_limit,
  }
}

const CASES = [
  {
    name: 'default_one',
    quota: { monthly_advance_limit: 1, used: 1, remaining: 0, month: '2026-09' },
    expectText: '本月还可预支 0 次',
    expectBlock: '本月预支次数已用完（2026年9月）',
    submitDisabled: true,
  },
  {
    name: 'site_two',
    quota: { monthly_advance_limit: 2, used: 1, remaining: 1, month: '2026-09' },
    expectText: '本月还可预支 1 次',
    expectBlock: null,
    submitDisabled: false,
  },
  {
    name: 'site_zero',
    quota: { monthly_advance_limit: 0, used: 0, remaining: 0, month: '2026-09' },
    expectText: '本月还可预支 0 次',
    expectBlock: '本站暂不可预支',
    submitDisabled: true,
  },
  {
    name: 'rejected_does_not_consume',
    quota: { monthly_advance_limit: 1, used: 0, remaining: 1, month: '2026-09' },
    expectText: '本月还可预支 1 次',
    expectBlock: null,
    submitDisabled: false,
  },
]

async function swaggerLogin() {
  if (ACCESS) return ACCESS
  const res = await fetch(
    `${API}/api/v1/auth/login/swagger?username=${encodeURIComponent('D5A001')}&password=${encodeURIComponent('Rider@123456')}`,
    { method: 'POST' },
  )
  if (!res.ok) throw new Error(`login failed: ${res.status}`)
  const body = await res.json()
  return body.access_token
}

async function runCase(page, token, item) {
  await page.route('**/api/v1/rider-salary/me/advance-quota', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(envelope(quotaPayload(item.quota))),
    })
  })
  await page.route('**/api/v1/rider-salary/me/advance-limit', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(envelope(moneyLimit())),
    })
  })
  await page.route('**/api/v1/rider-salary/me/advances', async (route) => {
    if (route.request().method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(envelope([])),
      })
      return
    }
    await route.continue()
  })
  await page.goto(`${H5}/login`, { waitUntil: 'domcontentloaded' })
  await page.evaluate((value) => localStorage.setItem('rider_h5_token', value), token)
  await page.goto(`${H5}/advance`, { waitUntil: 'networkidle', timeout: 60000 })
  const body = await page.locator('body').innerText()
  if (!body.includes(item.expectText)) {
    throw new Error(`[${item.name}] missing 「${item.expectText}」 in:\n${body}`)
  }
  if (item.expectBlock && !body.includes(item.expectBlock)) {
    throw new Error(`[${item.name}] missing 「${item.expectBlock}」 in:\n${body}`)
  }
  if (body.includes('请联系站点')) {
    throw new Error(`[${item.name}] leaked 请联系站点`)
  }
  const submit = page.getByRole('button', { name: '提交申请' })
  const disabled = await submit.isDisabled()
  if (disabled !== item.submitDisabled) {
    throw new Error(`[${item.name}] submit disabled=${disabled}, expected ${item.submitDisabled}`)
  }
  console.log('OK', item.name)
}

async function main() {
  const token = await swaggerLogin()
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
  try {
    for (const item of CASES) {
      await runCase(page, token, item)
    }
  } finally {
    await browser.close()
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
