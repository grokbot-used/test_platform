<template>
  <div class="doc-page version-info-page">
    <div class="doc-shell">
      <div class="doc-hero">
        <div class="hero-row">
          <button class="btn-export" type="button" @click="goBack">返回用例库</button>
          <h1>版本信息</h1>
          <span v-if="productName" class="chip">{{ productName }}</span>
        </div>
        <p class="hero-sub">左侧选择用例版本，右侧展示该版本文档的附加信息</p>
      </div>

      <p v-if="error" class="err">{{ error }}</p>
      <div v-else class="version-info-layout">
        <aside class="version-tree-card">
          <h2>版本</h2>
          <p v-if="loadingTree" class="muted">正在加载…</p>
          <p v-else-if="!versions.length" class="muted">暂无用例版本</p>
          <ol v-else class="version-tree">
            <li
              v-for="(ver, index) in versions"
              :key="ver"
              class="version-node"
              :class="{ selected: ver === selectedVersion, latest: index === 0 }"
            >
              <button type="button" @click="selectVersion(ver)">
                <span class="node-dot" aria-hidden="true"></span>
                <span class="node-label">{{ ver }}</span>
                <span v-if="index === 0" class="node-badge">最新</span>
              </button>
            </li>
          </ol>
        </aside>

        <section class="version-info-pane">
          <header class="version-info-pane-hd">
            <h2>{{ selectedVersion || "版本信息" }}</h2>
          </header>
          <div class="version-info-pane-body">
            <p v-if="loadingPane" class="muted">正在加载…</p>
            <iframe
              v-else-if="caseInfoPage"
              class="review-frame review-srcdoc version-info-frame"
              :srcdoc="caseInfoPage"
              sandbox="allow-same-origin allow-popups"
              title="版本信息"
            ></iframe>
            <dl v-else-if="caseInfoFields.length" class="review-fields case-info-fields">
              <template v-for="field in caseInfoFields" :key="field.label">
                <dt>{{ field.label }}</dt>
                <dd>{{ field.value }}</dd>
              </template>
            </dl>
            <p v-else class="modal-msg">当前用例文档没有可展示的额外信息</p>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api";

const route = useRoute();
const router = useRouter();

const products = ref([]);
const productId = ref("");
const versions = ref([]);
const selectedVersion = ref("");
const caseInfoCache = ref({});
const loadingTree = ref(false);
const loadingPane = ref(false);
const error = ref("");

const productName = computed(() => {
  const found = products.value.find((item) => String(item.id) === String(productId.value));
  return found?.name || "";
});

const currentInfo = computed(() => caseInfoCache.value[selectedVersion.value] || {
  available: false,
  title: "",
  fields: [],
  fragment_page: "",
});
const caseInfoPage = computed(() => (
  typeof currentInfo.value.fragment_page === "string" ? currentInfo.value.fragment_page : ""
));
const caseInfoFields = computed(() => currentInfo.value.fields || []);

function errorText(e) {
  const raw = e?.message ?? e;
  if (raw == null) return "请求失败";
  if (typeof raw === "string") return raw;
  return String(raw);
}

function goBack() {
  const query = productId.value ? { product_id: String(productId.value) } : {};
  router.push({ path: "/cases", query });
}

async function loadPane(version) {
  if (!productId.value || !version) return;
  if (caseInfoCache.value[version]) return;
  loadingPane.value = true;
  try {
    const data = await api.caseDocs({
      product_id: productId.value,
      version,
      page: 1,
      page_size: 1,
    });
    versions.value = [...(data.versions || [])].sort((a, b) => compareVersion(b, a));
    caseInfoCache.value = {
      ...caseInfoCache.value,
      [data.version || version]: data.case_info || { available: false, title: "", fields: [], fragment_page: "" },
    };
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loadingPane.value = false;
  }
}

function compareVersion(a, b) {
  const nums = (value) => String(value || "").match(/\d+/g)?.map((n) => parseInt(n, 10)) || [0];
  const left = nums(a);
  const right = nums(b);
  const len = Math.max(left.length, right.length);
  for (let i = 0; i < len; i += 1) {
    const diff = (left[i] || 0) - (right[i] || 0);
    if (diff) return diff;
  }
  return String(a).localeCompare(String(b));
}

async function selectVersion(version) {
  if (!version || version === selectedVersion.value) {
    selectedVersion.value = version;
    return;
  }
  selectedVersion.value = version;
  await loadPane(version);
}

async function bootstrap() {
  error.value = "";
  loadingTree.value = true;
  try {
    products.value = await api.products();
    const requested = String(route.query.product_id || "");
    const match = products.value.find((item) => String(item.id) === requested);
    productId.value = String((match || products.value[0])?.id || "");
    if (!productId.value) {
      versions.value = [];
      return;
    }
    const data = await api.caseDocs({
      product_id: productId.value,
      page: 1,
      page_size: 1,
    });
    const ordered = [...(data.versions || [])].sort((a, b) => compareVersion(b, a));
    versions.value = ordered;
    const latest = data.version || ordered[0] || "";
    selectedVersion.value = latest;
    if (latest) {
      caseInfoCache.value = {
        ...caseInfoCache.value,
        [latest]: data.case_info || { available: false, title: "", fields: [], fragment_page: "" },
      };
    }
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loadingTree.value = false;
  }
}

watch(() => route.query.product_id, bootstrap, { immediate: true });
</script>
