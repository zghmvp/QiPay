<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, Field, Form, showToast } from 'vant'
import { getCaptcha, login } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const form = reactive({
  username: '',
  password: '',
  captcha: '',
})
const uuid = ref('')
const imageSrc = ref('')
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null
let captchaSeq = 0

function captchaSrc(image: string) {
  const mime = image.startsWith('/9j/') ? 'image/jpeg' : 'image/png'
  return `data:${mime};base64,${image}`
}

async function refreshCaptcha() {
  const seq = ++captchaSeq
  const res = await getCaptcha()
  if (seq !== captchaSeq) return
  uuid.value = res.uuid
  imageSrc.value = captchaSrc(res.image)
  if (timer) clearTimeout(timer)
  if (res.is_enabled && res.expire_seconds > 0) {
    const delay = Math.max((res.expire_seconds - 3) * 1000, 1000)
    timer = setTimeout(() => {
      void refreshCaptcha()
    }, delay)
  }
}

async function onSubmit() {
  if (!form.username || !form.password || !form.captcha) {
    showToast('请填写工号、密码和验证码')
    return
  }
  loading.value = true
  try {
    const res = await login({
      username: form.username.trim(),
      password: form.password,
      captcha: form.captcha.trim(),
      uuid: uuid.value,
    })
    auth.saveToken(res.access_token)
    await auth.loadProfile()
    showToast('登录成功')
    await router.replace('/home')
  } catch {
    form.captcha = ''
    void refreshCaptcha()
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void refreshCaptcha()
})

onUnmounted(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="login">
    <header class="hero">
      <p class="waybill-kicker">RIDER PAY STUB</p>
      <h1>骑手薪资</h1>
      <p>账号由站点开通，用户名为工号</p>
    </header>
    <Form class="card-block form" @submit="onSubmit">
      <Field
        v-model="form.username"
        name="username"
        label="工号"
        placeholder="请输入工号"
        autocomplete="username"
      />
      <Field
        v-model="form.password"
        type="password"
        name="password"
        label="密码"
        placeholder="请输入密码"
        autocomplete="current-password"
      />
      <Field
        v-model="form.captcha"
        name="captcha"
        label="验证码"
        placeholder="不区分大小写"
        maxlength="8"
        autocomplete="off"
      />
      <button type="button" class="captcha" @click="refreshCaptcha">
        <img v-if="imageSrc" :src="imageSrc" alt="图形验证码，点击刷新" />
        <span v-else>验证码加载中</span>
        <span class="captcha-tip">看不清？点击刷新</span>
      </button>
      <div class="actions">
        <Button round block type="primary" native-type="submit" :loading="loading">
          登录
        </Button>
      </div>
    </Form>
  </div>
</template>

<style scoped>
.login {
  min-height: 100vh;
  min-height: 100dvh;
  background: linear-gradient(180deg, #15202b 0 220px, var(--paper) 220px);
  padding: 48px 18px 24px;
}

.hero {
  color: #f4efe6;
  margin-bottom: 24px;
}

.hero h1 {
  margin: 8px 0 6px;
  font-size: 32px;
  letter-spacing: 0.08em;
}

.hero p:last-child {
  opacity: 0.72;
  font-size: 13px;
}

.form {
  padding: 8px 8px 18px;
}

.actions {
  padding: 16px 12px 4px;
}

.captcha {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: calc(100% - 24px);
  margin: 4px 12px 0;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: #f0ebe3;
}

.captcha img {
  width: 180px;
  height: 60px;
  object-fit: contain;
  image-rendering: auto;
  background: #fff;
  border-radius: 4px;
}

.captcha-tip {
  color: #8a8175;
  font-size: 12px;
}
</style>
