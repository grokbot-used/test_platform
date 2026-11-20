<template>
  <div class="doc-page" :class="{ 'drawer-open': drawer.open }">
    <div ref="docScroll" class="doc-scroll" @scroll="onScroll">
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
            <nav class="env-progress" aria-label="环境测试执行记录" @click.stop>
              <button
                v-for="env in ENVIRONMENTS"
                :key="env.key"
                type="button"
                class="env-node"
                :class="{ lit: hasEnvComment(c, env.key), active: isEnvOpen(c, env.key) }"
                :style="{ '--env-color': env.color }"
                :title="envButtonTitle(c, env)"
                :aria-label="envButtonTitle(c, env)"
                @click="openEnvComments(c, env.key)"
              >
                <span class="env-icon" v-html="env.icon"></span>
                <span class="env-label">{{ env.label }}</span>
              </button>
            </nav>
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
            <span class="dock-name">测试执行记录</span>
            <span class="dock-result">测试执行记录</span>
            <span class="dock-ver">{{ (c.comment_count || 0) > 0 ? c.comment_count + " 条" : "暂无" }}</span>
          </button>
        </aside>
      </article>

    </div>
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
            <h2 id="comment-drawer-title">测试执行记录 · {{ commentTitle }}</h2>
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
          <p v-if="comments.loading" class="muted">正在加载测试执行记录…</p>
          <p v-else-if="comments.error" class="err">{{ comments.error }}</p>
          <p v-else-if="!comments.items.length" class="modal-msg">还没有测试执行记录，可以在下方留言或粘贴图片</p>
          <article
            v-for="item in comments.items"
            :key="item.id"
            class="comment-item"
            :class="{ 'is-focusing': focusingCommentId === item.id }"
            :data-comment-id="item.id"
          >
            <div class="comment-item-hd">
              <div class="comment-meta">
                <span
                  v-if="item.environment"
                  class="comment-env"
                  :style="{ '--env-color': envColor(item.environment) }"
                >
                  <span class="comment-env-icon" v-html="envIcon(item.environment)"></span>
                  {{ item.environment_label || envLabel(item.environment) }}
                </span>
                <time class="comment-time">{{ formatCommentTime(item.created_at) }}</time>
              </div>
              <button type="button" class="comment-delete" :disabled="confirmDelete.deleting" @click="askDeleteComment(item)">删除</button>
            </div>
            <p v-if="item.body" class="comment-body">{{ item.body }}</p>
            <div v-if="item.images?.length" class="comment-images">
              <button
                v-for="(img, i) in item.images"
                :key="img.url + i"
                type="button"
                class="comment-image-btn"
                @click="openLightbox(img)"
              >
                <img :src="img.url" :alt="img.name || '测试执行记录图片'" />
              </button>
            </div>
          </article>
        </div>
        <form class="comment-composer" :class="{ locked: envCommentLocked }" @submit.prevent="submitComment">
          <p v-if="envCommentLocked" class="composer-hint">该环境已有测试执行记录，删除后可重新评论</p>
          <textarea
            v-model="draftText"
            rows="3"
            :placeholder="composerPlaceholder"
            :disabled="comments.sending || envCommentLocked"
            @paste="onCommentPaste"
          ></textarea>
          <div v-if="draftImages.length" class="draft-images">
            <div v-for="(img, i) in draftImages" :key="img.url" class="draft-thumb">
              <img :src="img.url" :alt="img.name" />
              <button type="button" class="draft-remove" :disabled="envCommentLocked" @click="removeDraftImage(i)">删除</button>
            </div>
          </div>
          <div class="composer-actions">
            <label class="btn-export composer-upload" :class="{ disabled: comments.sending || envCommentLocked }">
              添加图片
              <input type="file" accept="image/*" multiple hidden :disabled="comments.sending || envCommentLocked" @change="onPickImages" />
            </label>
            <button class="btn-export composer-send" type="submit" :disabled="!canSendComment || comments.sending || envCommentLocked">
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

    <div
      v-if="confirmDelete.open"
      class="review-mask confirm-mask"
      @wheel.self.prevent
      @touchmove.self.prevent
      @click.self="cancelDeleteComment"
    >
      <div class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-delete-title">
        <h2 id="confirm-delete-title">删除测试执行记录</h2>
        <p>确定删除这条测试执行记录？删除后无法恢复。</p>
        <div class="confirm-actions">
          <button type="button" class="btn-export" :disabled="confirmDelete.deleting" @click="cancelDeleteComment">取消</button>
          <button type="button" class="btn-export btn-danger" :disabled="confirmDelete.deleting" @click="confirmDeleteComment">
            {{ confirmDelete.deleting ? "删除中…" : "删除" }}
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="lightbox.open"
      class="img-lightbox-mask"
      @click.self="closeLightbox"
      @wheel.prevent="onLightboxWheel"
    >
      <div class="img-lightbox-toolbar" @click.stop>
        <button type="button" class="img-tool-btn" title="缩小" @click="zoomLightbox(1 / 1.25)">缩小</button>
        <button type="button" class="img-tool-btn" title="放大" @click="zoomLightbox(1.25)">放大镜</button>
        <button type="button" class="img-tool-btn" title="重置" @click="resetLightbox">重置</button>
        <span class="img-zoom-label">{{ Math.round(lightbox.scale * 100) }}%</span>
      </div>
      <div class="img-lightbox-stage" @click="closeLightbox">
        <img
          class="img-lightbox-photo"
          :src="lightbox.url"
          :alt="lightbox.name"
          :style="lightboxStyle"
          draggable="false"
          @load="onLightboxLoad"
          @click.stop
          @pointerdown="onLightboxPointerDown"
          @pointermove="onLightboxPointerMove"
          @pointerup="onLightboxPointerUp"
          @pointerleave="onLightboxPointerLeave"
        />
        <div
          v-show="lightbox.loupe.visible"
          class="img-loupe"
          :style="loupeStyle"
        ></div>
      </div>
    </div>
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
const ENV_ICON = {
  test: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M8 3h4M9 3v4.1L5.1 15.3A2 2 0 0 0 6.9 18h6.2a2 2 0 0 0 1.8-2.7L11 7.1V3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M6.3 13h7.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
  cn_pre: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 16.5V7.2L10 3.8l5.5 3.4v9.3H4.5z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M8 16.5v-4h4v4M8 8.4h.01M12 8.4h.01M10 11h.01" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  overseas_pre: '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="6.2" fill="none" stroke="currentColor" stroke-width="1.6"/><ellipse cx="10" cy="10" rx="3" ry="6.2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M3.8 10h12.4M5.2 6.7h9.6M5.2 13.3h9.6" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>',
  cn_prod: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.6 16 5.2v5.1c0 3.3-2.5 5.5-6 6.8-3.5-1.3-6-3.5-6-6.8V5.2L10 2.6z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="m7.3 10.2 2 2.1 3.7-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  overseas_prod: '<svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8.6" cy="9.4" r="5.4" fill="none" stroke="currentColor" stroke-width="1.6"/><ellipse cx="8.6" cy="9.4" rx="2.5" ry="5.4" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M3.2 9.4h10.8" stroke="currentColor" stroke-width="1.4"/><path d="m12.2 12.3 1.5 1.6 3.3-3.6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};
const ENVIRONMENTS = [
  { key: "test", label: "测试线", color: "#2563EB", icon: ENV_ICON.test },
  { key: "cn_pre", label: "国内预发布", color: "#7C3AED", icon: ENV_ICON.cn_pre },
  { key: "overseas_pre", label: "海外预发布", color: "#0891B2", icon: ENV_ICON.overseas_pre },
  { key: "cn_prod", label: "国内正式线", color: "#059669", icon: ENV_ICON.cn_prod },
  { key: "overseas_prod", label: "海外正式线", color: "#C2410C", icon: ENV_ICON.overseas_prod },
];

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
const docScroll = ref(null);
const comments = ref({ loading: false, error: "", items: [], sending: false });
const draftText = ref("");
const draftImages = ref([]);
const commentEnvironment = ref("");
const focusingCommentId = ref(null);
let focusTimer = 0;
const confirmDelete = ref({ open: false, item: null, deleting: false });
const lightbox = ref({
  open: false,
  url: "",
  name: "",
  scale: 1,
  x: 0,
  y: 0,
  dragging: false,
  dragStartX: 0,
  dragStartY: 0,
  originX: 0,
  originY: 0,
  loupe: { visible: false, x: 0, y: 0, bgSize: "", bgPos: "" },
});

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
  const base = `${c.key || ""} ${c.description || c.title || ""}`.trim();
  const env = envLabel(commentEnvironment.value);
  return env ? `${base} · ${env}` : base;
});

const envCommentLocked = computed(() => {
  const key = commentEnvironment.value;
  if (!key) return false;
  return comments.value.items.some((item) => item.environment === key);
});

const canSendComment = computed(() => {
  if (envCommentLocked.value) return false;
  return Boolean(draftText.value.trim() || draftImages.value.length);
});

const composerPlaceholder = computed(() => {
  if (envCommentLocked.value) return "该环境已有测试执行记录，删除后可重新评论";
  const label = envLabel(commentEnvironment.value);
  if (label) return `记录「${label}」的测试执行情况，可直接粘贴图片`;
  return "输入测试执行记录，可直接粘贴图片";
});

const lightboxStyle = computed(() => ({
  transform: `translate(${lightbox.value.x}px, ${lightbox.value.y}px) scale(${lightbox.value.scale})`,
  cursor: lightbox.value.scale > 1 ? (lightbox.value.dragging ? "grabbing" : "grab") : "zoom-in",
}));

const loupeStyle = computed(() => {
  const loupe = lightbox.value.loupe;
  return {
    left: `${loupe.x}px`,
    top: `${loupe.y}px`,
    backgroundImage: lightbox.value.url ? `url(${lightbox.value.url})` : "none",
    backgroundSize: loupe.bgSize,
    backgroundPosition: loupe.bgPos,
  };
});

watch(
  () => infoModal.value.open,
  () => {
    syncPageScrollLock();
    onScroll();
  }
);

watch(
  () => drawer.value.open,
  (open) => {
    setDrawerOpen(open);
    syncPageScrollLock();
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
    // 仅「用例信息」/图片预览/确认框在无抽屉时补偿滚动条；抽屉打开后滚动条改到抽屉左侧，不再加 body padding。
    const compensate = !drawer.value.open && (infoModal.value.open || lightbox.value.open || confirmDelete.value.open);
    const gap = compensate ? window.innerWidth - root.clientWidth : 0;
    root.classList.add("modal-open");
    document.body.style.overflow = "hidden";
    document.body.style.paddingRight = gap > 0 ? `${gap}px` : "";
  } else {
    root.classList.remove("modal-open");
    document.body.style.overflow = "";
    document.body.style.paddingRight = "";
  }
}

function syncPageScrollLock() {
  setScrollLocked(Boolean(
    infoModal.value.open || drawer.value.open || lightbox.value.open || confirmDelete.value.open
  ));
}

function pageScrollTop() {
  if (drawer.value.open && docScroll.value) return docScroll.value.scrollTop;
  return window.scrollY;
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
  const scroller = docScroll.value;
  if (open) {
    const y = window.scrollY;
    root.style.setProperty("--drawer-w", "40vw");
    root.classList.add("drawer-open");
    nextTick(() => {
      if (scroller) scroller.scrollTop = y;
      window.scrollTo(0, 0);
      onScroll();
    });
  } else {
    const y = scroller ? scroller.scrollTop : 0;
    root.style.setProperty("--drawer-w", "0px");
    root.classList.remove("drawer-open");
    nextTick(() => {
      window.scrollTo(0, y);
      onScroll();
    });
  }
}

function clearDraftImages() {
  for (const item of draftImages.value) {
    if (item.url) URL.revokeObjectURL(item.url);
  }
  draftImages.value = [];
}

function envMeta(key) {
  return ENVIRONMENTS.find((item) => item.key === key) || null;
}
function envLabel(key) {
  return envMeta(key)?.label || "";
}
function envColor(key) {
  return envMeta(key)?.color || "#2563EB";
}
function envIcon(key) {
  return ENV_ICON[key] || "";
}
function hasEnvComment(caseItem, key) {
  return Boolean(caseItem?.env_comments?.[key]);
}
function isEnvOpen(caseItem, key) {
  return isCommentOpen(caseItem) && commentEnvironment.value === key;
}
function envButtonTitle(caseItem, env) {
  return hasEnvComment(caseItem, env.key) ? `${env.label}（已有记录）` : `${env.label}（未记录）`;
}
function clearCommentFocus() {
  if (focusTimer) {
    clearTimeout(focusTimer);
    focusTimer = 0;
  }
  focusingCommentId.value = null;
}
function closeDrawer() {
  drawer.value = { open: false, mode: "review" };
  modal.value = { open: false, loading: false, error: "", data: null, endpoint: "" };
  comments.value = { loading: false, error: "", items: [], sending: false };
  commentEnvironment.value = "";
  clearCommentFocus();
  draftText.value = "";
  clearDraftImages();
  cancelDeleteComment();
  closeLightbox();
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
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(d);
  const pick = (type) => parts.find((part) => part.type === type)?.value || "";
  return `${pick("year")}-${pick("month")}-${pick("day")} ${pick("hour")}:${pick("minute")}`;
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
  if (envCommentLocked.value) return;
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

async function focusComment(commentId) {
  await nextTick();
  requestAnimationFrame(() => {
    const el = commentList.value?.querySelector(`[data-comment-id="${commentId}"]`);
    if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
    focusingCommentId.value = null;
    requestAnimationFrame(() => {
      focusingCommentId.value = commentId;
    });
    if (focusTimer) clearTimeout(focusTimer);
    focusTimer = setTimeout(() => {
      if (focusingCommentId.value === commentId) focusingCommentId.value = null;
      focusTimer = 0;
    }, 3000);
  });
}

async function openComments(caseItem, environment = "") {
  if (!caseItem?.id) return;
  selectedId.value = caseItem.id;
  commentEnvironment.value = environment || "";
  clearCommentFocus();
  drawer.value = { open: true, mode: "comments" };
  modal.value = { open: false, loading: false, error: "", data: null, endpoint: "" };
  await loadComments(caseItem);
  if (!environment) return;
  const existingId =
    caseItem.env_comments?.[environment] ||
    comments.value.items.find((item) => item.environment === environment)?.id;
  if (existingId) await focusComment(existingId);
}

async function openEnvComments(caseItem, environment) {
  await openComments(caseItem, environment);
}

async function submitComment() {
  const current = selectedCase.value;
  if (!current?.id || !canSendComment.value || comments.value.sending || envCommentLocked.value) return;
  comments.value = { ...comments.value, sending: true, error: "" };
  const form = new FormData();
  form.append("body", draftText.value.trim());
  if (caseVersion.value) form.append("case_version", caseVersion.value);
  if (commentEnvironment.value) form.append("environment", commentEnvironment.value);
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
    if (created.environment) {
      current.env_comments = { ...(current.env_comments || {}), [created.environment]: created.id };
    }
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

function askDeleteComment(item) {
  if (!item?.id) return;
  confirmDelete.value = { open: true, item, deleting: false };
  syncPageScrollLock();
}

function cancelDeleteComment() {
  if (confirmDelete.value.deleting) return;
  confirmDelete.value = { open: false, item: null, deleting: false };
  syncPageScrollLock();
}

async function confirmDeleteComment() {
  const item = confirmDelete.value.item;
  const current = selectedCase.value;
  if (!item?.id || !current?.id || confirmDelete.value.deleting) return;
  confirmDelete.value = { ...confirmDelete.value, deleting: true };
  try {
    await api.deleteComment(current.id, item.id);
    comments.value = {
      ...comments.value,
      items: comments.value.items.filter((row) => row.id !== item.id),
      error: "",
    };
    current.comment_count = Math.max(0, (current.comment_count || 0) - 1);
    if (item.environment && current.env_comments) {
      const next = { ...current.env_comments };
      if (next[item.environment] === item.id) delete next[item.environment];
      current.env_comments = next;
    }
    confirmDelete.value = { open: false, item: null, deleting: false };
    syncPageScrollLock();
  } catch (e) {
    comments.value = { ...comments.value, error: errorText(e) };
    confirmDelete.value = { ...confirmDelete.value, deleting: false };
  }
}

function openLightbox(img) {
  if (!img?.url) return;
  lightbox.value = {
    open: true,
    url: img.url,
    name: img.name || "图片",
    scale: 1,
    x: 0,
    y: 0,
    dragging: false,
    dragStartX: 0,
    dragStartY: 0,
    originX: 0,
    originY: 0,
    loupe: { visible: false, x: 0, y: 0, bgSize: "", bgPos: "" },
  };
  syncPageScrollLock();
}

function closeLightbox() {
  if (!lightbox.value.open) return;
  lightbox.value = {
    ...lightbox.value,
    open: false,
    dragging: false,
    loupe: { visible: false, x: 0, y: 0, bgSize: "", bgPos: "" },
  };
  syncPageScrollLock();
}

function onLightboxLoad() {
  resetLightbox();
}

function resetLightbox() {
  lightbox.value = {
    ...lightbox.value,
    scale: 1,
    x: 0,
    y: 0,
    dragging: false,
    loupe: { ...lightbox.value.loupe, visible: false },
  };
}

function zoomLightbox(factor) {
  const next = Math.min(5, Math.max(0.5, lightbox.value.scale * factor));
  lightbox.value = { ...lightbox.value, scale: next };
}

function onLightboxWheel(e) {
  const factor = e.deltaY < 0 ? 1.12 : 1 / 1.12;
  zoomLightbox(factor);
}

function updateLoupe(e) {
  const img = e.currentTarget?.classList?.contains("img-lightbox-photo")
    ? e.currentTarget
    : (e.currentTarget.querySelector?.(".img-lightbox-photo") || document.querySelector(".img-lightbox-photo"));
  if (!img) return;
  const rect = img.getBoundingClientRect();
  const over = e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom;
  if (!over || lightbox.value.dragging) {
    lightbox.value.loupe.visible = false;
    return;
  }
  const zoom = 2.2;
  const size = 168;
  const px = (e.clientX - rect.left) / rect.width;
  const py = (e.clientY - rect.top) / rect.height;
  const stage = document.querySelector(".img-lightbox-stage");
  const stageRect = stage ? stage.getBoundingClientRect() : { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
  let left = e.clientX - stageRect.left - size / 2;
  let top = e.clientY - stageRect.top - size / 2;
  left = Math.min(Math.max(0, left), Math.max(0, stageRect.width - size));
  top = Math.min(Math.max(0, top), Math.max(0, stageRect.height - size));
  lightbox.value.loupe = {
    visible: true,
    x: left,
    y: top,
    bgSize: `${rect.width * zoom}px ${rect.height * zoom}px`,
    bgPos: `${-px * rect.width * zoom + size / 2}px ${-py * rect.height * zoom + size / 2}px`,
  };
}

function onLightboxPointerDown(e) {
  if (e.button != null && e.button !== 0) return;
  if (lightbox.value.scale <= 1) {
    updateLoupe(e);
    return;
  }
  e.currentTarget.setPointerCapture?.(e.pointerId);
  lightbox.value.dragging = true;
  lightbox.value.dragStartX = e.clientX;
  lightbox.value.dragStartY = e.clientY;
  lightbox.value.originX = lightbox.value.x;
  lightbox.value.originY = lightbox.value.y;
  lightbox.value.loupe.visible = false;
}

function onLightboxPointerMove(e) {
  if (lightbox.value.dragging) {
    lightbox.value.x = lightbox.value.originX + (e.clientX - lightbox.value.dragStartX);
    lightbox.value.y = lightbox.value.originY + (e.clientY - lightbox.value.dragStartY);
    return;
  }
  updateLoupe(e);
}

function onLightboxPointerUp(e) {
  lightbox.value.dragging = false;
  try { e.currentTarget.releasePointerCapture?.(e.pointerId); } catch (_) {}
}

function onLightboxPointerLeave() {
  lightbox.value.dragging = false;
  lightbox.value.loupe.visible = false;
}

function onKey(e) {
  if (e.key !== "Escape") return;
  if (lightbox.value.open) {
    closeLightbox();
    return;
  }
  if (confirmDelete.value.open) {
    cancelDeleteComment();
    return;
  }
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
  const overlay = infoModal.value.open || lightbox.value.open || confirmDelete.value.open;
  showBackTop.value = pageScrollTop() > 240 && !overlay;
}

function scrollToTop() {
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const behavior = reduce ? "auto" : "smooth";
  if (drawer.value.open && docScroll.value) {
    docScroll.value.scrollTo({ top: 0, behavior });
    return;
  }
  window.scrollTo({ top: 0, behavior });
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
  clearCommentFocus();
  setScrollLocked(false);
  setDrawerOpen(false);
  clearDraftImages();
});
</script>
