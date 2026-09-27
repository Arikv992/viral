import { num, pct, usd } from "../api";
import { Badge, Bar, Card, Empty, LONGEVITY, Page, Stat, useApi, VERDICT } from "../ui";

const AREA: Record<string, string> = {
  estrategia: "strategy", canais: "strategy", estudio: "studio", publicacao: "publish", analise: "analytics",
  fabrica: "factory", cofre: "vault",
};

export default function Dashboard() {
  const { data: d } = useApi<any>("/dashboard", [], 20000);
  if (!d) return <Page kicker="Comando" title="Painel">A carregar…</Page>;
  const b = d.budget;
  return (
    <Page kicker="Comando" title="Painel"
      sub="O estado do império numa página: dinheiro, pipeline, vencedores e as ações de maior impacto para hoje.">
      <div className="grid g4">
        <Stat label="Lucro (30 dias)" value={usd(d.pnl.profit)} tone={d.pnl.profit >= 0 ? "teal" : "red"}
          sub={`${usd(d.pnl.revenue)} receita · ${usd(d.pnl.cost)} custo`} />
        <Stat label="Orçamento restante" value={usd(b.remaining)} tone="gold"
          sub={`de ${usd(b.budget)} · ${usd(b.reinvest_from_last_month)} reinvestido`} />
        <Stat label="Views totais" value={num(d.views_total)} sub={`${d.channels} canal(is) ativo(s)`} />
        <Stat label="Custo médio / vídeo" value={usd(d.pnl.cost_per_video, 3)} sub="LLM + voz + visuais + render" />
      </div>

      <div className="grid g-side mt">
        <Card title="O que fazer hoje">
          {d.today.length ? (
            <div className="stack">
              {d.today.map((a: any, i: number) => (
                <a key={i} href={`#/${AREA[a.area] ?? "dashboard"}`} className="row"
                  style={{ flexWrap: "nowrap", padding: "10px 12px", background: "var(--bg-2)", borderRadius: 10, border: "1px solid var(--line)", color: "var(--text)", textDecoration: "none" }}>
                  <Badge tone={a.priority === 1 ? "gold" : a.priority === 2 ? "blue" : undefined}>P{a.priority}</Badge>
                  <span style={{ flex: 1, minWidth: 0 }}>{a.text}</span>
                  <span className="faint">→</span>
                </a>
              ))}
            </div>
          ) : (
            <Empty>Nada pendente. O piloto automático está a tratar do resto.</Empty>
          )}
        </Card>
        <Card title="Pipeline">
          {[
            ["Ideias em backlog", d.ideas.backlog ?? 0],
            ["Aprovadas", d.ideas.approved ?? 0],
            ["Em produção", (d.videos.rendering ?? 0) + (d.videos.scripting ?? 0) + (d.videos.planned ?? 0)],
            ["Prontos", d.videos.ready ?? 0],
            ["Agendados", d.publications.scheduled ?? 0],
            ["Publicados/exportados", (d.publications.published ?? 0) + (d.publications.exported ?? 0)],
          ].map(([l, v]) => (
            <div key={l as string} className="row spread" style={{ padding: "7px 0", borderBottom: "1px solid var(--line)" }}>
              <span className="muted">{l}</span>
              <b className="mono">{v as number}</b>
            </div>
          ))}
          <div className="small faint mt">Gasto: {usd(b.spent)} · ritmo {usd(b.burn_per_day)}/dia · projeção {usd(b.projected_spend)}</div>
          <div className="mt"><Bar value={b.spent} max={Math.max(b.budget, 0.01)} /></div>
        </Card>
      </div>

      <div className="grid g2 mt">
        <Card title="Melhores vídeos" action={<a href="#/analytics" className="small">Análise →</a>}>
          {d.top.length ? (
            <table>
              <thead><tr><th>Vídeo</th><th className="right">Views</th><th className="right">Outlier</th><th>Veredito</th></tr></thead>
              <tbody>
                {d.top.map((r: any) => (
                  <tr key={r.publication_id}>
                    <td>{r.title}<div className="small faint">{r.format} · CTR {pct(r.ctr, 1)} · ret. {pct(r.avg_view_pct)}</div></td>
                    <td className="right mono">{num(r.views)}</td>
                    <td className="right mono">{r.outlier}×</td>
                    <td>{r.verdict && <Badge tone={VERDICT[r.verdict]?.tone}>{VERDICT[r.verdict]?.label}</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty>Sem vídeos medidos ainda.</Empty>}
        </Card>
        <Card title="Tendências mais fortes" action={<a href="#/trends" className="small">Radar →</a>}>
          {d.recent_trends.length ? (
            <table>
              <thead><tr><th>Tema</th><th>Vida</th><th className="right">Oportunidade</th></tr></thead>
              <tbody>
                {d.recent_trends.map((t: any) => (
                  <tr key={t.id}>
                    <td>{t.topic}<div className="small faint">{t.niche_key}</div></td>
                    <td><Badge tone={LONGEVITY[t.longevity]?.tone}>{LONGEVITY[t.longevity]?.label}</Badge></td>
                    <td className="right"><span className="score gold">{t.opportunity.toFixed(0)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty>Corre um scan no Radar de tendências.</Empty>}
        </Card>
      </div>
    </Page>
  );
}
