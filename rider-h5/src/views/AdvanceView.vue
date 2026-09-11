<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Button, Empty, Field, Form, NavBar, showConfirmDialog, showToast, Step, Steps, Tag } from 'vant'
import AppTabbar from '@/components/AppTabbar.vue'
import MoneyText from '@/components/MoneyText.vue'
import { cancelAdvance, createAdvance, getAdvanceLimit, getAdvances } from '@/api/me'
import {
  ADVANCE_STATUS_OPTIONS,
  enumColor,
  enumLabel,
  vantTagType,
} from '@/constants/enums'
import { moneyNumber } from '@/utils/money'
import { toDateTimeString } from '@/utils/date'
import type { AdvanceDetail, AdvanceLimit } from '@/types'

const loading = ref(true)
const submitting = ref(false)
const limit = ref<AdvanceLimit | null>(null)
const list = ref<AdvanceDetail[]>([])
const form = reactive({
  amount: '',
  reason: '',
})

const available = computed(() => moneyNumber(limit.value?.available))
const canSubmit = computed(() => available.value > 0)

function canCancel(item: AdvanceDetail) {
  return item.status === 'pending' || item.status === 'draft'
}

async function load() {
  loading.value = true
  try {
    const [limitRes, listRes] = await Promise.all([getAdvanceLimit(), getAdvances()])
    limit.value = limitRes
    list.value = listRes
  } finally {
    loading.value = false
  }
}

async function onSubmit() {
  const amount = Number(form.amount)
  if (!Number.isFinite(amount) || amount <= 0) {
    showToast('请输入大于 0 的预支金额')
    return
  }
  if (amount > available.value) {
    showToast(`可用额度为 ${available.value.toFixed(2)} 元`)
    return
  }
  if (!form.reason.trim()) {
    showToast('请填写申请原因')
    return
  }
  submitting.value = true
  try {
    await createAdvance({ amount, reason: form.reason.trim() })
    showToast('预支申请已提交')
    form.amount = ''
    form.reason = ''
    await load()
  } finally {
    submitting.value = false
  }
}

async function onCancel(item: AdvanceDetail) {
  try {
    await showConfirmDialog({
      title: '撤回申请',
      message: '撤回后需重新申请。是否撤回？',
    })
  } catch {
    return
  }
  await cancelAdvance(item.id)
  showToast('已撤回')
  await load()
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div>
    <NavBar title="预支" />
    <div class="page-body">
      <section v-if="limit" class="waybill">
        <p class="waybill-kicker">可申请额度</p>
        <p class="waybill-amount display-num"><MoneyText :value="limit.available" /></p>
        <div class="metric-grid">
          <div>
            <span class="label">上限</span>
            <span class="value"><MoneyText :value="limit.limit" /></span>
          </div>
          <div>
            <span class="label">在途</span>
            <span class="value"><MoneyText :value="limit.used_pending_amount" /></span>
          </div>
        </div>
        <p v-if="available <= 0" class="muted">当前无法预支，请联系站点</p>
      </section>

      <div class="section-title"><span>申请预支</span></div>
      <Form class="card-block" @submit="onSubmit">
        <Field
          v-model="form.amount"
          type="number"
          label="金额"
          placeholder="请输入金额"
          :disabled="!canSubmit"
        />
        <Field
          v-model="form.reason"
          type="textarea"
          rows="2"
          label="原因"
          placeholder="请填写申请原因"
          :disabled="!canSubmit"
        />
        <div class="actions">
          <Button
            round
            block
            type="primary"
            native-type="submit"
            :loading="submitting"
            :disabled="!canSubmit"
          >
            提交申请
          </Button>
        </div>
      </Form>

      <div class="section-title"><span>我的预支</span></div>
      <Empty v-if="!loading && !list.length" description="暂无预支记录" />
      <article v-for="item in list" :key="item.id" class="card-block item">
        <header>
          <strong class="display-num"><MoneyText :value="item.amount" /></strong>
          <Tag round :type="vantTagType(enumColor(ADVANCE_STATUS_OPTIONS, item.status))">
            {{ item.status_label || enumLabel(ADVANCE_STATUS_OPTIONS, item.status) }}
          </Tag>
        </header>
        <p>{{ item.reason }}</p>
        <p class="muted">申请时间 {{ toDateTimeString(item.submit_time || item.created_time) }}</p>
        <Steps v-if="item.timeline?.length" direction="vertical" :active="item.timeline.length" active-color="#ff7a1a">
          <Step v-for="(node, idx) in item.timeline" :key="idx">
            <p>{{ node.action }} · {{ node.operator_name }}</p>
            <p class="muted">{{ toDateTimeString(node.operate_time) }} {{ node.reason || '' }}</p>
          </Step>
        </Steps>
        <Button v-if="canCancel(item)" size="small" plain type="danger" @click="onCancel(item)">
          撤回
        </Button>
      </article>
    </div>
    <AppTabbar />
  </div>
</template>

<style scoped>
.actions {
  padding: 12px;
}

.item {
  padding: 12px;
  margin-bottom: 10px;
}

.item header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.item p {
  margin: 6px 0;
}
</style>
