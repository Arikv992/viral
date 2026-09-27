import { useEffect, useState } from "react";
import { api, usd, when } from "../api";
import { Badge, Btn, Card, ChannelPicker, Empty, Page, Tabs, useAction, useApi, useChannels } from "../ui";

const STATUS: Record<string, any> = { planned: undefined, scripting: "blue", rendering: "violet", ready: "teal", failed: "red", published: "gold" };

function PlanCompare({ ideaId }: { ideaId: number }) {
  const [p, setP] = useState<any | null>(null);
  const { busy, run } = useAction();
  useEffect(() => { run("plan", async () => setP(await api.post(`/production/plan/${ideaId}`))); }, [ideaId, run]);
  if (!p) return <span className="muted">{busy ? "A calcular…" : ""}</span>;
  return (
    <>
      <p className="note">{p.why}</p>
      <div className="table-wrap mt"><table>
        <thead><tr><th>Modo</th><th className="right">Custo</th><th className="right">Valor esperado</th><th className="right">Lucro esperado</th><th className="right">Qualidade</th><th>Risco</th><th>Notas</th></tr></thead>
        <tbody>{p.options.map((o: any) => (
          <tr key={o.mode} style={o.mode === p.mode ? { background: "rgba(245,179,1,.06)" } : undefined}>
            <td><b>{o.label}</b>{o.mode === p.mode && <> <Badge tone="gold">escolhido</Badge></>}</td>
            <td className="right mono">{usd(o.cost.total, 3)}</td>
            <td className="right mono">{usd(o.expected_value, 3)}</td>
            <td className={`right mono ${o.expected_profit >= 0 ? "teal" : "red"}`}>{usd(o.expected_profit, 3)}</td>
            <td className="right mono">{o.quality}×</td>
            <td className="mono">{o.risk}</td>
            <td className="small">{o.blocked ? <span className="red">{o.blocked}</span> : o.over_budget ? <span className="gold">acima do teto por vídeo</span> : o.notes.join("; ")}</td>
          </tr>))}</tbody>
      </table></div>
      <div className="small muted mt">Upgrades pagos: {p.upgrades.reasons.join(" · ")}</div>
    </>
  );
}

function VideoCard({ v, onChange }: { v: any; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const { busy, run } = useAction();
  const c = v.compliance ?? {};
  return (
    <Card>
      <div className="grid" style={{ gridTemplateColumns: v.format === "short" ? "180px 1fr" : "300px 1fr", gap: 16 }}>
        <div>
          {v.output_url ? <video className="vid" src={v.output_url} controls preload="metadata" poster={v.thumbnail_url ?? undefined} />
            : v.thumbnail_url ? <img className="thumb" src={v.thumbnail_url} alt="" /> : <div className="empty" style={{ padding: 20 }}>sem render</div>}
        </div>
        <div className="stack">
          <div className="row spread">
            <div className="row">
              <Badge tone={STATUS[v.status]}>{v.status}</Badge>
              <Badge>{v.format}</Badge>
              <Badge tone="violet">{v.mode}</Badge>
              {c.verdict && <Badge tone={c.verdict === "publish" ? "teal" : c.verdict === "block" ? "red" : "gold"}>Guardião: {c.verdict} ({c.risk})</Badge>}
              {c.synthetic_disclosure && <Badge tone="blue">rótulo IA</Badge>}
            </div>
            <span className="mono small faint">#{v.id} · {usd(v.cost_usd, 3)} · {v.duration_s ? `${v.duration_s.toFixed(0)}s` : ""}</span>
          </div>
          <h3>{v.packaging?.title ?? v.script?.title ?? "(a escrever guião…)"}</h3>
          {v.packaging?.titles?.length > 1 && <div className="small muted">Alternativas: {v.packaging.titles.slice(1).join(" · ")}</div>}
          {(c.issues ?? []).slice(0, 4).map((i: any, k: number) => (
            <div key={k} className="note warn small"><b>{i.area}:</b> {i.problem} → <i>{i.fix}</i></div>
          ))}
          <div className="row">
            <Btn sm kind="ghost" onClick={() => setOpen(!open)}>{open ? "Esconder detalhes" : "Guião, packaging e log"}</Btn>
            {["failed", "ready", "planned"].includes(v.status) && <Btn sm busy={busy === "rr"} onClick={() => run("rr", async () => { await api.post(`/videos/${v.id}/rerender`); onChange(); }, "A renderizar de novo")}>Re-renderizar</Btn>}
            {v.output_url && <a className="btn sm" href={v.output_url} download>Descarregar MP4</a>}
          </div>
          {open && (
            <div className="grid g2">
              <div>
                <h2>Cenas ({v.script?.scenes?.length ?? 0})</h2>
                <div className="log" style={{ maxHeight: 320 }}>
                  {(v.script?.scenes ?? []).map((s: any, k: number) => (
                    <div key={k}><b>{k + 1}</b>{s.narration}{s.on_screen_text && <span className="gold"> [{s.on_screen_text}]</span>}</div>
                  ))}
                </div>
              </div>
              <div>
                <h2>Descrição & tags</h2>
                <div className="log" style={{ whiteSpace: "pre-wrap", maxHeight: 160 }}>{v.packaging?.description}</div>
                <div className="chip-list mt">{(v.packaging?.tags ?? []).map((t: string) => <span className="chip small" key={t}>{t}</span>)}</div>
                <h2 className="mt">Log</h2>
                <div className="log">{(v.log ?? []).map((l: any, k: number) => <div key={k}><b>{when(l.at)}</b>{l.msg}</div>)}</div>
              </div>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

export default function Factory() {
  const { data: meta } = useApi<any>("/meta");
  const { data: channels } = useChannels();
  const [cid, setCid] = useState<number | null>(null);
  const [tab, setTab] = useState<"videos" | "modes" | "clips">("videos");
  const { data: videos, reload } = useApi<any[]>(`/videos${cid ? `?channel_id=${cid}` : ""}`, [cid], 5000);
  const { data: ideas } = useApi<any[]>(cid ? `/ideas?channel_id=${cid}` : "/ideas", [cid]);
  const [ideaId, setIdeaId] = useState<number | null>(null);
  const [mode, setMode] = useState<string>("");
  const [clip, setClip] = useState({ url: "", permission: false, count: 3, angle: "" });
  const [source, setSource] = useState<any | null>(null);
  const { busy, run } = useAction();
  const candidates = (ideas ?? []).filter((i) => ["backlog", "approved"].includes(i.status));

  const produce = () => run("prod", async () => { await api.post("/production/produce", { idea_id: ideaId, force_mode: mode || null }); setTab("videos"); reload(); }, "Produção iniciada");
  const inspect = () => run("insp", async () => setSource(await api.post("/production/inspect-source", { url: clip.url })));
  const clips = () => run("clips", async () => { await api.post("/production/clips", { ...clip, channel_id: cid }); setTab("videos"); reload(); }, "Recortes em produção");

  return (
    <Page kicker="Criar" title="Fábrica de vídeos"
      sub="O Planner escolhe, vídeo a vídeo, entre IA generativa, imagens IA, stock grátis, histórias em texto ou recortes licenciados — pelo lucro esperado dentro do orçamento. Voz premium, imagens melhores e clips de vídeo IA só entram quando o retorno marginal ≥ 3× o custo."
      actions={<><ChannelPicker value={cid} onChange={setCid} channels={channels} allowAll />
        <Tabs value={tab} onChange={setTab} options={[["videos", "Produção"], ["modes", "Modos & decisão"], ["clips", "Recortes"]]} /></>}>

      {tab === "modes" && (
        <>
          <div className="grid g3">
            {Object.entries(meta?.modes ?? {}).map(([k, m]: any) => (
              <Card key={k} title={m.label}>
                <p className="small muted">{m.desc}</p>
                <div className="row">{m.formats.map((f: string) => <Badge key={f}>{f}</Badge>)}</div>
              </Card>
            ))}
          </div>
          <Card className="mt" title="Decidir e produzir uma ideia">
            <div className="row">
              <select value={ideaId ?? ""} onChange={(e) => setIdeaId(Number(e.target.value) || null)} style={{ maxWidth: 520 }}>
                <option value="">Escolhe uma ideia…</option>
                {candidates.map((i) => <option key={i.id} value={i.id}>[{i.score.toFixed(0)}] {i.format} · {i.title}</option>)}
              </select>
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="">Modo: decisão automática (recomendado)</option>
                {Object.entries(meta?.modes ?? {}).map(([k, m]: any) => <option key={k} value={k}>Forçar: {m.label}</option>)}
              </select>
              <Btn kind="primary" disabled={!ideaId} busy={busy === "prod"} onClick={produce}>Produzir</Btn>
            </div>
            {ideaId && <div className="mt"><PlanCompare ideaId={ideaId} /></div>}
          </Card>
        </>
      )}

      {tab === "clips" && (
        <Card title="Recortes transformativos (Shorts a partir de vídeos longos)">
          <div className="note warn">Só fontes <b>Creative Commons (CC-BY)</b> ou com <b>autorização</b> (conteúdo teu, domínio público, acordo com o criador). Cada recorte leva gancho narrado original, título e contexto, e a atribuição vai na descrição — é isto que evita a política de conteúdo reutilizado e strikes de copyright.</div>
          <div className="row mt">
            <input placeholder="URL do vídeo (YouTube)" value={clip.url} onChange={(e) => setClip({ ...clip, url: e.target.value })} style={{ flex: 1, minWidth: 320 }} />
            <Btn busy={busy === "insp"} disabled={!clip.url} onClick={inspect}>Verificar licença</Btn>
          </div>
          {source && (
            <div className={`note mt ${source.is_cc ? "" : "bad"}`}>
              <b>{source.title}</b> — {source.channel} · {Math.round((source.duration ?? 0) / 60)} min · licença: <b>{source.license}</b> · legendas: {source.has_subs ? "sim" : "não"}
            </div>
          )}
          <div className="row mt">
            <input placeholder="Ângulo do teu canal (opcional)" value={clip.angle} onChange={(e) => setClip({ ...clip, angle: e.target.value })} style={{ flex: 1 }} />
            <label className="f">Nº de Shorts<input type="number" min={1} max={8} value={clip.count} onChange={(e) => setClip({ ...clip, count: Number(e.target.value) })} style={{ width: 90 }} /></label>
            <label className="check"><input type="checkbox" checked={clip.permission} onChange={(e) => setClip({ ...clip, permission: e.target.checked })} />Tenho autorização para usar este conteúdo</label>
            <Btn kind="primary" busy={busy === "clips"} disabled={!clip.url || !cid} onClick={clips}>{cid ? "Criar recortes" : "Escolhe um canal"}</Btn>
          </div>
        </Card>
      )}

      {tab === "videos" && (
        !videos?.length ? <Empty>Nenhum vídeo ainda. Produz a partir do Banco de ideias ou em “Modos & decisão”.</Empty> : (
          <div className="stack">{videos.map((v) => <VideoCard key={v.id} v={v} onChange={reload} />)}</div>
        )
      )}
    </Page>
  );
}
