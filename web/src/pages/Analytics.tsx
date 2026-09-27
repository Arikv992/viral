import { useEffect, useState } from "react";
import { api, num, pct, usd } from "../api";
import { Badge, Btn, Card, ChannelPicker, Empty, Page, Stat, useAction, useApi, useChannels, VERDICT } from "../ui";

function MetricsForm({ pid, onDone }: { pid: number; onDone: () => void }) {
  const [m, setM] = useState({ views: 0, ctr: 0, avg_view_pct: 0, likes: 0, comments: 0, revenue_usd: 0 });
  const { busy, run } = useAction();
  return (
    <div className="row small">
      {(Object.keys(m) as (keyof typeof m)[]).map((k) => (
        <label key={k} className="f">{k}<input type="number" value={m[k]} onChange={(e) => setM({ ...m, [k]: Number(e.target.value) })} style={{ width: 90 }} /></label>
      ))}
      <Btn sm busy={busy === "s"} onClick={() => run("s", async () => { await api.post(`/analytics/metrics/${pid}`, m); onDone(); }, "Métricas gravadas")}>Gravar</Btn>
    </div>
  );
}

export default function Analytics() {
  const { data: channels } = useChannels();
  const [cid, setCid] = useState<number | null>(null);
  useEffect(() => { if (!cid && channels?.length) setCid(channels[0].id); }, [channels, cid]);
  const { data: rows, reload } = useApi<any[]>(cid ? `/analytics/performance?channel_id=${cid}` : null, [cid]);
  const { data: pubs, reload: reloadPubs } = useApi<any[]>(cid ? `/publications?channel_id=${cid}` : null, [cid]);
  const [diag, setDiag] = useState<any | null>(null);
  const [acted, setActed] = useState<any | null>(null);
  const [manual, setManual] = useState<number | null>(null);
  const { busy, run } = useAction();

  const sync = () => run("sync", async () => { const r = await api.post(`/analytics/sync/${cid}`); reload(); return r; }, "Métricas sincronizadas");
  const diagnose = () => run("diag", async () => { setDiag(await api.post(`/analytics/diagnose/${cid}`)); reload(); });
  const act = () => run("act", async () => { setActed(await api.post(`/analytics/act/${cid}`)); reload(); }, "Vereditos executados");

  const counts = diag?.counts ?? {};
  return (
    <Page kicker="Distribuir" title="Análise & escala"
      sub="Cada vídeo contra a baseline do próprio canal à mesma idade (outlier). Matriz CTR × retenção decide: escalar vencedores, reembalar conteúdo bom mal embalado, novo gancho quando a retenção cai cedo, republicar joias escondidas, matar o que falha em tudo."
      actions={<>
        <ChannelPicker value={cid} onChange={setCid} channels={channels} />
        <Btn busy={busy === "sync"} disabled={!cid} onClick={sync}>Sincronizar YouTube</Btn>
        <Btn busy={busy === "diag"} disabled={!cid} onClick={diagnose}>Diagnosticar</Btn>
        <Btn kind="primary" busy={busy === "act"} disabled={!cid} onClick={act}>Executar vereditos</Btn>
      </>}>
      {diag && (
        <div className="grid g4">
          <Stat label="Escalar" value={counts.scale ?? 0} tone="gold" sub="vencedores → 5 sequelas cada" />
          <Stat label="Republicar / novo gancho" value={(counts.republish ?? 0) + (counts.rehook ?? 0)} tone="teal" sub="joias escondidas" />
          <Stat label="Reembalar" value={counts.repackage ?? 0} sub="novo título/thumbnail" />
          <Stat label="Matar" value={counts.kill ?? 0} tone="red" sub="série despromovida" />
        </div>
      )}
      {acted && <div className="note mt">Executado: {acted.scaled} escalados ({acted.ideas_created} ideias novas), {acted.republish} republicações, {acted.repackaged} reembalados, {acted.killed_series} séries despromovidas.</div>}
      {diag?.lessons?.length > 0 && (
        <Card className="mt" title="Lições do portefólio"><ul>{diag.lessons.map((l: string) => <li key={l}>{l}</li>)}</ul></Card>
      )}

      <Card className="mt" title="Desempenho">
        {!rows?.length ? <Empty>Sem métricas. Liga o YouTube e sincroniza, ou introduz métricas manualmente abaixo.</Empty> : (
          <div className="table-wrap"><table>
            <thead><tr><th>Vídeo</th><th className="right">Idade</th><th className="right">Views</th><th className="right">Outlier</th><th className="right">CTR</th><th className="right">Retenção</th><th className="right">Engaj.</th><th className="right">Receita</th><th className="right">Custo</th><th>Veredito</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.publication_id}>
                <td style={{ maxWidth: 340 }}><b>{r.title}</b><div className="small faint">{r.format} · {r.mode}{r.series && ` · #${r.series}`}</div>
                  {diag && (() => { const d = diag.videos.find((x: any) => x.publication_id === r.publication_id); return d ? <div className="small muted">{d.why}{d.new_titles?.length ? ` → ${d.new_titles[0]}` : ""}</div> : null; })()}</td>
                <td className="right mono">{Math.round(r.age_hours)}h</td>
                <td className="right mono">{num(r.views)}</td>
                <td className={`right mono ${r.outlier >= 1.5 ? "gold" : r.outlier < 0.4 ? "red" : ""}`}>{r.outlier}×</td>
                <td className="right mono">{pct(r.ctr, 1)}</td>
                <td className="right mono">{pct(r.avg_view_pct)}</td>
                <td className="right mono">{pct(r.engagement, 1)}</td>
                <td className="right mono">{usd(r.revenue)}</td>
                <td className="right mono">{usd(r.cost, 3)}</td>
                <td>{r.verdict && <Badge tone={VERDICT[r.verdict]?.tone}>{VERDICT[r.verdict]?.label}</Badge>}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </Card>

      <Card className="mt" title="Métricas manuais (vídeos exportados / sem OAuth)">
        {!pubs?.length ? <Empty>Sem publicações.</Empty> : (
          <div className="stack">
            <select value={manual ?? ""} onChange={(e) => setManual(Number(e.target.value) || null)}>
              <option value="">Escolhe uma publicação…</option>
              {pubs.map((p) => <option key={p.id} value={p.id}>#{p.id} {p.title}</option>)}
            </select>
            {manual && <MetricsForm pid={manual} onDone={() => { reload(); reloadPubs(); }} />}
          </div>
        )}
      </Card>
    </Page>
  );
}
