<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Cell, CellGroup, Field, Form, NavBar, showConfirmDialog, showToast } from 'vant'
import AppTabbar from '@/components/AppTabbar.vue'
import { updateMyPassword } from '@/api/auth'
import { getProfile } from '@/api/me'
import { enumLabel, EMPLOY_TYPE_OPTIONS } from '@/constants/enums'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()
const saving = ref(false)
const form = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

onMounted(async () => {
  if (!auth.profile) {
    auth.profile = await getProfile()
  }
})

async function onChangePassword() {
  if (!form.old_password || !form.new_password || !form.confirm_password) {
    showToast('请完整填写密码')
    return
  }
  if (form.new_password !== form.confirm_password) {
    showToast('两次输入的新密码不一致')
    return
  }
  saving.value = true
  try {
    await updateMyPassword({ ...form })
    showToast('密码已更新')
    form.old_password = ''
    form.new_password = ''
    form.confirm_password = ''
  } finally {
    saving.value = false
  }
}

async function onLogout() {
  try {
    await showConfirmDialog({ title: '退出登录', message: '确定退出当前账号？' })
  } catch {
    return
  }
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <div>
    <NavBar title="我的" />
    <div class="page-body">
      <CellGroup inset class="block">
        <Cell title="姓名" :value="auth.profile?.name || '—'" />
        <Cell title="工号" :value="auth.profile?.job_no || '—'" />
        <Cell title="站点" :value="auth.profile?.site_name || '—'" />
        <Cell
          title="用工类型"
          :value="auth.profile?.employ_type_label || enumLabel(EMPLOY_TYPE_OPTIONS, auth.profile?.employ_type)"
        />
        <Cell title="入职日期" :value="auth.profile?.hire_date || '—'" />
      </CellGroup>

      <div class="section-title"><span>修改密码</span></div>
      <Form class="card-block" @submit="onChangePassword">
        <Field v-model="form.old_password" type="password" label="原密码" placeholder="请输入原密码" />
        <Field v-model="form.new_password" type="password" label="新密码" placeholder="请输入新密码" />
        <Field v-model="form.confirm_password" type="password" label="确认密码" placeholder="再次输入新密码" />
        <div class="actions">
          <Button round block type="primary" native-type="submit" :loading="saving">保存密码</Button>
        </div>
      </Form>

      <div class="actions out">
        <Button round block plain type="danger" @click="onLogout">退出登录</Button>
      </div>
    </div>
    <AppTabbar />
  </div>
</template>

<style scoped>
.block {
  margin-top: 8px;
}

.actions {
  padding: 12px;
}

.out {
  padding: 8px 4px 0;
}
</style>
