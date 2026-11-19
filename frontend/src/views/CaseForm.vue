<template>
  <div>
    <div class="page-hd">
      <div>
        <h1>{{ isEdit ? "保存为新版本" : "新建用例" }}</h1>
        <p v-if="isEdit">在当前内容上修改后写入新版本，不覆盖已有快照。</p>
      </div>
    </div>
    <form class="card" @submit.prevent="save">
      <div class="form-grid">
        <div class="field">
          <label>产品</label>
          <select v-model="form.product_id" :disabled="isEdit" required>
            <option value="" disabled>选择产品</option>
            <option v-for="p in products" :key="p.id" :value="p.id">{{ p.name }}</option>
          </select>
        </div>
        <div class="field">
          <label>编号</label>
          <input v-model="form.key" :disabled="isEdit" required placeholder="如 TC-OPA-035" />
        </div>
        <div class="field">
          <label>版本（留空则自动递增）</label>
          <input v-model="form.version" placeholder="v1.0.7" />
        </div>
        <div class="field">
          <label>优先级</label>
          <input v-model="form.priority" placeholder="P1" />
        </div>
        <div class="field">
          <label>模块</label>
          <input v-model="form.module" />
        </div>
        <div class="field">
          <label>业务端</label>
          <input v-model="form.client" placeholder="web / app" />
        </div>
        <div class="field full">
          <label>标题 / 用例描述</label>
          <input v-model="form.title" required />
        </div>
        <div class="field full">
          <label>前置步骤</label>
          <textarea v-model="form.preconditions"></textarea>
        </div>
        <div class="field full">
          <label>操作步骤</label>
          <textarea v-model="form.steps"></textarea>
        </div>
        <div class="field full">
          <label>预期结果</label>
          <textarea v-model="form.expected"></textarea>
        </div>
      </div>
      <p class="err" v-if="error" style="padding: 0 22px">{{ error }}</p>
      <div class="actions">
        <button class="btn ghost" type="button" @click="$router.back()">取消</button>
        <button class="btn solid" type="submit">保存</button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api";

const props = defineProps({ id: [String, Number] });
const route = useRoute();
const router = useRouter();
const products = ref([]);
const error = ref("");
const isEdit = !!props.id;
const form = reactive({
  product_id: "",
  key: "",
  version: "",
  title: "",
  module: "",
  priority: "",
  client: "",
  description: "",
  preconditions: "",
  steps: "",
  expected: "",
});

onMounted(async () => {
  products.value = await api.products();
  if (isEdit) {
    const data = await api.case(props.id, route.query.version);
    form.product_id = data.product.id;
    form.key = data.key;
    form.version = "";
    form.title = data.current.title;
    form.module = data.current.module;
    form.priority = data.current.priority;
    form.client = data.current.client;
    form.description = data.current.description;
    form.preconditions = data.current.preconditions;
    form.steps = data.current.steps;
    form.expected = data.current.expected;
  }
});

async function save() {
  error.value = "";
  try {
    const payload = { ...form, description: form.description || form.title };
    if (!payload.version) delete payload.version;
    let id = props.id;
    if (isEdit) {
      const r = await api.addCaseVersion(props.id, payload);
      id = r.id;
      router.push(`/cases/${id}?version=${r.version}`);
    } else {
      const r = await api.createCase(payload);
      router.push(`/cases/${r.id}?version=${r.version}`);
    }
  } catch (e) {
    error.value = e.message;
  }
}
</script>
