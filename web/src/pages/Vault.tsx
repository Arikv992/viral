import { useState } from "react";
import { api, usd, when } from "../api";
import { Badge, Bar, Btn, Card, Empty, Page, Stat, useAction, useApi, useChannels } from "../ui";

export default function Vault() {
  const { data: b, reload: rb } = useApi<any>("/finance/budget");
  const [days, setDays] = useState(90);
  const { data: pnl, reload: rp } = useApi<any>(`/finance/pnl?days=${days}`, [days]);
  const { data: ledger, reload: rl } = useApi<any[]>("/finance/ledger?limit=80");
  const { data: channels } = useChannels();
  const [alloc, setAlloc] = useState<any | null>(null);
  const [rev, setRev] = useState({ amount: 0, channel_id: "", memo: "" });
  const [ypp, setYpp] = useState({ subs: 0, watch_hours: 0, shorts_views_90d: 0, daily_subs: 10, daily_hours: 20, daily_shorts_views: 20000 });
  const [yppRes, setYppRes] = useState<any | null>(null);
  const { busy, run } = useAction();

  const reloadAll = () => { rb(); rp(); rl(); };
  const cats = Object.entries(pnl?.by_category ?? {}).sort((a: any, z: any) => z[1] - a[1]) as [string, number][];
  const catMax = Math.max(...cats.map((c) => c[1]), 0.0001);

  return (
    <Page kicker="Dinheiro" title="Cofre de lucro"
      sub="Cada cêntimo registado. Orçamento mensal = base + reinvestimento automático de parte da receita do mês anterior. O capital é realocado entre canais por Thompson sampling sobre o retorno por dólar — quem rende recebe mais, quem falha os critérios de corte é congelado."
      actions={<Btn kind="primary" busy={busy === "alloc"} onClick={() => run("alloc", async () => setAlloc(await api.post("/finance/allocate")), "Capital realocado")}>Realocar capital</Btn>}>
      {b && (
        <div className="grid g4">
          <Stat label={`Orçamento ${b.month}`} value={usd(b.budget)} tone="gold" sub={`${usd(b.base_budget)} base + ${usd(b.reinvest_from_last_month)} reinvestido`} />
          <Stat label="Gasto" value={usd(b.spent)} sub={`${usd(b.burn_per_day)}/dia · projeção ${usd(b.projected_spend)}`} tone={b.on_track ? undefined : "red"} />
          <Stat label="Receita do mês" value={usd(b.revenue_month)} tone="teal" />
          <Stat label="Lucro do mês" value={usd(b.profit_month)} tone={b.profit_month >= 0 ? "teal" : "red"} sub={`Permitido hoje: ${usd(b.daily_allowance)}`} />
        </div>
      )}

      {alloc && (
        <Card className="mt hl" title="Alocação de capital">
          {!alloc.allocations.length ? <Empty>Sem canais ativos.</Empty> : (
            <table>
              <thead><tr><th>Canal</th><th className="right">Custo 60d</th><th className="right">Receita 60d</th><th className="right">$ por $1</th><th>Fase</th><th>Quota</th><th className="right">Orçamento</th></tr></thead>
              <tbody>{alloc.allocations.map((a: any) => (
                <tr key={a.channel_id}><td><b>{a.name}</b><div className="small faint">{a.videos} vídeos · {a.age_days} dias</div></td>
                  <td className="right mono">{usd(a.cost_60d)}</td><td className="right mono">{usd(a.revenue_60d)}</td>
                  <td className="right mono">{a.return_per_dollar}</td><td>{a.young ? <Badge tone="blue">exploração</Badge> : <Badge>maduro</Badge>}</td>
                  <td style={{ minWidth: 120 }}><Bar value={a.share * 100} /></td><td className="right mono gold">{usd(a.budget_usd)}</td></tr>))}</tbody>
            </table>
          )}
          {alloc.notes.map((n: string) => <div key={n} className="note bad mt small">{n}</div>)}
        </Card>
      )}

      <div className="grid g-side mt">
        <Card title="P&L por canal" action={<select value={days} onChange={(e) => setDays(Number(e.target.value))}><option value={30}>30 dias</option><option value={90}>90 dias</option><option value={365}>12 meses</option></select>}>
          {!pnl?.by_channel?.length ? <Empty>Sem movimentos.</Empty> : (
            <table>
              <thead><tr><th>Canal</th><th className="right">Custo</th><th className="right">Receita</th><th className="right">Lucro</th><th className="right">ROI</th></tr></thead>
              <tbody>{pnl.by_channel.map((r: any) => (
                <tr key={r.channel_id}><td><b>{r.name}</b></td><td className="right mono">{usd(r.cost, 3)}</td><td className="right mono">{usd(r.revenue)}</td>
                  <td className={`right mono ${r.profit >= 0 ? "teal" : "red"}`}>{usd(r.profit)}</td><td className="right mono">{r.roi == null ? "—" : `${(r.roi * 100).toFixed(0)}%`}</td></tr>))}</tbody>
            </table>
          )}
          <h2 className="mt2">Vídeos mais lucrativos</h2>
          {(pnl?.top_videos ?? []).slice(0, 8).map((v: any) => (
            <div key={v.video_id} className="row spread small" style={{ padding: "5px 0", borderBottom: "1px solid var(--line)" }}>
              <span>#{v.video_id} {v.title}</span><span className={`mono ${v.profit >= 0 ? "teal" : "red"}`}>{usd(v.profit, 3)}</span>
            </div>
          ))}
        </Card>
        <div className="stack">
          <Card title="Para onde vai o dinheiro">
            {!cats.length ? <Empty>Sem custos.</Empty> : cats.map(([k, v]) => (
              <div key={k} style={{ padding: "5px 0" }}>
                <div className="row spread small"><span>{k}</span><span className="mono">{usd(v, 3)}</span></div>
                <Bar value={v} max={catMax} />
              </div>
            ))}
          </Card>
          <Card title="Registar receita">
            <div className="stack">
              <input type="number" placeholder="Valor USD" value={rev.amount || ""} onChange={(e) => setRev({ ...rev, amount: Number(e.target.value) })} />
              <select value={rev.channel_id} onChange={(e) => setRev({ ...rev, channel_id: e.target.value })}>
                <option value="">Sem canal</option>
                {(channels ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <input placeholder="Nota (ex.: AdSense setembro, sponsor…)" value={rev.memo} onChange={(e) => setRev({ ...rev, memo: e.target.value })} />
              <Btn busy={busy === "rev"} disabled={!rev.amount} onClick={() => run("rev", async () => { await api.post("/finance/revenue", { amount: rev.amount, channel_id: rev.channel_id ? Number(rev.channel_id) : null, memo: rev.memo }); reloadAll(); }, "Receita registada")}>Registar</Btn>
            </div>
          </Card>
        </div>
      </div>

      <div className="grid g2 mt">
        <Card title="Projeção até ao YPP (Programa de Parcerias)">
          <div className="row small">
            {(Object.keys(ypp) as (keyof typeof ypp)[]).map((k) => (
              <label key={k} className="f">{k}<input type="number" value={ypp[k]} onChange={(e) => setYpp({ ...ypp, [k]: Number(e.target.value) })} style={{ width: 110 }} /></label>
            ))}
          </div>
          <Btn className="mt" busy={busy === "ypp"} onClick={() => run("ypp", async () => setYppRes(await api.post("/finance/ypp", ypp)))}>Calcular</Btn>
          {yppRes && <p className="mt">Caminho mais rápido: <b className="gold">{yppRes.best_path === "long" ? "4.000 horas (longos)" : "10M views Shorts"}</b> — ETA <b>{yppRes.eta_days ?? "∞"} dias</b> (longos: {yppRes.long_path_days ?? "∞"} · Shorts: {yppRes.shorts_path_days ?? "∞"}).</p>}
        </Card>
        <Card title="Livro-razão">
          {!ledger?.length ? <Empty>Vazio.</Empty> : (
            <div className="log" style={{ maxHeight: 300 }}>
              {ledger.map((e) => (
                <div key={e.id}><b>{when(e.at)}</b><span className={e.kind === "revenue" ? "teal" : ""}>{e.kind === "revenue" ? "+" : "−"}{usd(e.amount_usd, 4)}</span> · {e.category} · {e.memo}</div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </Page>
  );
}
