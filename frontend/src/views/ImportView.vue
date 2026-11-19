<template>
  <div>
    <div class="page-hd">
      <div>
        <h1>导入</h1>
        <p>上传用例 HTML，或报告 HTML / Markdown，解析后写入新版本。</p>
      </div>
    </div>
    <div class="grid-2">
      <form class="card" @submit.prevent="uploadCases">
        <div class="section-title">导入用例</div>
        <div class="form-grid">
          <div class="field">
            <label>产品</label>
            <select v-model="caseForm.product_id" required>
              <option value="" disabled>选择产品</option>
              <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </div>
          <div class="field">
            <label>版本（可选）</label>
            <input v-model="caseForm.version" placeholder="默认取文件名或文内版本" />
          </div>
          <div class="field full">
            <label>HTML 文件</label>
            <input type="file" accept=".html,.htm,.md" @change="(e) => (caseFile = e.target.files[0])" required />
          </div>
        </div>
        <p class="err" v-if="caseError" style="padding: 0 22px">{{ caseError }}</p>
        <p class="muted" v-if="caseMsg" style="padding: 0 22px 8px">{{ caseMsg }}</p>
        <div class="actions"><button class="btn solid" type="submit">导入用例</button></div>
      </form>

      <form class="card" @submit.prevent="uploadReports">
        <div class="section-title">导入报告</div>
        <div class="form-grid">
          <div class="field">
            <label>产品</label>
            <select v-model="reportForm.product_id" required>
              <option value="" disabled>选择产品</option>
              <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
            </select>
          </div>
          <div class="field">
            <label>类型</label>
            <select v-model="reportForm.type" required>
              <option value="blackbox">黑盒测试</option>
              <option value="frontend_review">前端推演</option>
              <option value="backend_review">后端推演</option>
              <option value="whitebox">白盒测试</option>
            </select>
          </div>
          <div class="field">
            <label>标题（可选）</label>
            <input v-model="reportForm.title" placeholder="默认取文件标题" />
          </div>
          <div class="field">
            <label>版本（可选）</label>
            <input v-model="reportForm.version" />
          </div>
          <div class="field full">
            <label>HTML / Markdown 文件</label>
            <input type="file" accept=".html,.htm,.md,.markdown" @change="(e) => (reportFile = e.target.files[0])" required />
          </div>
        </div>
        <p class="err" v-if="reportError" style="padding: 0 22px">{{ reportError }}</p>
        <p class="muted" v-if="reportMsg" style="padding: 0 22px 8px">{{ reportMsg }}</p>
        <div class="actions"><button class="btn solid" type="submit">导入报告</button></div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { api } from "../api";

const products = ref([]);
const caseFile = ref(null);
const reportFile = ref(null);
const caseError = ref("");
const reportError = ref("");
const caseMsg = ref("");
const reportMsg = ref("");
const caseForm = reactive({ product_id: "", version: "" });
const reportForm = reactive({ product_id: "", type: "blackbox", title: "", version: "" });

onMounted(async () => {
  products.value = await api.products();
});

async function uploadCases() {
  caseError.value = "";
  caseMsg.value = "";
  try {
    const fd = new FormData();
    fd.append("product_id", caseForm.product_id);
    if (caseForm.version) fd.append("version", caseForm.version);
    fd.append("file", caseFile.value);
    const r = await api.importCases(fd);
    caseMsg.value = `已导入 ${r.imported} 条，版本 ${r.version}`;
  } catch (e) {
    caseError.value = e.message;
  }
}

async function uploadReports() {
  reportError.value = "";
  reportMsg.value = "";
  try {
    const fd = new FormData();
    fd.append("product_id", reportForm.product_id);
    fd.append("type", reportForm.type);
    if (reportForm.title) fd.append("title", reportForm.title);
    if (reportForm.version) fd.append("version", reportForm.version);
    fd.append("file", reportFile.value);
    const r = await api.importReports(fd);
    reportMsg.value = `已导入「${r.title}」${r.version}，自动关联 ${r.links} 条用例`;
  } catch (e) {
    reportError.value = e.message;
  }
}
</script>
