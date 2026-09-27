import { useEffect, useState } from "react";
import { useApi } from "./ui";
import Dashboard from "./pages/Dashboard";
import Trends from "./pages/Trends";
import Strategy from "./pages/Strategy";
import Studio from "./pages/Studio";
import Audience from "./pages/Audience";
import Ideas from "./pages/Ideas";
import Factory from "./pages/Factory";
import Publish from "./pages/Publish";
import Analytics from "./pages/Analytics";
import Vault from "./pages/Vault";
import Autopilot from "./pages/Autopilot";

const ROUTES: { key: string; label: string; group: string; icon: string; el: () => JSX.Element }[] = [
  { key: "dashboard", label: "Painel", group: "Comando", icon: "◆", el: Dashboard },
  { key: "autopilot", label: "Piloto automático", group: "Comando", icon: "⟳", el: Autopilot },
  { key: "trends", label: "Radar de tendências", group: "Descobrir", icon: "◎", el: Trends },
  { key: "strategy", label: "Estratégia de canais", group: "Descobrir", icon: "♜", el: Strategy },
  { key: "audience", label: "Público & CPM", group: "Descobrir", icon: "◉", el: Audience },
  { key: "studio", label: "Estúdio de canal", group: "Criar", icon: "✦", el: Studio },
  { key: "ideas", label: "Banco de ideias", group: "Criar", icon: "☰", el: Ideas },
  { key: "factory", label: "Fábrica de vídeos", group: "Criar", icon: "▶", el: Factory },
  { key: "publish", label: "Publicação", group: "Distribuir", icon: "⤴", el: Publish },
  { key: "analytics", label: "Análise & escala", group: "Distribuir", icon: "↗", el: Analytics },
  { key: "vault", label: "Cofre de lucro", group: "Dinheiro", icon: "$", el: Vault },
];

function useHash() {
  const get = () => (window.location.hash.replace(/^#\/?/, "") || "dashboard").split("?")[0];
  const [h, setH] = useState(get);
  useEffect(() => {
    const on = () => setH(get());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return h;
}

export default function App() {
  const route = useHash();
  const { data: status } = useApi<any>("/status", [route]);
  const current = ROUTES.find((r) => r.key === route) ?? ROUTES[0];
  const Page = current.el;
  const groups = [...new Set(ROUTES.map((r) => r.group))];
  const caps = status?.capabilities ?? {};
  const on = Object.values(caps).filter(Boolean).length;

  useEffect(() => {
    document.title = `${current.label} · VIRAL-OPS`;
    window.scrollTo(0, 0);
  }, [current]);

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <div className="brand-mark">
            <svg width="20" height="20" viewBox="0 0 32 32" aria-hidden>
              <path d="M5 8l11 18L27 8" stroke="#f5b301" strokeWidth="4" fill="none" strokeLinejoin="round" />
            </svg>
          </div>
          <div className="brand-name">VIRAL<b>·</b>OPS</div>
        </div>
        {groups.map((g) => (
          <div key={g}>
            <div className="nav-group">{g}</div>
            <nav className="nav">
              {ROUTES.filter((r) => r.group === g).map((r) => (
                <a key={r.key} href={`#/${r.key}`} className={r.key === current.key ? "on" : ""}>
                  <span style={{ width: 16, textAlign: "center", opacity: 0.8 }}>{r.icon}</span>
                  {r.label}
                </a>
              ))}
            </nav>
          </div>
        ))}
        <div className="side-foot">
          {status ? (
            <>
              <div className="row spread">
                <span>Orçamento do mês</span>
                <b className="gold">${status.budget.remaining.toFixed(2)}</b>
              </div>
              <div className="bar mt" style={{ marginTop: 8 }}>
                <i style={{ width: `${Math.min(100, (status.budget.spent / Math.max(status.budget.budget, 0.01)) * 100)}%` }} />
              </div>
              <div className="small faint" style={{ marginTop: 8 }}>
                {on}/{Object.keys(caps).length} integrações ativas · {status.model}
              </div>
              <div className="small faint">Piloto: {status.settings.autopilot_enabled ? "LIGADO" : "desligado"}</div>
            </>
          ) : (
            <span className="faint">A ligar ao servidor…</span>
          )}
        </div>
      </aside>
      <main className="main">
        <Page />
      </main>
    </div>
  );
}
