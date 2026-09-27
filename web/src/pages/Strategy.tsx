import { useState } from "react";
import { api, usd } from "../api";
import { Badge, Bar, Btn, Card, Empty, Page, Tabs, useAction, useApi, useChannels } from "../ui";

export default function Strategy() {
  const [language, setLanguage] = useState("en");
  const [budget, setBudget] = useState(50);
  const [prefer, setPrefer] = useState<"both" | "short" | "long">("both");
  const { data: meta } = useApi<any>("/meta");
  const { data: niches } = useApi<any[]>(`/niches?language=${language}&budget=${budget}&prefer=${prefer}`, [language, budget, prefer]);
  const { data: langs } = useApi<any[]>("/languages");
  const { data: channels, reload: reloadCh } = useChannels();
  const [concepts, setConcepts] = useState<any | null>(null);
  const [names, setNames] = useState<Record<string, any[]>>({});
  const [notes, setNotes] = useState("");
  const { busy, run } = useAction();

  const makeConcepts = () =>
    run("concepts", async () => setConcepts(await api.post("/strategy/concepts", { language, budget, prefer, count: 5, notes })));
  const makeNames = (c: any) =>
    run(`names-${c.niche_key}`, async () => {
      const r = await api.post<any[]>("/strategy/names", { niche_key: c.niche_key, concept: c.positioning, language: c.language || language, count: 12 });
      setNames({ ...names, [c.niche_key]: r });
    });
  const create = (c: any, n: any) =>
    run(`create-${n.name}`, async () => {
      await api.post("/channels", {
        name: n.name, handle: n.handle, niche_key: c.niche_key, language: c.language || language,
        target_geos: c.target_geos?.length ? c.target_geos : ["US"],
        formats: prefer === "both" ? ["short", "long"] : [prefer], strategy: c,
      });
      reloadCh();
    }, `Canal "${n.name}" criado. Próximo passo: Estúdio de canal.`);

  return (
    <Page kicker="Descobrir" title="Estratégia de canais"
      sub="Que canais criar, em que língua e para que países. O ranking é um modelo económico explícito: RPM efetivo × procura × concorrência × evergreen × adequação faceless × risco de políticas.">
      <Card>
        <div className="row">
          <label className="f">Língua do canal
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {(meta?.languages ?? []).map((l: any) => <option key={l.code} value={l.code}>{l.name}</option>)}
            </select>
          </label>
          <label className="f">Orçamento mensal (USD)
            <input type="number" value={budget} min={0} onChange={(e) => setBudget(Number(e.target.value))} style={{ width: 120 }} />
          </label>
          <label className="f">Formato
            <Tabs value={prefer} onChange={setPrefer} options={[["both", "Shorts + Longos"], ["short", "Só Shorts"], ["long", "Só Longos"]]} />
          </label>
          <label className="f" style={{ flex: 1, minWidth: 240 }}>Notas para o estratega (opcional)
            <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="ex.: quero um canal de finanças e um de mistério" />
          </label>
          <Btn kind="primary" busy={busy === "concepts"} onClick={makeConcepts} style={{ alignSelf: "flex-end" }}>Gerar conceitos de canal</Btn>
        </div>
      </Card>

      {concepts && (
        <div className="mt">
          <div className="row spread"><h2>Conceitos recomendados</h2>
            <Badge tone={concepts.source === "llm" ? "teal" : undefined}>{concepts.source === "llm" ? "Claude" : "heurística (liga a ANTHROPIC_API_KEY para estratégia completa)"}</Badge></div>
          <div className="grid g2 mt">
            {concepts.concepts.map((c: any, i: number) => (
              <Card key={i} className={i === 0 ? "hl" : ""} title={<div><div className="kicker">#{i + 1} · {c.niche_key}</div><h3>{c.positioning}</h3></div>}>
                <div className="stack small">
                  <div><b>Público:</b> <span className="muted">{c.target_audience}</span></div>
                  <div><b>Mix:</b> <span className="muted">{c.format_mix}</span> · <b>Modo:</b> <span className="muted">{c.production_mode}</span></div>
                  <div><b>Receita mês 12:</b> <span className="gold">{usd(c.revenue_12m_usd?.[0], 0)} – {usd(c.revenue_12m_usd?.[1], 0)}</span>/mês</div>
                  <div><b>Caminho para monetizar:</b> <span className="muted">{c.monetization_path}</span></div>
                  <div><b>Estilo:</b> <span className="muted">{c.signature_style}</span></div>
                  <div><b>Critério de corte:</b> <span className="red">{c.kill_criteria}</span></div>
                  <div className="chip-list">{(c.content_pillars ?? []).map((p: string) => <span key={p} className="chip">{p}</span>)}</div>
                  <details><summary>Primeiros 10 vídeos</summary><ol>{(c.first_10_videos ?? []).map((t: string) => <li key={t}>{t}</li>)}</ol></details>
                </div>
                <div className="row mt">
                  <Btn busy={busy === `names-${c.niche_key}`} onClick={() => makeNames(c)}>Sugerir nomes</Btn>
                </div>
                {names[c.niche_key] && (
                  <div className="mt">
                    <table>
                      <thead><tr><th>Nome</th><th>@handle</th><th>Livre?</th><th className="right">Score</th><th /></tr></thead>
                      <tbody>
                        {names[c.niche_key].map((n) => (
                          <tr key={n.name}>
                            <td><b>{n.name}</b><div className="small faint">{n.why_it_works}</div></td>
                            <td className="mono">@{n.handle}</td>
                            <td>{n.handle_available === true ? <Badge tone="teal">livre</Badge> : n.handle_available === false ? <Badge tone="red">ocupado</Badge> : <Badge>?</Badge>}</td>
                            <td className="right mono">{n.score}</td>
                            <td><Btn sm kind="primary" busy={busy === `create-${n.name}`} onClick={() => create(c, n)}>Criar</Btn></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            ))}
          </div>
        </div>
      )}

      <div className="grid g-side mt">
        <Card title="Ranking de nichos (lucro esperado)">
          {!niches ? "A carregar…" : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Nicho</th><th className="right">RPM longo</th><th className="right">RPM Short</th><th>Concorr.</th><th>Evergreen</th><th>Risco</th><th className="right">Mês 12</th><th className="right">Score</th></tr></thead>
                <tbody>
                  {niches.map((n, i) => (
                    <tr key={n.key}>
                      <td><b>{i + 1}. {n.name}</b><div className="small faint">{n.best_modes.join(" · ")}</div></td>
                      <td className="right mono">{usd(n.rpm_long_effective)}</td>
                      <td className="right mono">{usd(n.rpm_short_effective, 3)}</td>
                      <td style={{ minWidth: 70 }}><Bar value={n.competition} /></td>
                      <td style={{ minWidth: 70 }}><Bar value={n.evergreen} tone="teal" /></td>
                      <td>{n.policy_risk >= 45 ? <Badge tone="red">{n.policy_risk}</Badge> : <span className="mono faint">{n.policy_risk}</span>}</td>
                      <td className="right mono small">{usd(n.month12_revenue_estimate[0], 0)}–{usd(n.month12_revenue_estimate[1], 0)}</td>
                      <td className="right"><span className="score gold">{n.score}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <div className="stack">
          <Card title="Quanto vale cada língua">
            {(langs ?? []).map((l) => (
              <div key={l.language} style={{ padding: "7px 0", borderBottom: "1px solid var(--line)" }}>
                <div className="row spread"><b>{l.name}</b><span className="mono gold">{(l.rpm_mult * 100).toFixed(0)}%</span></div>
                <Bar value={l.rpm_mult * 100} />
                <div className="small faint" style={{ marginTop: 4 }}>{l.top_geos.map((g: any) => `${g.geo} ${(g.share * 100).toFixed(0)}%`).join(" · ")}</div>
              </div>
            ))}
            <p className="small muted mt">% = RPM médio face a uma audiência 100% EUA, dada a mistura real de países de cada língua.</p>
          </Card>
          <Card title="Os teus canais">
            {!channels?.length ? <Empty>Ainda nenhum.</Empty> : channels.map((c) => (
              <div key={c.id} className="row spread" style={{ padding: "6px 0" }}>
                <span><b>{c.name}</b> <span className="faint small">{c.niche_key} · {c.language}</span></span>
                <Badge tone={c.status === "active" ? "teal" : undefined}>{c.status}</Badge>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </Page>
  );
}
