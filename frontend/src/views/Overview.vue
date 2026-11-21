<template>
  <div>
    <div class="page-hd">
      <div>
        <h1>总览</h1>
        <p>用例、报告与版本关联的当前库存。</p>
      </div>
    </div>
    <p v-if="error" class="err">{{ error }}</p>
    <div class="kpi-grid" v-if="data">
      <div class="card kpi" v-for="item in kpis" :key="item.label">
        <div class="label">{{ item.label }}</div>
        <div class="num"><em>{{ item.value }}</em></div>
      </div>
    </div>
    <div class="grid-2" v-if="data">
      <div class="card">
        <div class="section-title">产品分布</div>
        <div class="prod-row muted" style="padding-top: 16px">
          <span>产品</span><span>用例</span><span>用例版本</span><span>报告</span><span>关联</span>
        </div>
        <div class="prod-row" v-for="p in data.by_product" :key="p.id">
          <strong>{{ p.name }}</strong>
          <span class="mono">{{ p.cases }}</span>
          <span class="mono">{{ p.case_versions }}</span>
          <span class="mono">{{ p.reports }}</span>
          <span class="mono">{{ p.links }}</span>
        </div>
      </div>
      <div class="card">
        <div class="section-title">关联结果概况</div>
        <div class="prod-row" v-for="row in resultRows" :key="row.key">
          <span class="tag" :class="'res-' + (row.key || 'empty')">{{ row.label }}</span>
          <span class="mono">{{ row.value }}</span>
        </div>
        <div v-if="!resultRows.length" class="empty">暂无关联</div>
      </div>
    </div>
    <div class="grid-2" style="margin-top: 16px" v-if="data">
      <div class="card">
        <div class="section-title">最近用例版本</div>
        <router-link
          class="recent-row"
          v-for="c in data.recent_cases"
          :key="c.case_id + c.version"
          :to="`/cases/${c.case_id}?version=${c.version}`"
        >
          <span class="mono">{{ c.key }}</span>
          <span>{{ c.title }}</span>
          <span class="muted mono">{{ c.version }}</span>
        </router-link>
      </div>
      <div class="card">
        <div class="section-title">最近报告版本</div>
        <router-link
          class="recent-row"
          v-for="r in data.recent_reports"
          :key="r.report_id + r.version"
          :to="`/reports/${r.report_id}?version=${r.version}`"
        >
          <span>{{ r.product }} · {{ r.title }}</span>
          <span class="tag tag-type">{{ r.type_label }}</span>
          <span class="muted mono">{{ r.version }}</span>
        </router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { api } from "../api";

const data = ref(null);
const error = ref("");
const labels = { pass: "通过", fail: "失败", skip: "跳过", blocked: "阻塞", untested: "未测", empty: "未记录" };

const kpis = computed(() => {
  if (!data.value) return [];
  const d = data.value;
  return [
    { label: "产品", value: d.products },
    { label: "用例", value: d.cases },
    { label: "用例版本", value: d.case_versions },
    { label: "报告", value: d.reports },
    { label: "报告版本", value: d.report_versions },
    { label: "关联", value: d.links },
  ];
});

const resultRows = computed(() => {
  const r = data.value?.results || {};
  return Object.entries(r).map(([key, value]) => ({
    key,
    value,
    label: labels[key] || key,
  }));
});

onMounted(async () => {
  try {
    data.value = await api.overview();
  } catch (e) {
    error.value = e.message;
  }
});
</script>
