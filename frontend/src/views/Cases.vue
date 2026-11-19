<template>
  <div class="doc-page" :class="{ 'drawer-open': drawer.open }">
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
          <button class="btn-export" type="button" @click="openCaseInfo">用例信息</button>
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
        <label>每页
          <select v-model.number="pageSize" @change="onPageSizeChange">
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
        </label>
        <div v-if="(doc.total || 0) > 0" class="pager toolbar-pager">
          <button type="button" :disabled="loading || page <= 1" @click="goPage(page - 1)">上一页</button>
          <label class="page-jump">第
            <input
              v-model="pageInput"
              type="number"
              min="1"
              :max="pageCount"
              inputmode="numeric"
              :disabled="loading"
              aria-label="跳转到页码"
              @keydown.enter.prevent="jumpToPage"
              @blur="jumpToPage"
            />
            / {{ pageCount }} 页
          </label>
          <button type="button" :disabled="loading || page >= pageCount" @click="goPage(page + 1)">下一页</button>
        </div>
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
          <button
            type="button"
            class="dock-btn comment-entry"
            :class="{ ready: (c.comment_count || 0) > 0, active: isCommentOpen(c) }"
            @click="openComments(c)"
          >
            <span class="dock-name">评论</span>
            <span class="dock-result">评论</span>
            <span class="dock-ver">{{ (c.comment_count || 0) > 0 ? c.comment_count + " 条" : "暂无" }}</span>
          </button>
        </aside>
      </article>

    </div>

    <aside
      v-if="drawer.open"
      class="side-drawer"
      role="dialog"
      aria-modal="false"
      :aria-labelledby="drawer.mode === 'comments' ? 'comment-drawer-title' : 'review-modal-title'"
    >
      <header class="modal-hd drawer-hd">
        <div class="modal-title-row">
          <template v-if="drawer.mode === 'comments'">
            <h2 id="comment-drawer-title">评论 · {{ commentTitle }}</h2>
          </template>
          <template v-else>
            <h2 id="review-modal-title">{{ modalTitle }}</h2>
            <span
              v-if="modal.data?.result_label"
              class="tag"
              :class="'res-' + (modal.data.result || 'empty')"
            >{{ modal.data.result_label }}</span>
          </template>
        </div>
        <button class="btn-close" type="button" @click="closeDrawer">关闭</button>
      </header>

      <div v-if="drawer.mode === 'review'" class="drawer-body">
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

      <div v-else class="comment-panel">
        <div ref="commentList" class="comment-list">
          <p v-if="comments.loading" class="muted">正在加载评论…</p>
          <p v-else-if="comments.error" class="err">{{ comments.error }}</p>
          <p v-else-if="!comments.items.length" class="modal-msg">还没有评论，可以在下方留言或粘贴图片</p>
          <article v-for="item in comments.items" :key="item.id" class="comment-item">
            <time class="comment-time">{{ formatCommentTime(item.created_at) }}</time>
            <p v-if="item.body" class="comment-body">{{ item.body }}</p>
            <div v-if="item.images?.length" class="comment-images">
              <a v-for="(img, i) in item.images" :key="img.url + i" :href="img.url" target="_blank" rel="noopener">
                <img :src="img.url" :alt="img.name || '评论图片'" />
              </a>
            </div>
          </article>
        </div>
        <form class="comment-composer" @submit.prevent="submitComment">
          <textarea
            v-model="draftText"
            rows="3"
            placeholder="输入评论，可直接粘贴图片"
            :disabled="comments.sending"
            @paste="onCommentPaste"
          ></textarea>
          <div v-if="draftImages.length" class="draft-images">
            <div v-for="(img, i) in draftImages" :key="img.url" class="draft-thumb">
              <img :src="img.url" :alt="img.name" />
              <button type="button" class="draft-remove" @click="removeDraftImage(i)">删除</button>
            </div>
          </div>
          <div class="composer-actions">
            <label class="btn-export composer-upload">
              添加图片
              <input type="file" accept="image/*" multiple hidden :disabled="comments.sending" @change="onPickImages" />
            </label>
            <button class="btn-export composer-send" type="submit" :disabled="!canSendComment || comments.sending">
              {{ comments.sending ? "发送中…" : "发送" }}
            </button>
          </div>
        </form>
      </div>
    </aside>

    <div v-if="infoModal.open" class="review-mask" @wheel.self.prevent @touchmove.self.prevent @click.self="closeCaseInfo">
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

    <button
      v-show="showBackTop"
      type="button"
      class="back-top"
      aria-label="回到顶部"
      title="回到顶部"
      @click="scrollToTop"
    >
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path fill="currentColor" d="M12 5.5 5.8 11.7a1 1 0 0 0 1.4 1.4L11 9.3V19a1 1 0 1 0 2 0V9.3l3.8 3.8a1 1 0 1 0 1.4-1.4Z"/>
      </svg>
    </button>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
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
const pageInput = ref("1");
const pageSize = ref(20);
const selectedId = ref(null);
const loading = ref(false);
const error = ref("");
const modal = ref({ open: false, loading: false, error: "", data: null, endpoint: "" });
const showBackTop = ref(false);
const infoModal = ref({ open: false });
const drawer = ref({ open: false, mode: "review" });
const commentList = ref(null);
const comments = ref({ loading: false, error: "", items: [], sending: false });
const draftText = ref("");
const draftImages = ref([]);

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

const commentTitle = computed(() => {
  const c = selectedCase.value;
  if (!c) return "";
  return `${c.key || ""} ${c.description || c.title || ""}`.trim();
});

const canSendComment = computed(() => Boolean(draftText.value.trim() || draftImages.value.length));

watch(
  () => infoModal.value.open,
  (open) => {
    setScrollLocked(Boolean(open));
    onScroll();
  }
);

watch(
  () => drawer.value.open,
  (open) => {
    setDrawerOpen(open);
    onScroll();
  }
);

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
  doc.value = { ...doc.value, items: [] };
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
    pageInput.value = String(page.value);
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
  pageInput.value = String(target);
  if (target === page.value) return;
  page.value = target;
  reload();
}

function jumpToPage() {
  const n = parseInt(String(pageInput.value), 10);
  if (!Number.isFinite(n)) {
    pageInput.value = String(page.value);
    return;
  }
  goPage(n);
}

function setScrollLocked(locked) {
  const root = document.documentElement;
  if (locked) {
    const gap = window.innerWidth - root.clientWidth;
    root.classList.add("modal-open");
    document.body.style.overflow = "hidden";
    if (gap > 0) document.body.style.paddingRight = `${gap}px`;
  } else {
    root.classList.remove("modal-open");
    document.body.style.overflow = "";
    document.body.style.paddingRight = "";
  }
}

function errorText(e) {
  const raw = e?.message ?? e;
  if (raw == null) return "请求失败";
  if (typeof raw === "string") return raw;
  if (Array.isArray(raw)) return raw.map((item) => errorText(item)).join("；");
  if (typeof raw === "object") return raw.msg || raw.message || raw.detail || JSON.stringify(raw);
  return String(raw);
}

function setDrawerOpen(open) {
  const root = document.documentElement;
  root.style.setProperty("--drawer-w", open ? "33.333vw" : "0px");
  root.classList.toggle("drawer-open", Boolean(open));
}

function clearDraftImages() {
  for (const item of draftImages.value) {
    if (item.url) URL.revokeObjectURL(item.url);
  }
  draftImages.value = [];
}

function closeDrawer() {
  drawer.value = { open: false, mode: "review" };
  modal.value = { open: false, loading: false, error: "", data: null, endpoint: "" };
  comments.value = { loading: false, error: "", items: [], sending: false };
  draftText.value = "";
  clearDraftImages();
}

function isCommentOpen(caseItem) {
  return Boolean(drawer.value.open && drawer.value.mode === "comments" && selectedId.value === caseItem?.id);
}

async function scrollCommentsToBottom() {
  await nextTick();
  requestAnimationFrame(() => {
    const el = commentList.value;
    if (el) el.scrollTop = el.scrollHeight;
  });
}

function formatCommentTime(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value || "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function addDraftImages(files) {
  const next = [];
  for (const file of files) {
    if (!file || !String(file.type || "").startsWith("image/")) continue;
    if (draftImages.value.length + next.length >= 9) break;
    next.push({ file, name: file.name || "image", url: URL.createObjectURL(file) });
  }
  if (next.length) draftImages.value = [...draftImages.value, ...next];
}

function removeDraftImage(index) {
  const item = draftImages.value[index];
  if (item?.url) URL.revokeObjectURL(item.url);
  draftImages.value = draftImages.value.filter((_, i) => i !== index);
}

function onPickImages(e) {
  addDraftImages(Array.from(e.target.files || []));
  e.target.value = "";
}

function onCommentPaste(e) {
  const items = e.clipboardData?.items || [];
  const files = [];
  for (const item of items) {
    if (item.kind === "file" && String(item.type || "").startsWith("image/")) {
      const file = item.getAsFile();
      if (file) files.push(file);
    }
  }
  if (!files.length) return;
  e.preventDefault();
  addDraftImages(files);
}

async function loadComments(caseItem) {
  comments.value = { ...comments.value, loading: true, error: "", items: comments.value.items || [] };
  try {
    const data = await api.caseComments(caseItem.id);
    comments.value = { loading: false, error: "", items: data.items || [], sending: false };
    await scrollCommentsToBottom();
  } catch (e) {
    comments.value = { loading: false, error: errorText(e), items: [], sending: false };
  }
}

async function openComments(caseItem) {
  if (!caseItem?.id) return;
  selectedId.value = caseItem.id;
  drawer.value = { open: true, mode: "comments" };
  modal.value = { open: false, loading: false, error: "", data: null, endpoint: "" };
  await loadComments(caseItem);
}

async function submitComment() {
  const current = selectedCase.value;
  if (!current?.id || !canSendComment.value || comments.value.sending) return;
  comments.value = { ...comments.value, sending: true, error: "" };
  const form = new FormData();
  form.append("body", draftText.value.trim());
  if (caseVersion.value) form.append("case_version", caseVersion.value);
  for (const item of draftImages.value) form.append("images", item.file, item.name);
  try {
    const created = await api.createComment(current.id, form);
    comments.value = {
      loading: false,
      error: "",
      items: [...comments.value.items, created],
      sending: false,
    };
    current.comment_count = (current.comment_count || 0) + 1;
    draftText.value = "";
    clearDraftImages();
    await scrollCommentsToBottom();
  } catch (e) {
    comments.value = { ...comments.value, sending: false, error: errorText(e) };
  }
}

async function openReview(endpoint, caseItem) {
  const current = caseItem || selectedCase.value;
  if (current?.id) selectedId.value = current.id;
  if (!current || !productId.value || !caseVersion.value || !endpoint) return;
  drawer.value = { open: true, mode: "review" };
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
  closeDrawer();
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
  if (drawer.value.open) closeDrawer();
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

function onScroll() {
  showBackTop.value = window.scrollY > 240 && !infoModal.value.open;
}

function scrollToTop() {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
}

onMounted(async () => {
  window.addEventListener("keydown", onKey);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
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
  window.removeEventListener("scroll", onScroll);
  clearTimeout(qTimer);
  setScrollLocked(false);
  setDrawerOpen(false);
  clearDraftImages();
});
</script>
