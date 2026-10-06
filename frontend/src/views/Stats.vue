<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const s = ref<any>({})
onMounted(async () => { s.value = await api('/seating/stats?hall_id=1') })
</script>
<template>
  <h1>统计</h1>
  <p class="sub">排座占用与违规汇总 · 前排占用与名额已耗同一套数</p>
  <div class="card" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem">
    <div><div class="muted">已排座</div><div class="stat">{{ s.seated }}</div></div>
    <div><div class="muted">未排上</div><div class="stat">{{ s.unplaced }}</div></div>
    <div><div class="muted">违规数</div><div class="stat">{{ s.violations }}</div></div>
    <div><div class="muted">座位容量</div><div class="stat">{{ s.capacity }}</div></div>
  </div>
  <div class="card">
    <h2 style="font-size:0.95rem;margin:0 0 0.5rem;font-family:'Segoe UI','PingFang SC',sans-serif">前排名额台账（最新方案快照）</h2>
    <template v-if="s.quota && s.quota.enabled">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem">
        <div><div class="muted">前排占用（图）</div><div class="stat">{{ s.front_occupied }}</div></div>
        <div><div class="muted">名额已耗（账）</div><div class="stat">{{ s.quota_used }}</div></div>
        <div><div class="muted">名额总额</div><div class="stat">{{ s.quota_total }}</div></div>
        <div><div class="muted">剩余名额</div><div class="stat">{{ s.quota.quota_remaining }}</div></div>
        <div><div class="muted">特殊考生在前排</div><div class="stat">{{ s.quota.special_seated_front }}</div></div>
        <div><div class="muted">前排行数</div><div class="stat">{{ s.quota.front_rows }}</div></div>
      </div>
      <p class="muted" style="margin-top:0.5rem">名额已耗与前排占用同源于最新方案快照，图账一致</p>
</template>
    <p v-else class="muted">前排行数为 0，名额账已关闭（现网模式）。</p>
  </div>
</template>
