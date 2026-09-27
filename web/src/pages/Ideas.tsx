import { useEffect, useState } from "react";
import { api, num, usd } from "../api";
import { Badge, Bar, Btn, Card, ChannelPicker, Empty, Page, Tabs, useAction, useApi, useChannels } from "../ui";

const COLS: [string, string][] = [["backlog", "Backlog"], ["approved", "Aprovadas"], ["producing", "Em produção"], ["ready", "Prontas"], ["published", "Publicadas"]];
const ORIGIN: Record<string, any> = { scale: "gold", republish: "teal", trend: "red", manual: "blue", clip: "violet" };

export default function Ideas() {
  const { data: channels } = useChannels();
  const [cid, setCid] = useState<number | null>(null);
  useEffect(() => { if (!cid && channels?.length) setCid(channels[0].id); }, [channels, cid]);
  const { data: ideas, reload } = useApi<any[]>(cid ? `/ideas?channel_id=${cid}` : null, [cid]);
  const { data: series, reload: reloadSeries } = useApi<any[]>(cid ? `/ideas/series?channel_id=${cid}` : null, [cid]);
  const [view, setView] = useState<"board" | "table" | "series">("board");
  const [fmt, setFmt] = useState<"both" | "short" | "long">("both");
  const [manual, setManual] = useState({ title: "", format: "short" });
  const { busy, run } = useAction();

  const refresh = () => { reload(); reloadSeries(); };
  const generate = () => run("gen", async () => { await api.post("/ideas/generate", { channel_id: cid, count: 20, fmt }); refresh(); }, "Ideias geradas e consolidadas");
  const move = (id: number, status: string) => run(`m${id}`, async () => { await api.patch(`/ideas/${id}`, { status }); reload(); });
  const produce = (id: number) => run(`p${id}`, async () => { await api.post("/production/produce", { idea_id: id }); reload(); }, "Enviado para a Fábrica");
  const consolidate = () => run("cons", async () => { const r = await api.post(`/ideas/consolidate?channel_id=${cid}`); refresh(); return r; }, "Ideias consolidadas");
  const addManual = () => run("add", async () => { await api.post("/ideas", { channel_id: cid, ...manual }); setManual({ ...manual, title: "" }); reload(); });

  const IdeaCard = ({ i }: { i: any }) => (
    <div className="kcard">
      <div className="row spread">
        <Badge tone={i.format === "long" ? "blue" : undefined}>{i.format === "long" ? "Longo" : "Short"}</Badge>
        <span className="score gold" style={{ fontSize: 22 }}>{i.score.toFixed(0)}</span>
      </div>
      <div style={{ fontWeight: 600, margin: "6px 0 4px" }}>{i.title}</div>
      {i.hook && <div className="small muted">“{i.hook}”</div>}
      <div className="row small faint" style={{ marginTop: 6 }}>
        {i.origin !== "generated" && <Badge tone={ORIGIN[i.origin]}>{i.origin}</Badge>}
        {i.series_key && <span>#{i.series_key}</span>}
        <span>~{num(i.scores?.expected_views)} views · {usd(i.scores?.expected_revenue_usd, 3)}</span>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        {i.status === "backlog" && <><Btn sm onClick={() => move(i.id, "approved")}>Aprovar</Btn><Btn sm kind="ghost" onClick={() => move(i.id, "discarded")}>Descartar</Btn></>}
        {(i.status === "approved" || i.status === "backlog") && <Btn sm kind="primary" busy={busy === `p${i.id}`} onClick={() => produce(i.id)}>Produzir</Btn>}
      </div>
    </div>
  );

  return (
    <Page kicker="Criar" title="Banco de ideias"
      sub="Cada ideia é pontuada (procura, CTR, RPM, momentum, evergreen, facilidade, risco) e recebe views e receita esperadas. Duplicados são fundidos e as ideias agrupadas em séries — clusters temáticos ensinam o algoritmo mais depressa."
      actions={<>
        <ChannelPicker value={cid} onChange={setCid} channels={channels} />
        <Tabs value={fmt} onChange={setFmt} options={[["both", "Ambos"], ["short", "Shorts"], ["long", "Longos"]]} />
        <Btn kind="primary" busy={busy === "gen"} disabled={!cid} onClick={generate}>Gerar 20 ideias</Btn>
      </>}>
      {!cid ? <Empty>Cria um canal primeiro.</Empty> : (
        <>
          <div className="row spread">
            <Tabs value={view} onChange={setView} options={[["board", "Quadro"], ["table", "Tabela"], ["series", "Séries"]]} />
            <div className="row">
              <input placeholder="Ideia manual…" value={manual.title} onChange={(e) => setManual({ ...manual, title: e.target.value })} style={{ width: 240 }} />
              <select value={manual.format} onChange={(e) => setManual({ ...manual, format: e.target.value })}><option value="short">Short</option><option value="long">Longo</option></select>
              <Btn disabled={!manual.title} busy={busy === "add"} onClick={addManual}>Adicionar</Btn>
              <Btn busy={busy === "cons"} onClick={consolidate}>Consolidar</Btn>
            </div>
          </div>
          <div className="mt">
            {!ideas?.length ? <Empty>Sem ideias — gera as primeiras 20.</Empty> : view === "board" ? (
              <div className="kanban">
                {COLS.map(([k, l]) => {
                  const items = ideas.filter((i) => i.status === k);
                  return (
                    <div key={k} className="kcol">
                      <div className="row spread" style={{ marginBottom: 8 }}><h2>{l}</h2><span className="mono faint">{items.length}</span></div>
                      {items.slice(0, 40).map((i) => <IdeaCard key={i.id} i={i} />)}
                    </div>
                  );
                })}
              </div>
            ) : view === "table" ? (
              <Card>
                <div className="table-wrap"><table>
                  <thead><tr><th>Ideia</th><th>Formato</th><th>Procura</th><th>CTR</th><th>RPM</th><th>Risco</th><th className="right">Views esp.</th><th className="right">Score</th><th>Estado</th><th /></tr></thead>
                  <tbody>{ideas.map((i) => (
                    <tr key={i.id}>
                      <td style={{ maxWidth: 380 }}><b>{i.title}</b><div className="small faint">{i.angle}</div></td>
                      <td>{i.format}</td>
                      <td style={{ minWidth: 60 }}><Bar value={i.scores?.demand ?? 0} /></td>
                      <td style={{ minWidth: 60 }}><Bar value={i.scores?.ctr ?? 0} /></td>
                      <td className="mono">{usd(i.scores?.rpm, i.format === "short" ? 3 : 2)}</td>
                      <td className="mono">{i.scores?.risk ?? "—"}</td>
                      <td className="right mono">{num(i.scores?.expected_views)}</td>
                      <td className="right"><span className="score gold">{i.score.toFixed(0)}</span></td>
                      <td><Badge>{i.status}</Badge></td>
                      <td>{["backlog", "approved"].includes(i.status) && <Btn sm kind="primary" onClick={() => produce(i.id)}>Produzir</Btn>}</td>
                    </tr>))}</tbody>
                </table></div>
              </Card>
            ) : (
              <div className="grid g3">
                {(series ?? []).map((s) => (
                  <Card key={s.series} title={`#${s.series}`} action={<span className="score gold">{s.avg_score}</span>}>
                    <div className="small muted">{s.count} ideias · {s.published} publicadas</div>
                    <ul className="small">{s.top.map((t: string) => <li key={t}>{t}</li>)}</ul>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </Page>
  );
}
