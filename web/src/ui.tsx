import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "./api";

// ---------------------------------------------------------------- dados
export function useApi<T = any>(path: string | null, deps: unknown[] = [], poll?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      const d = await api.get<T>(path);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e: any) {
      if (alive.current) setError(e.message);
    } finally {
      if (alive.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => {
    alive.current = true;
    load();
    const t = poll ? setInterval(load, poll) : undefined;
    return () => {
      alive.current = false;
      if (t) clearInterval(t);
    };
  }, [load, poll]);
  return { data, error, loading, reload: load, setData };
}

// ---------------------------------------------------------------- toast
const ToastCtx = createContext<(msg: string, err?: boolean) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [t, setT] = useState<{ msg: string; err?: boolean } | null>(null);
  const show = useCallback((msg: string, err?: boolean) => {
    setT({ msg, err });
    setTimeout(() => setT(null), err ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {t && <div className={`toast ${t.err ? "err" : ""}`}>{t.msg}</div>}
    </ToastCtx.Provider>
  );
}

/** Executa uma ação assíncrona com estado de "a trabalhar" e toast de erro/sucesso. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const run = useCallback(
    async <T,>(key: string, fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
      setBusy(key);
      try {
        const r = await fn();
        if (ok) toast(ok);
        return r;
      } catch (e: any) {
        toast(e.message || String(e), true);
      } finally {
        setBusy(null);
      }
    },
    [toast],
  );
  return { busy, run };
}

// ---------------------------------------------------------------- componentes
export function Page({ kicker, title, sub, actions, children }: { kicker: string; title: string; sub?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <>
      <div className="page-head">
        <div>
          <div className="kicker">{kicker}</div>
          <h1>{title}</h1>
          {sub && <p>{sub}</p>}
        </div>
        {actions && <div className="row">{actions}</div>}
      </div>
      {children}
    </>
  );
}

export function Card({ title, action, children, className = "" }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={`card ${className}`}>
      {(title || action) && (
        <div className="card-head">
          {typeof title === "string" ? <h2>{title}</h2> : title}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "gold" | "teal" | "red" }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className={`value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Btn({ children, busy, kind, sm, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; kind?: "primary" | "ghost" | "danger"; sm?: boolean }) {
  return (
    <button {...p} className={`btn ${kind ?? ""} ${sm ? "sm" : ""} ${p.className ?? ""}`} disabled={busy || p.disabled}>
      {busy && <span className="spin" />}
      {children}
    </button>
  );
}

export function Badge({ children, tone }: { children: ReactNode; tone?: "gold" | "teal" | "red" | "blue" | "violet" }) {
  return <span className={`badge ${tone ?? ""}`}>{children}</span>;
}

export function Bar({ value, max = 100, tone }: { value: number; max?: number; tone?: "teal" }) {
  return (
    <div className={`bar ${tone ?? ""}`}>
      <i style={{ width: `${Math.max(0, Math.min(100, (value / max) * 100))}%` }} />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Tabs<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div className="pill-tabs">
      {options.map(([k, l]) => (
        <button key={k} className={k === value ? "on" : ""} onClick={() => onChange(k)}>
          {l}
        </button>
      ))}
    </div>
  );
}

export function Spark({ values, w = 140, h = 34, color = "var(--gold)" }: { values: number[]; w?: number; h?: number; color?: string }) {
  if (!values?.length) return <span className="faint small">sem série</span>;
  const mx = Math.max(...values, 1);
  const pts = values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * w},${h - (v / mx) * (h - 2) - 1}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="série temporal">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  );
}

const DAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];
export function Heatmap({ data }: { data: number[][] }) {
  return (
    <div className="heat">
      <span />
      {Array.from({ length: 24 }, (_, h) => (
        <span key={h} style={{ textAlign: "center" }}>{h % 3 === 0 ? h : ""}</span>
      ))}
      {data.map((row, d) => [
        <span key={`l${d}`}>{DAYS[d]}</span>,
        ...row.map((v, h) => (
          <div key={`${d}-${h}`} className="cell" title={`${DAYS[d]} ${h}:00 UTC — ${(v * 100).toFixed(0)}`}
            style={{ background: `rgba(245,179,1,${0.05 + v * 0.9})` }} />
        )),
      ])}
    </div>
  );
}

export const VERDICT: Record<string, { label: string; tone: any }> = {
  scale: { label: "Escalar", tone: "gold" },
  repackage: { label: "Reembalar", tone: "blue" },
  rehook: { label: "Novo gancho", tone: "violet" },
  republish: { label: "Republicar", tone: "teal" },
  hold: { label: "Aguardar", tone: undefined },
  kill: { label: "Matar", tone: "red" },
  ride_now: { label: "Surfar já", tone: "red" },
  build_series: { label: "Série", tone: "gold" },
  evergreen_asset: { label: "Evergreen", tone: "teal" },
  skip: { label: "Ignorar", tone: undefined },
};

export const LONGEVITY: Record<string, { label: string; tone: any }> = {
  flash: { label: "Flash (dias)", tone: "red" },
  wave: { label: "Onda (semanas)", tone: "gold" },
  evergreen: { label: "Evergreen", tone: "teal" },
  seasonal: { label: "Sazonal", tone: "violet" },
  unknown: { label: "?", tone: undefined },
};

export function useChannels() {
  return useApi<any[]>("/channels");
}

export function ChannelPicker({ value, onChange, channels, allowAll }: { value: number | null; onChange: (v: number | null) => void; channels: any[] | null; allowAll?: boolean }) {
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      {allowAll && <option value="">Todos os canais</option>}
      {!allowAll && !value && <option value="">Escolhe um canal…</option>}
      {(channels ?? []).filter((c) => c.status !== "killed").map((c) => (
        <option key={c.id} value={c.id}>{c.name}</option>
      ))}
    </select>
  );
}
