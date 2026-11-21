<template>
  <div v-if="data">
    <div class="page-hd">
      <div>
        <p class="muted" style="margin: 0 0 6px">
          <router-link to="/reports">报告库</router-link>
          · {{ data.product?.name }}
        </p>
        <h1>{{ data.title }}</h1>
        <div class="chips">
          <span class="tag tag-type">{{ data.type_label }}</span>
          <span class="tag" v-for="(n, k) in data.result_summary" :key="k" :class="'res-' + (k || 'empty')">
            {{ label(k) }} {{ n }}
          </span>
        </div>
      </div>
    </div>
    <div class="card block">
      <h3>版本</h3>
      <div class="versions">
        <button v-for="v in data.versions" :key="v" :class="{ active: v === cur.version }" @click="switchVersion(v)">{{ v }}</button>
      </div>
    </div>
    <div class="card block" v-if="cur.conclusion || cur.summary">
      <h3>结论</h3>
      <p class="pre">{{ cur.conclusion || cur.summary }}</p>
    </div>
    <div class="card block">
      <h3>关联用例（{{ data.cases.length }}）</h3>
      <table class="data" v-if="data.cases.length">
        <thead>
          <tr><th>编号</th><th>标题</th><th>用例版本</th><th>结果</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="c in data.cases" :key="c.link_id">
            <td><router-link class="key" :to="caseLink(c)">{{ c.key }}</router-link></td>
            <td>{{ c.title }}</td>
            <td class="mono muted">{{ c.case_version || "未钉版本" }}</td>
            <td><span class="tag" :class="'res-' + (c.result || 'empty')">{{ c.result_label }}</span></td>
            <td><button class="btn danger" @click="remove(c)">解除</button></td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">尚未解析到可对齐的用例，可在下方手动补扣。</div>
      <form class="link-form" @submit.prevent="addLink">
        <input v-model="searchKey" placeholder="用例编号，如 TC-OPA-001" style="min-width:220px" />
        <select v-model="linkResult">
          <option value="">结果（可选）</option>
          <option value="pass">通过</option>
          <option value="fail">失败</option>
          <option value="skip">跳过</option>
          <option value="blocked">阻塞</option>
          <option value="untested">未测</option>
        </select>
        <button class="btn" type="submit">补扣关联</button>
        <span class="err" v-if="linkError">{{ linkError }}</span>
      </form>
    </div>
    <div class="card block" v-if="cur.id">
      <h3>原始文件预览</h3>
      <iframe class="preview-frame" :src="`/api/report-versions/${cur.id}/preview`" sandbox="allow-same-origin allow-scripts allow-popups allow-forms"></iframe>
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
const searchKey = ref("");
const linkResult = ref("");
const linkError = ref("");
const cur = computed(() => data.value?.current || {});
const labels = { pass: "通过", fail: "失败", skip: "跳过", blocked: "阻塞", untested: "未测", empty: "未记录" };
const label = (k) => labels[k] || k;

function caseLink(c) {
  return c.case_version ? `/cases/${c.case_id}?version=${c.case_version}` : `/cases/${c.case_id}`;
}

async function load() {
  error.value = "";
  data.value = await api.report(props.id, route.query.version).catch((e) => {
    error.value = e.message;
    return null;
  });
}

function switchVersion(v) {
  router.replace({ query: { version: v } });
}

async function addLink() {
  linkError.value = "";
  try {
    const productId = data.value.product?.id;
    const found = await api.cases({ q: searchKey.value.trim(), product_id: productId, page_size: 10 });
    const match = found.items.find((c) => c.key.toLowerCase() === searchKey.value.trim().toLowerCase()) || found.items[0];
    if (!match) throw new Error("未找到该用例");
    const detail = await api.case(match.id, cur.value.version);
    const cv = detail.versions.includes(cur.value.version) ? detail.current.id : null;
    await api.createLink({
      report_version_id: cur.value.id,
      case_id: match.id,
      case_version_id: cv,
      result: linkResult.value,
    });
    searchKey.value = "";
    await load();
  } catch (e) {
    linkError.value = e.message;
  }
}

async function remove(c) {
  if (!confirm(`解除 ${c.key} 的关联？`)) return;
  await api.deleteLink(c.link_id);
  await load();
}

watch(() => [props.id, route.query.version], load);
onMounted(load);
</script>
