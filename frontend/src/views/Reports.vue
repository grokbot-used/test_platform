<template>
  <div>
    <div class="page-hd">
      <div>
        <h1>报告库</h1>
        <p>黑盒与白盒报告，按产品、类型和版本过滤。</p>
      </div>
    </div>
    <div class="filters">
      <input v-model="q" placeholder="搜索标题、结论…" @keyup.enter="load(1)" />
      <select v-model="productId" @change="load(1)">
        <option value="">全部产品</option>
        <option v-for="p in products" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
      </select>
      <select v-model="type" @change="load(1)">
        <option value="">全部类型</option>
        <option v-for="t in meta.report_types || []" :key="t.value" :value="t.value">{{ t.label }}</option>
      </select>
      <select v-model="version" @change="load(1)">
        <option value="">全部版本</option>
        <option v-for="v in meta.report_versions || []" :key="v" :value="v">{{ v }}</option>
      </select>
      <button class="btn" @click="load(1)">筛选</button>
    </div>
    <p v-if="error" class="err">{{ error }}</p>
    <div class="card" style="overflow:auto">
      <table class="data">
        <thead>
          <tr>
            <th>报告</th>
            <th>产品</th>
            <th>类型</th>
            <th>版本</th>
            <th>关联用例</th>
            <th>结论摘要</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in items" :key="r.id">
            <td><router-link :to="`/reports/${r.id}`">{{ r.title }}</router-link></td>
            <td class="muted">{{ r.product?.name }}</td>
            <td><span class="tag tag-type">{{ r.type_label }}</span></td>
            <td class="mono">{{ r.latest_version }} <span class="muted">×{{ r.version_count }}</span></td>
            <td class="mono">{{ r.link_count }}</td>
            <td class="muted">{{ r.summary }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!items.length && !error" class="empty">没有匹配的报告</div>
    </div>
    <div class="pager" v-if="total">
      <span>共 {{ total }} 条</span>
      <span>
        <button class="btn ghost" :disabled="page<=1" @click="load(page-1)">上一页</button>
        <span style="margin: 0 10px">{{ page }} / {{ pages }}</span>
        <button class="btn ghost" :disabled="page>=pages" @click="load(page+1)">下一页</button>
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { api } from "../api";

const products = ref([]);
const meta = ref({});
const items = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 30;
const q = ref("");
const productId = ref("");
const type = ref("");
const version = ref("");
const error = ref("");
const pages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));

async function load(p = 1) {
  page.value = p;
  error.value = "";
  try {
    const data = await api.reports({
      q: q.value,
      product_id: productId.value,
      type: type.value,
      version: version.value,
      page: page.value,
      page_size: pageSize,
    });
    items.value = data.items;
    total.value = data.total;
  } catch (e) {
    error.value = e.message;
  }
}

onMounted(async () => {
  products.value = await api.products();
  meta.value = await api.meta(productId.value || undefined);
  await load(1);
});
</script>
