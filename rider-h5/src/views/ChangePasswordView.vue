<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Field, Form, NavBar, showToast } from 'vant'
import { updateMyPassword } from '@/api/auth'

const router = useRouter()
const saving = ref(false)
const form = reactive({
  old_password: '',
  new_password: '',
  confirm_password: '',
})

async function onSubmit() {
  if (!form.old_password || !form.new_password || !form.confirm_password) {
    showToast('请完整填写密码')
    return
  }
  if (form.new_password !== form.confirm_password) {
    showToast('两次输入的新密码不一致')
    return
  }
  if (form.new_password === form.old_password) {
    showToast('新密码不能与当前密码相同')
    return
  }
  saving.value = true
  try {
    await updateMyPassword({ ...form })
    showToast('密码已更新')
    await router.replace('/home')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div>
    <NavBar title="修改初始密码" />
    <div class="page-body">
      <p class="hint">请先修改初始密码。完成后才能查看薪资、预支和公告。</p>
      <Form class="card-block" @submit="onSubmit">
        <Field v-model="form.old_password" type="password" label="原密码" placeholder="请输入初始密码" />
        <Field v-model="form.new_password" type="password" label="新密码" placeholder="请输入新密码" />
        <Field v-model="form.confirm_password" type="password" label="确认密码" placeholder="再次输入新密码" />
        <div class="actions">
          <Button round block type="primary" native-type="submit" :loading="saving">保存并继续</Button>
        </div>
      </Form>
    </div>
  </div>
</template>

<style scoped>
.hint {
  margin: 12px 4px;
  color: var(--ink-soft, #5c564e);
  font-size: 14px;
  line-height: 1.5;
}

.actions {
  padding: 12px;
}
</style>
