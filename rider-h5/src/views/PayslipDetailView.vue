<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Empty, NavBar, Skeleton } from 'vant'
import MoneyText from '@/components/MoneyText.vue'
import { getPayslip } from '@/api/me'
import type { MePayslipDetail, MePayslipLine } from '@/types'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const failed = ref(false)
const detail = ref<MePayslipDetail | null>(null)
let requestSeq = 0

const slipId = computed(() => Number(route.params.id))

const groups = computed(() => {
  const map = new Map<string, MePayslipLine[]>()
  for (const line of detail.value?.lines ?? []) {
    const key = line.stage_label || line.stage || '其他'
    const rows = map.get(key) ?? []
    rows.push(line)
    map.set(key, rows)
  }
  return [...map.entries()]
})

async function load() {
  const seq = ++requestSeq
  loading.value = true
  failed.value = false
  const id = slipId.value
  if (!Number.isInteger(id) || id <= 0) {
    detail.value = null
    failed.value = true
    loading.value = false
    return
  }
  try {
    const data = await getPayslip(id)
    if (seq !== requestSeq) return
    detail.value = data
  } catch {
    if (seq !== requestSeq) return
    detail.value = null
    failed.value = true
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

watch(
  slipId,
  () => {
    void load()
  },
  { immediate: true },
)
</script>

<template>
  <div>
    <NavBar title="工资条明细" left-arrow @click-left="router.back()" />
    <div v-if="loading" class="page-body no-tab">
      <Skeleton title :row="6" />
    </div>
    <div v-else-if="failed || !detail" class="page-body no-tab">
      <Empty description="工资条不存在或已失效">
        <button type="button" class="retry" @click="load">重试</button>
      </Empty>
    </div>
    <div v-else class="page-body no-tab">
      <section class="waybill">
        <p class="waybill-kicker">实发 · {{ detail.period_range }}</p>
        <p class="waybill-amount display-num"><MoneyText :value="detail.net" /></p>
        <p class="muted">
          {{ detail.status_label }} · {{ detail.kind_label }} · {{ detail.period_status_label }}
        </p>
        <div class="metric-grid">
          <div>
            <span class="label">单量</span>
            <span class="value display-num">{{ detail.order_count }}</span>
          </div>
          <div>
            <span class="label">应发</span>
            <span class="value"><MoneyText :value="detail.gross" /></span>
          </div>
          <div>
            <span class="label">代扣</span>
            <span class="value"><MoneyText :value="detail.deduction_total" /></span>
          </div>
          <div>
            <span class="label">预支抵扣</span>
            <span class="value"><MoneyText :value="detail.advance_deduction" /></span>
          </div>
        </div>
      </section>

      <Empty v-if="!groups.length" description="这张工资条没有明细" />
      <section v-for="[stage, lines] in groups" :key="stage">
        <div class="section-title"><span>{{ stage }}</span></div>
        <article v-for="(line, index) in lines" :key="`${stage}-${index}`" class="card-block line">
          <div>
            <strong>{{ line.subject_name }}</strong>
            <p class="muted">
              {{ line.source_label }}
              <template v-if="line.line_count > 1"> · 共 {{ line.line_count }} 笔</template>
            </p>
          </div>
          <MoneyText :value="line.amount" />
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
.line {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  margin-bottom: 8px;
}

.line p {
  margin: 4px 0 0;
}

.retry {
  margin-top: 8px;
  border: 0;
  background: var(--vis);
  color: #fff;
  border-radius: 999px;
  padding: 6px 14px;
}
</style>
