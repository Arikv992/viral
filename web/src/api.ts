// Cliente mínimo da API. Todas as rotas vivem em /api (proxy do Vite em dev, mesma origem em produção).

export class ApiError extends Error {}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* resposta sem JSON */
    }
    throw new ApiError(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  get: <T = any>(p: string) => req<T>("GET", p),
  post: <T = any>(p: string, b: unknown = {}) => req<T>("POST", p, b),
  put: <T = any>(p: string, b: unknown) => req<T>("PUT", p, b),
  patch: <T = any>(p: string, b: unknown) => req<T>("PATCH", p, b),
  del: <T = any>(p: string) => req<T>("DELETE", p),
};

export const usd = (v: number | null | undefined, d = 2) =>
  v == null ? "—" : `$${Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
export const num = (v: number | null | undefined) =>
  v == null ? "—" : Number(v) >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : Number(v) >= 1e3 ? `${(v / 1e3).toFixed(1)}k` : `${Math.round(v)}`;
export const pct = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${Number(v).toFixed(d)}%`);
export const when = (iso?: string | null) =>
  iso ? new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").toLocaleString("pt-PT", { dateStyle: "short", timeStyle: "short" }) : "—";
