<template>
  <div v-if="data">
    <div class="page-hd">
      <div>
        <p class="muted" style="margin: 0 0 6px">
          <router-link to="/cases">用例库</router-link>
          · {{ data.product?.name }}
        </p>
        <h1 class="mono" style="font-size: 26px">{{ data.key }}</h1>
        <div class="chips">
          <span v-if="cur.priority" class="tag" :class="'tag-' + cur.priority.toLowerCase()">{{ cur.priority }}</span>
          <span class="tag tag-type">{{ cur.module || "未分模块" }}</span>
          <span v-if="cur.client" class="tag">{{ cur.client }}</span>
        </div>
      </div>
      <div style="display:flex;gap:8px">
        <router-link class="btn" :to="`/cases/${data.id}/edit?version=${cur.version}`">保存为新版本</router-link>
      </div>
    </div>
    <div class="card block">
      <h3>版本</h3>
      <div class="versions">
        <button
          v-for="v in data.versions"
          :key="v"
          :class="{ active: v === cur.version }"
          @click="switchVersion(v)"
        >{{ v }}</button>
      </div>
    </div>
    <div class="card block">
      <h3>用例描述</h3>
      <p class="pre">{{ cur.title || cur.description }}</p>
    </div>
    <div class="grid-2">
      <div class="card block"><h3>前置步骤</h3><pre class="pre">{{ cur.preconditions || "—" }}</pre></div>
      <div class="card block"><h3>操作步骤</h3><pre class="pre">{{ cur.steps || "—" }}</pre></div>
    </div>
    <div class="card block">
      <h3>预期结果</h3>
      <pre class="pre">{{ cur.expected || "—" }}</pre>
    </div>
    <div class="card block">
      <h3>关联报告（{{ data.reports.length }}）</h3>
      <table class="data" v-if="data.reports.length">
        <thead>
          <tr><th>报告</th><th>类型</th><th>报告版本</th><th>对准用例版本</th><th>结果</th></tr>
        </thead>
        <tbody>
          <tr v-for="r in data.reports" :key="r.link_id">
            <td><router-link :to="`/reports/${r.report_id}?version=${r.report_version}`">{{ r.title }}</router-link></td>
            <td><span class="tag tag-type">{{ r.type_label }}</span></td>
            <td class="mono">{{ r.report_version }}</td>
            <td class="mono muted">{{ r.case_version || "未钉版本" }}</td>
            <td><span class="tag" :class="'res-' + (r.result || 'empty')">{{ r.result_label }}</span></td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">尚未关联报告</div>
    </div>
    <div class="card block" v-if="cur.source_file">
      <h3>原始文件预览</h3>
      <iframe class="preview-frame" :src="`/api/case-versions/${cur.id}/preview`" sandbox="allow-same-origin allow-scripts allow-popups"></iframe>
    </div>
  </div>
  <p v-else-if="error" class="err">{{ error }}</p>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api";

const props = defineProps({ id: [String, Number] });
const route = useRoute();
const router = useRouter();
const data = ref(null);
const error = ref("");
const cur = computed(() => data.value?.current || {});

async function load() {
  error.value = "";
  try {
    data.value = await api.case(props.id, route.query.version);
  } catch (e) {
    error.value = e.message;
  }
}

function switchVersion(v) {
  router.replace({ query: { version: v } });
}

watch(() => [props.id, route.query.version], load);
onMounted(load);
</script>
