<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const busy = ref<Record<number, boolean>>({})
const errors = ref<Record<number, string>>({})

async function load() { rows.value = await api('/candidates') }
onMounted(load)

async function toggle(r: any) {
  errors.value[r.id] = ''
  busy.value[r.id] = true
  try {
    const res = await api(`/candidates/${r.id}/special`, {
      method: 'PATCH',
      body: JSON.stringify({ special: !r.special }),
    })
    r.special = res.candidate.special
  } catch (e: any) {
    // 名额不足：保住名额账优先，标记、台账、方案皆不变
    errors.value[r.id] = e?.message || '修改失败'
  } finally {
    busy.value[r.id] = false
  }
}
</script>
<template>
  <h1>考生名册</h1>
  <p class="sub">★ 特殊考生只能消耗前排名额格；名额不足时标记切换会被整体拒绝</p>
  <div class="hs-clipboard" style="max-width:520px">
    <h2>考生名册 · Clipboard</h2>
    <div v-for="r in rows" :key="r.id ?? JSON.stringify(r)" class="hs-roster-row">
      <div>
        <div>{{ r.name }}<span v-if="r.special" class="hs-special-mark">★特殊</span></div>
        <div class="hs-ticket">{{ r.ticket_no }}</div>
        <div v-if="errors[r.id]" class="hs-error" style="margin-top:0.25rem">
          已拒绝，标记未改：{{ errors[r.id] }}
        </div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:0.25rem">
        <div>卷{{ r.paper_id }} · 室{{ r.hall_id }}</div>
        <button class="btn" style="padding:0.15rem 0.55rem;font-size:0.72rem"
                :disabled="busy[r.id]" @click="toggle(r)">
          {{ r.special ? '取消特殊' : '标为特殊' }}
        </button>
      </div>
    </div>
  </div>
</template>
