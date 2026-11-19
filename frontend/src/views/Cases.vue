<template>
  <div class="doc-page">
    <div class="doc-shell">
      <div class="doc-hero">
        <div class="hero-row">
          <h1>{{ productName || "用例库" }}</h1>
          <span v-if="doc.version" class="chip">{{ doc.version }}</span>
        </div>
        <p class="hero-sub">
          共 {{ doc.total || 0 }} 条 · 每张卡片右侧显示该条在各端的推演结论
        </p>
        <div class="hero-controls">
          <label>需求
            <select v-model="productId" @change="onProductChange">
              <option v-for="p in products" :key="p.id" :value="String(p.id)">{{ p.name }}</option>
            </select>
          </label>
          <label>用例版本
            <select v-model="caseVersion" :disabled="!versions.length" @change="onVersionChange">
              <option v-for="v in versions" :key="v" :value="v">{{ v }}</option>
            </select>
          </label>
        </div>
      </div>

      <div v-if="doc.pending?.length" class="pending">
        <b>待确认（不阻塞出用例，执行前需补齐）</b>
        <ul>
          <li v-for="(item, i) in doc.pending" :key="i">{{ item }}</li>
        </ul>
      </div>

      <div v-if="showPriorityStats" class="priority-stats" aria-label="优先级统计栏">
        <div class="stat-card stat-total">
          <span class="label">用例总数</span>
          <span class="num">{{ priorityStats.total }}</span>
        </div>
        <div
          v-for="p in priorityStats.priorities"
          :key="p.priority"
          class="stat-card"
          :class="'stat-' + (p.priority || '').toLowerCase()"
        >
          <span class="label">{{ p.priority }}（{{ formatPercent(p.percent) }}%）</span>
          <span class="num">{{ p.count }}</span>
        </div>
        <div v-if="(priorityStats.untested || 0) > 0" class="stat-card stat-skip">
          <span class="label">不测</span>
          <span class="num">{{ priorityStats.untested }}</span>
        </div>
      </div>

      <div class="toolbar">
        <label>优先级
          <select v-model="priority" @change="onFilterChange">
            <option value="">全部</option>
            <option v-for="x in priorities" :key="x" :value="x">{{ x }}</option>
          </select>
        </label>
        <label>搜索
          <input v-model="qInput" type="search" placeholder="编号 / 标题 / 字符" />
        </label>
        <button class="btn-export" type="button" @click="exportTable">导出表格</button>
        <button class="btn-export" type="button" @click="openCaseInfo">用例信息</button>
        <label>每页
          <select v-model.number="pageSize" @change="onPageSizeChange">
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
        </label>
        <span class="stats">第 {{ rangeStart }}–{{ rangeEnd }} 条 / 共 {{ doc.total || 0 }} 条</span>
      </div>

      <p v-if="error" class="err">{{ error }}</p>
      <div v-else-if="loading" class="empty">正在加载用例…</div>
      <div v-else-if="!doc.items?.length" class="empty">没有匹配的用例</div>

      <article
        v-for="c in doc.items"
        :key="c.id"
        class="case-card"
        :class="{ selected: selectedId === c.id }"
        @click="selectedId = c.id"
      >
        <div class="case-main">
          <header class="case-hd">
            <span class="num">{{ c.seq || c.key }}</span>
            <span v-if="c.priority" class="tag" :class="'tag-' + (c.priority || '').toLowerCase()">{{ c.priority }}</span>
            <span class="case-title">{{ c.description || c.title || c.key }}</span>
          </header>
          <div class="case-meta">
            <div><span class="k">业务端</span><span class="v">{{ c.client || "—" }}</span></div>
            <div><span class="k">模块</span><span class="v">{{ c.module || "—" }}</span></div>
            <div class="full"><span class="k">用例描述</span><span class="v">{{ c.description || c.title || "—" }}</span></div>
          </div>
          <div class="case-stack">
            <section>
              <h4>前置步骤</h4>
              <BlockText :text="c.preconditions" />
            </section>
            <section>
              <h4>操作步骤</h4>
              <BlockText :text="c.steps" />
            </section>
            <section>
              <h4>预期结果</h4>
              <BlockText :text="c.expected" />
            </section>
          </div>
        </div>
        <aside class="case-entries" aria-label="该用例推演结果入口" @click.stop>
          <button
            v-for="ep in caseEndpoints(c)"
            :key="ep.endpoint || ep.id"
            type="button"
            class="dock-btn"
            :class="dockClass(ep)"
            @click="openReview(ep.endpoint || ep.id, c)"
          >
            <span class="dock-name">{{ ep.label }}</span>
            <span class="dock-result">{{ ep.result_label || "暂无" }}</span>
            <span v-if="ep.available && ep.report_version" class="dock-ver">报告 {{ ep.report_version }}</span>
            <span v-else class="dock-ver">暂无报告</span>
          </button>
        </aside>
      </article>

      <div v-if="!loading && (doc.total || 0) > 0" class="pager">
        <button type="button" :disabled="page <= 1" @click="goPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ pageCount }} 页</span>
        <button type="button" :disabled="page >= pageCount" @click="goPage(page + 1)">下一页</button>
      </div>
    </div>

    <div v-if="modal.open" class="review-mask" @click.self="closeModal">
      <div class="review-modal" role="dialog" aria-modal="true" aria-labelledby="review-modal-title">
        <header class="modal-hd">
          <div class="modal-title-row">
            <h2 id="review-modal-title">{{ modalTitle }}</h2>
            <span
              v-if="modal.data?.result_label"
              class="tag"
              :class="'res-' + (modal.data.result || 'empty')"
            >{{ modal.data.result_label }}</span>
          </div>
          <button class="btn-close" type="button" @click="closeModal">关闭</button>
        </header>
        <div class="modal-body">
          <p v-if="modal.loading" class="muted">正在加载…</p>
          <p v-else-if="modal.error" class="err">{{ modal.error }}</p>
          <template v-else-if="modal.data">
            <div v-if="reviewSourceMeta.length" class="review-source-meta">
              <div v-for="item in reviewSourceMeta" :key="item.label" class="review-source-item">
                <span class="k">{{ item.label }}</span>
                <span class="v">{{ item.value }}</span>
              </div>
            </div>
            <iframe
              v-if="fragmentPage"
              class="review-frame review-srcdoc"
              :srcdoc="fragmentPage"
              sandbox="allow-same-origin allow-popups"
              title="推演结果"
            ></iframe>
            <p v-else class="modal-msg">{{ emptyReviewMessage }}</p>
          </template>
        </div>
      </div>
    </div>

    <div v-if="infoModal.open" class="review-mask" @click.self="closeCaseInfo">
      <div class="review-modal" role="dialog" aria-modal="true" aria-labelledby="case-info-title">
        <header class="modal-hd">
          <div class="modal-title-row">
            <h2 id="case-info-title">用例信息</h2>
          </div>
          <button class="btn-close" type="button" @click="closeCaseInfo">关闭</button>
        </header>
        <div class="modal-body">
          <iframe
            v-if="caseInfoPage"
            class="review-frame review-srcdoc"
            :srcdoc="caseInfoPage"
            sandbox="allow-same-origin allow-popups"
            title="用例信息"
          ></iframe>
          <dl v-else-if="caseInfoFields.length" class="review-fields case-info-fields">
            <template v-for="field in caseInfoFields" :key="field.label">
              <dt>{{ field.label }}</dt>
              <dd>{{ field.value }}</dd>
            </template>
          </dl>
          <p v-else class="modal-msg">当前用例文档没有可展示的额外信息</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, onUnmounted, ref, watch } from "vue";
import { api } from "../api";

const BlockText = defineComponent({
  name: "BlockText",
  props: { text: { type: String, default: "" } },
  setup(props) {
    return () => {
      const parsed = parseBlock(props.text);
      if (parsed.type === "empty") return h("div", { class: "steps muted" }, "—");
      if (parsed.type === "ol") {
        return h(
          "ol",
          { class: "steps" },
          parsed.items.map((item, i) => h("li", { key: i }, item))
        );
      }
      return h(
        "div",
        { class: "steps" },
        parsed.items.map((item, i) => h("p", { key: i }, item))
      );
    };
  },
});

const ENDPOINT_ORDER = ["backend", "web", "android", "ios"];
const ENDPOINT_LABELS = { backend: "后端", web: "web", android: "安卓", ios: "ios" };

const products = ref([]);
const productId = ref("");
const caseVersion = ref("");
const versions = ref([]);
const priorities = ref([]);
const doc = ref({ items: [], pending: [], total: 0, version: "", page: 1, page_size: 20 });
const qInput = ref("");
const q = ref("");
const priority = ref("");
const page = ref(1);
const pageSize = ref(20);
const selectedId = ref(null);
const loading = ref(false);
const error = ref("");
const modal = ref({ open: false, loading: false, error: "", data: null, endpoint: "" });
const infoModal = ref({ open: false });

let qTimer = null;

const productName = computed(() => {
  const p = products.value.find((x) => String(x.id) === String(productId.value));
  return p?.name || doc.value.product?.name || "";
});

const pageCount = computed(() => Math.max(1, Math.ceil((doc.value.total || 0) / (pageSize.value || 20))));
const rangeStart = computed(() => ((doc.value.total || 0) === 0 ? 0 : ((page.value - 1) * pageSize.value + 1)));
const rangeEnd = computed(() => Math.min(page.value * pageSize.value, doc.value.total || 0));

const selectedCase = computed(() => (doc.value.items || []).find((c) => c.id === selectedId.value) || null);

const modalTitle = computed(() => {
  const d = modal.value.data;
  if (!d) return "推演详情";
  const parts = [
    `${d.label || ""}推演`,
    d.case_key,
    d.report_version ? `报告 ${d.report_version}` : null,
    d.based_on_case_version ? `依据用例 ${d.based_on_case_version}` : null,
  ].filter(Boolean);
  return parts.join(" · ");
});

const fragmentPage = computed(() => {
  const pageHtml = modal.value.data?.fragment_page;
  return typeof pageHtml === "string" ? pageHtml : "";
});

const priorityStats = computed(() => doc.value.priority_stats || { total: 0, priorities: [], untested: 0 });
const showPriorityStats = computed(() => (priorityStats.value.total || 0) > 0 || (priorityStats.value.untested || 0) > 0);

const caseInfo = computed(() => doc.value.case_info || { available: false, title: "", fields: [], fragment_page: "" });
const caseInfoPage = computed(() => (typeof caseInfo.value.fragment_page === "string" ? caseInfo.value.fragment_page : ""));
const caseInfoFields = computed(() => caseInfo.value.fields || []);

const reviewSourceMeta = computed(() => {
  const d = modal.value.data || {};
  return [
    { label: "仓库", value: d.repo },
    { label: "分支", value: d.branch },
    { label: "参与人", value: d.participants },
  ].filter((item) => String(item.value || "").trim());
});

function formatPercent(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "0.0";
  return n.toFixed(1);
}

const emptyReviewMessage = computed(() => {
  const msg = modal.value.data?.message;
  const text = errorText(msg);
  return text || "该用例在此端报告中没有推演详情";
});

watch(qInput, (val) => {
  clearTimeout(qTimer);
  qTimer = setTimeout(() => {
    if (q.value === val) return;
    q.value = val;
    page.value = 1;
    reload();
  }, 300);
});

function caseEndpoints(c) {
  const byId = {};
  for (const ep of c?.endpoints || []) {
    const id = ep.endpoint || ep.id;
    if (id) byId[id] = ep;
  }
  return ENDPOINT_ORDER.map((id) => {
    const ep = byId[id] || {};
    return {
      ...ep,
      id,
      endpoint: ep.endpoint || id,
      label: ep.label || ENDPOINT_LABELS[id],
      available: Boolean(ep.available),
      result: ep.result || "",
      result_label: ep.result_label || (ep.available ? "无详情" : "暂无"),
      found: Boolean(ep.found),
    };
  });
}

function dockClass(ep) {
  if (!ep.available) return { empty: true };
  if (ep.found && ep.result) return { ready: true, ["result-" + ep.result]: true };
  return { empty: true, "result-none": true };
}

function parseBlock(text) {
  const raw = String(text || "")
    .replace(/\r\n/g, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .trim();
  if (!raw) return { type: "empty", items: [] };
  const lines = raw.split(/\n+/).map((s) => s.trim()).filter(Boolean);
  const numberedLines = lines.filter((s) => /^\d+[\.、．)]\s*/.test(s));
  if (lines.length > 1 && numberedLines.length >= Math.ceil(lines.length * 0.6)) {
    return { type: "ol", items: lines.map((s) => s.replace(/^\d+[\.、．)]\s*/, "")) };
  }
  const inline = raw.split(/(?=\d+[\.、．)]\s+)/).map((s) => s.trim()).filter(Boolean);
  if (inline.length > 1 && inline.every((s) => /^\d+[\.、．)]\s*/.test(s))) {
    return { type: "ol", items: inline.map((s) => s.replace(/^\d+[\.、．)]\s*/, "")) };
  }
  return { type: "text", items: lines };
}

function keepSelection() {
  const ids = new Set((doc.value.items || []).map((c) => c.id));
  if (selectedId.value && ids.has(selectedId.value)) return;
  selectedId.value = doc.value.items?.[0]?.id ?? null;
}

async function reload() {
  if (!productId.value) return;
  loading.value = true;
  error.value = "";
  try {
    const data = await api.caseDocs({
      product_id: productId.value,
      version: caseVersion.value || undefined,
      q: q.value || undefined,
      priority: priority.value || undefined,
      page: page.value,
      page_size: pageSize.value,
    });
    doc.value = data;
    versions.value = data.versions || [];
    priorities.value = data.priorities || [];
    caseVersion.value = data.version || caseVersion.value;
    if (data.page) page.value = data.page;
    keepSelection();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}

async function onProductChange() {
  caseVersion.value = "";
  selectedId.value = null;
  priority.value = "";
  page.value = 1;
  await reload();
}

function onVersionChange() {
  page.value = 1;
  priority.value = "";
  reload();
}

function onFilterChange() {
  page.value = 1;
  reload();
}

function onPageSizeChange() {
  page.value = 1;
  reload();
}

function goPage(next) {
  const target = Math.min(Math.max(1, next), pageCount.value);
  if (target === page.value) return;
  page.value = target;
  reload();
}

function errorText(e) {
  const raw = e?.message ?? e;
  if (raw == null) return "请求失败";
  if (typeof raw === "string") return raw;
  if (Array.isArray(raw)) return raw.map((item) => errorText(item)).join("；");
  if (typeof raw === "object") return raw.msg || raw.message || raw.detail || JSON.stringify(raw);
  return String(raw);
}

async function openReview(endpoint, caseItem) {
  const current = caseItem || selectedCase.value;
  if (current?.id) selectedId.value = current.id;
  if (!current || !productId.value || !caseVersion.value || !endpoint) return;
  modal.value = { open: true, loading: true, error: "", data: null, endpoint };
  try {
    const data = await api.reviewDetail({
      product_id: productId.value,
      endpoint,
      case_id: current.id,
      case_version: caseVersion.value,
    });
    modal.value = { open: true, loading: false, error: "", data, endpoint };
  } catch (e) {
    modal.value = { open: true, loading: false, error: errorText(e), data: null, endpoint };
  }
}

function closeModal() {
  modal.value = { open: false, loading: false, error: "", data: null, endpoint: "" };
}

function openCaseInfo() {
  infoModal.value = { open: true };
}

function closeCaseInfo() {
  infoModal.value = { open: false };
}

function onKey(e) {
  if (e.key !== "Escape") return;
  if (infoModal.value.open) {
    closeCaseInfo();
    return;
  }
  if (modal.value.open) closeModal();
}

async function exportTable() {
  const headers = ["序号", "编号", "优先级", "业务端", "模块", "用例描述", "前置步骤", "操作步骤", "预期结果", "后端", "web", "安卓", "ios"];
  let items = [];
  try {
    const data = await api.caseDocs({
      product_id: productId.value,
      version: caseVersion.value || undefined,
      q: q.value || undefined,
      priority: priority.value || undefined,
      page: 1,
      page_size: 1000,
    });
    items = data.items || [];
  } catch (e) {
    error.value = errorText(e);
    return;
  }
  const resultOf = (c, id) => (c.endpoints || []).find((ep) => (ep.endpoint || ep.id) === id)?.result_label || "";
  const rows = items.map((c) => [
    c.seq || "",
    c.key || "",
    c.priority || "",
    c.client || "",
    c.module || "",
    c.description || c.title || "",
    c.preconditions || "",
    c.steps || "",
    c.expected || "",
    resultOf(c, "backend"),
    resultOf(c, "web"),
    resultOf(c, "android"),
    resultOf(c, "ios"),
  ]);
  const esc = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const csv = [headers, ...rows].map((r) => r.map(esc).join(",")).join("\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  const name = `${productName.value || "cases"}_${caseVersion.value || "latest"}.csv`;
  a.href = URL.createObjectURL(blob);
  a.download = name.replace(/\s+/g, "_");
  a.click();
  URL.revokeObjectURL(a.href);
}

onMounted(async () => {
  window.addEventListener("keydown", onKey);
  try {
    products.value = await api.products();
    if (products.value.length) {
      productId.value = String(products.value[0].id);
      await reload();
    }
  } catch (e) {
    error.value = errorText(e);
  }
});

onUnmounted(() => {
  window.removeEventListener("keydown", onKey);
  clearTimeout(qTimer);
});
</script>
