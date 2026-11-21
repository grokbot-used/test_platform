import { createRouter, createWebHistory } from "vue-router";
import Cases from "./views/Cases.vue";
import CaseDetail from "./views/CaseDetail.vue";
import CaseForm from "./views/CaseForm.vue";
import VersionInfo from "./views/VersionInfo.vue";
import Reports from "./views/Reports.vue";
import ReportDetail from "./views/ReportDetail.vue";
import ImportView from "./views/ImportView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/cases" },
    { path: "/cases", name: "cases", component: Cases },
    { path: "/cases/new", name: "case-new", component: CaseForm },
    { path: "/cases/version-info", name: "case-version-info", component: VersionInfo },
    { path: "/cases/:id", name: "case-detail", component: CaseDetail, props: true },
    { path: "/cases/:id/edit", name: "case-edit", component: CaseForm, props: true },
    { path: "/reports", name: "reports", component: Reports },
    { path: "/reports/:id", name: "report-detail", component: ReportDetail, props: true },
    { path: "/import", name: "import", component: ImportView },
  ],
  scrollBehavior() {
    return { top: 0 };
  },
});

export default router;
