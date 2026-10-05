<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
const data = ref<any>(null)
const candidates = ref<any[]>([])
const violKeys = ref<Set<string>>(new Set())
const errorMsg = ref('')
const busy = ref(false)

async function loadViolations() {
  try {
    const v = await api('/seating/violations?hall_id=1')
    const keys = new Set<string>()
    for (const x of v.violations || []) {
      if (x.a_id != null) keys.add(String(x.a_id))
      if (x.b_id != null) keys.add(String(x.b_id))
    }
    violKeys.value = keys
  } catch { violKeys.value = new Set() }
}

async function refreshLatest() {
  // 失败后仍展示最新（钉死）方案，不清空座位图；
  // 若从未有过成功方案（/latest 同样被拒绝）则保持空图，不吞掉提示。
  try {
    data.value = await api('/seating/latest?hall_id=1')
    await loadViolations()
  } catch (e: any) {
    if (!data.value) errorMsg.value = e?.message || '排座失败'
  }
}

async function run() {
  busy.value = true
  errorMsg.value = ''
  try {
    data.value = await api('/seating/run?hall_id=1', { method: 'POST' })
    await loadViolations()
  } catch (e: any) {
    // 名额不足：方案条数不增，图仍是上一版
    errorMsg.value = e?.message || '排座失败'
    await refreshLatest()
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  candidates.value = await api('/candidates')
  await refreshLatest()
})

const gridStyle = computed(() => data.value ? ({ gridTemplateColumns: `repeat(${data.value.cols}, 72px)` }) : {})
const quota = computed(() => data.value?.quota || {})
const cells = computed(() => {
  if (!data.value) return []
  const map = new Map<string, any>()
  for (const a of data.value.assignments || []) map.set(a.row + ',' + a.col, a)
  const out: any[] = []
  const frontRows = quota.value.enabled ? (quota.value.front_rows || 0) : 0
  for (let r = 0; r < data.value.rows; r++) {
    for (let c = 0; c < data.value.cols; c++) {
      const cell = map.get(r + ',' + c) || { empty: true, row: r, col: c }
      cell.row = r; cell.col = c
      cell.quotaZone = r < frontRows
      out.push(cell)
    }
  }
  return out
})
function isViol(cell: any) {
  if (cell.empty) return false
  const id = cell.candidate_id ?? cell.id
  return id != null && violKeys.value.has(String(id))
}
function paperClass(pid: number) {
  return pid % 2 === 0 ? 'b' : 'a'
}
</script>
<template>
  <h1>考场课桌网格</h1>
  <p class="sub">课桌网格为主视图 · 前排名额格高亮 · 特殊考生★ · 违规课桌高亮</p>
  <div style="display:flex;align-items:center;gap:1rem;flex-wrap:wrap">
    <button class="btn" :disabled="busy" @click="run">重新排座</button>
    <span v-if="quota.enabled" class="badge badge-warn">
      前排名额：已耗 {{ quota.quota_used }} / {{ quota.quota_total }}
      （前排 {{ quota.front_rows }} 行）
    </span>
    <span v-else class="badge badge-ok">名额账关闭（前排行数 0 · 现网模式）</span>
  </div>
  <div v-if="errorMsg" class="card hs-error">
    <strong>排座被拒绝，方案未增加：</strong>{{ errorMsg }}
  </div>
  <div class="hs-classroom" style="margin-top:0.85rem">
    <aside class="hs-clipboard">
      <h2>考生名册</h2>
      <div v-for="c in candidates" :key="c.id" class="hs-roster-row">
        <div>
          <div>{{ c.name }}<span v-if="c.special" class="hs-special-mark">★特殊</span></div>
          <div class="hs-ticket">{{ c.ticket_no }}</div>
        </div>
        <div>卷{{ c.paper_id }}</div>
      </div>
    </aside>
    <div class="hs-desk-stage" v-if="data">
      <div v-if="quota.enabled" class="hs-quota-label">
        ↑ 前排名额区（第 0 ~ {{ quota.front_rows - 1 }} 行，仅特殊考生★可占用，普通人不得入内）
      </div>
      <div class="hs-grid-board" :style="gridStyle">
        <div
          v-for="(cell,i) in cells" :key="i"
          class="hs-desk"
          :class="{ empty: cell.empty, 'hs-viol': isViol(cell), 'hs-quota-cell': cell.quotaZone, 'hs-special-desk': !cell.empty && cell.special }"
        >
          <template v-if="!cell.empty">
            <span class="hs-paper-tag" :class="paperClass(cell.paper_id)">卷{{ cell.paper_id }}</span>
            <div>{{ cell.name }}<span v-if="cell.special" class="hs-star">★</span></div>
          </template>
          <template v-else>·</template>
        </div>
      </div>
    </div>
  </div>
</template>
