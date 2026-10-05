<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const drafts = ref<Record<number, number>>({})
const busy = ref<Record<number, boolean>>({})
const errors = ref<Record<number, string>>({})
const saved = ref<Record<number, string>>({})

onMounted(async () => {
  rows.value = await api('/halls')
  for (const r of rows.value) drafts.value[r.id] = r.front_rows ?? 0
})

async function save(r: any) {
  const front_rows = Number(drafts.value[r.id])
  errors.value[r.id] = ''
  saved.value[r.id] = ''
  busy.value[r.id] = true
  try {
    const res = await api(`/halls/${r.id}/front-rows`, {
      method: 'PUT',
      body: JSON.stringify({ front_rows }),
    })
    r.front_rows = res.hall.front_rows
    drafts.value[r.id] = res.hall.front_rows
    saved.value[r.id] = `已保存 · 名额已耗 ${res.quota.quota_used}/${res.quota.quota_total}`
  } catch (e: any) {
    // 拒绝保存：行数、台账、最新方案三处停在拒绝前
    drafts.value[r.id] = r.front_rows
    errors.value[r.id] = e?.message || '保存失败'
  } finally {
    busy.value[r.id] = false
  }
}
</script>
<template>
  <h1>考室</h1>
  <p class="sub">前排行数 0 = 关闭名额账、退回现网；负数或超过考室行数将拒绝保存</p>
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>行</th><th>列</th><th>最小间距</th><th>前排行数</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id ?? JSON.stringify(r)">
          <td>{{ r.code }}</td><td>{{ r.name }}</td><td>{{ r.rows }}</td><td>{{ r.cols }}</td>
          <td>{{ r.min_manhattan }}</td>
          <td>
            <input v-model.number="drafts[r.id]" type="number" min="0" :max="r.rows"
                   style="width:64px" :disabled="busy[r.id]" />
          </td>
          <td>
            <button class="btn" :disabled="busy[r.id]" @click="save(r)">
              {{ busy[r.id] ? '提交中…' : '保存并重排' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-for="r in rows" :key="'m' + r.id">
      <div v-if="errors[r.id]" class="hs-error" style="margin-top:0.5rem">
        <strong>已拒绝，三处未改动：</strong>{{ errors[r.id] }}
      </div>
      <div v-if="saved[r.id]" class="hs-ok" style="margin-top:0.5rem">{{ saved[r.id] }}</div>
    </div>
  </div>
</template>
