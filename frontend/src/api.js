function formatDetail(detail) {
  if (detail == null || detail === "") return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => formatDetail(item))
      .filter(Boolean)
      .join("；");
  }
  if (typeof detail === "object") {
    return detail.msg || detail.message || (detail.detail ? formatDetail(detail.detail) : JSON.stringify(detail));
  }
  return String(detail);
}

async function request(url, options = {}) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = formatDetail(body.detail) || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  overview: () => request("/api/overview"),
  products: () => request("/api/products"),
  meta: (productId) =>
    request("/api/meta" + (productId ? `?product_id=${productId}` : "")),
  cases: (params = {}) => request("/api/cases?" + new URLSearchParams(clean(params))),
  case: (id, version) =>
    request(`/api/cases/${id}` + (version ? `?version=${encodeURIComponent(version)}` : "")),
  createCase: (body) =>
    request("/api/cases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  addCaseVersion: (id, body) =>
    request(`/api/cases/${id}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  reports: (params = {}) =>
    request("/api/reports?" + new URLSearchParams(clean(params))),
  report: (id, version) =>
    request(`/api/reports/${id}` + (version ? `?version=${encodeURIComponent(version)}` : "")),
  createLink: (body) =>
    request("/api/links", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteLink: (id) => request(`/api/links/${id}`, { method: "DELETE" }),
  importCases: (form) => request("/api/imports/cases", { method: "POST", body: form }),
  importReports: (form) => request("/api/imports/reports", { method: "POST", body: form }),
  caseDocs: (params = {}) =>
    request("/api/case-docs?" + new URLSearchParams(clean(params))),
  reviewEntries: (productId, caseVersion) =>
    request(
      "/api/review-entries?" +
        new URLSearchParams(clean({ product_id: productId, case_version: caseVersion }))
    ),
  reviewDetail: (params = {}) =>
    request("/api/review-detail?" + new URLSearchParams(clean(params))),
  caseComments: (caseId) => request(`/api/cases/${caseId}/comments`),
  createComment: (caseId, form) =>
    request(`/api/cases/${caseId}/comments`, { method: "POST", body: form }),
  deleteComment: (caseId, commentId) =>
    request(`/api/cases/${caseId}/comments/${commentId}`, { method: "DELETE" }),
};

function clean(params) {
  const out = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") out[k] = v;
  }
  return out;
}
