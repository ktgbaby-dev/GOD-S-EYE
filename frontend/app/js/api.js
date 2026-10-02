// Fetch wrapper. The session is an HttpOnly cookie (never readable here); mutations carry the header the server
// requires as a CSRF check. Any 401 sends the user back to the login gate.
export class ApiError extends Error {
  constructor(status, data) {
    super((data && data.error) || `Request failed (${status})`);
    this.status = status;
    this.data = data || {};
  }
}

export async function api(method, path, body) {
  const opts = { method, credentials: "same-origin", headers: { Accept: "application/json" } };
  if (method !== "GET") {
    opts.headers["X-Requested-With"] = "GodsEye";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body || {});
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new ApiError(0, { error: "Network error. Check your connection and try again." });
  }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (res.status === 401) {
    const next = location.pathname + location.search;
    location.replace("/login" + (next && next !== "/dashboard" ? "?next=" + encodeURIComponent(next) : ""));
    throw new ApiError(401, data);
  }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const get = (p) => api("GET", p);
export const post = (p, b) => api("POST", p, b);
export const put = (p, b) => api("PUT", p, b);
export const patch = (p, b) => api("PATCH", p, b);
export const del = (p) => api("DELETE", p);

export function qs(obj) {
  const p = new URLSearchParams();
  Object.entries(obj || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, v);
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}
