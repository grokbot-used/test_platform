<template>
  <div class="app-shell" :class="{ 'doc-mode': docMode }">
    <header class="topbar">
      <router-link to="/cases" class="brand">
        <strong>SPECTRA</strong>
        <span>测谱</span>
      </router-link>
      <nav class="nav">
        <router-link to="/cases">用例库</router-link>
      </nav>
    </header>
    <main class="page" :class="{ 'page-doc': docMode }">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();
const docMode = computed(() => route.name === "cases" || route.name === "case-version-info");
</script>
