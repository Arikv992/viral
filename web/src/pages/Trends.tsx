import { useState } from "react";
import { api, num } from "../api";
import { Badge, Btn, Card, Empty, LONGEVITY, Page, Spark, useAction, useApi, VERDICT } from "../ui";

export default function Trends() {
  const { data: meta } = useApi<any>("/meta");
  const [niche, setNiche] = useState("");
  const { data: rows, reload } = useApi<any[]>(`/trends${niche ? `?niche=${niche}` : ""}`, [niche]);
  const [picked, setPicked] = useState<string[]>([]);
  const [geo, setGeo] = useState("US");
  const [lang, setLang] = useState("en");
  const [open, setOpen] = useState<number | null>(null);
  const [outliers, setOutliers] = useState<any[] | null>(null);
  const { busy, run } = useAction();

  const scan = () =>
    run("scan", async () => {
      await api.post("/trends/scan-sync", { niches: picked.length ? picked : null, geo, lang, use_llm: true });
      reload();
    }, "Scan concluído");

  return (
    <Page kicker="Descobrir" title="Radar de tendências"
      sub="Google Trends, autocomplete do YouTube, Reddit, vídeos outlier e séries do Wikipedia. Cada tema recebe momentum, classe de longevidade (flash → evergreen), dias de vida útil e um veredito."
      actions={<Btn kind="primary" busy={busy === "scan"} onClick={scan}>Fazer scan agora</Btn>}>
      <Card>
        <div className="row">
          <select value={geo} onChange={(e) => setGeo(e.target.value)}>
            {(meta?.countries ?? []).map((c: any) => <option key={c.code} value={c.code}>{c.code} · {c.name}</option>)}
          </select>
          <select value={lang} onChange={(e) => setLang(e.target.value)}>
            {(meta?.languages ?? []).map((l: any) => <option key={l.code} value={l.code}>{l.name}</option>)}
          </select>
          <select value={niche} onChange={(e) => setNiche(e.target.value)}>
            <option value="">Todos os nichos</option>
            {(meta?.niches ?? []).map((n: any) => <option key={n.key} value={n.key}>{n.name}</option>)}
          </select>
          <span className="faint small">Nichos a varrer (vazio = 8 principais):</span>
        </div>
        <div className="chip-list mt">
          {(meta?.niches ?? []).map((n: any) => (
            <label key={n.key} className="chip check">
              <input type="checkbox" checked={picked.includes(n.key)}
                onChange={(e) => setPicked(e.target.checked ? [...picked, n.key] : picked.filter((x) => x !== n.key))} />
              {n.name}
            </label>
          ))}
        </div>
      </Card>

      <Card className="mt" title={`Temas (${rows?.length ?? 0})`}>
        {!rows?.length ? <Empty>Sem tendências ainda — faz um scan.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Tema</th><th>Veredito</th><th>Longevidade</th><th className="right">Momentum</th><th className="right">Saturação</th><th>Série (Wikipedia)</th><th className="right">Oportunidade</th><th /></tr>
              </thead>
              <tbody>
                {rows.map((t) => {
                  const a = t.analysis ?? {};
                  return [
                    <tr key={t.id}>
                      <td style={{ maxWidth: 360 }}><b>{t.topic}</b><div className="small faint">{t.niche_key} · {t.source}</div></td>
                      <td>{a.verdict && <Badge tone={VERDICT[a.verdict]?.tone}>{VERDICT[a.verdict]?.label}</Badge>}</td>
                      <td><Badge tone={LONGEVITY[t.longevity]?.tone}>{LONGEVITY[t.longevity]?.label}</Badge><div className="small faint">~{a.longevity_days ?? t.longevity_days} dias</div></td>
                      <td className="right mono">{t.momentum.toFixed(0)}</td>
                      <td className="right mono">{t.saturation.toFixed(0)}</td>
                      <td><Spark values={t.series} /></td>
                      <td className="right"><span className="score gold">{t.opportunity.toFixed(0)}</span></td>
                      <td><Btn sm kind="ghost" onClick={() => setOpen(open === t.id ? null : t.id)}>{open === t.id ? "Fechar" : "Ver"}</Btn></td>
                    </tr>,
                    open === t.id && (
                      <tr key={`${t.id}-d`}>
                        <td colSpan={8} style={{ background: "var(--bg-2)" }}>
                          <div className="grid g3">
                            <div><h2>Porquê</h2><p>{a.why ?? "—"}</p><p className="small muted">Risco: {a.risks ?? "—"}</p></div>
                            <div><h2>Ângulos dark</h2><ul>{(a.dark_angles ?? []).map((x: string) => <li key={x}>{x}</li>)}</ul></div>
                            <div><h2>Diagnóstico da série</h2><pre className="mono small muted" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(t.evidence?.diagnostics ?? {}, null, 1)}</pre></div>
                          </div>
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card className="mt" title="Vídeos outlier (views ≫ subscritores = o tema puxou, não o canal)"
        action={<Btn sm busy={busy === "out"} disabled={!niche} onClick={() => run("out", async () => setOutliers(await api.get(`/trends/outliers?niche=${niche}&geo=${geo}&lang=${lang}`)))}>
          {niche ? "Procurar outliers do nicho" : "Escolhe um nicho"}</Btn>}>
        {outliers === null ? <p className="muted small">Requer YOUTUBE_API_KEY. Usa 1 pesquisa (100 unidades de quota).</p> :
          !outliers.length ? <Empty>Sem resultados (verifica a chave da YouTube API).</Empty> : (
            <div className="grid g4">
              {outliers.slice(0, 12).map((v) => (
                <a key={v.video_id} href={v.url} target="_blank" rel="noreferrer" className="card flat" style={{ padding: 10, color: "var(--text)" }}>
                  <img src={v.thumbnail} alt="" className="thumb" />
                  <div className="small" style={{ marginTop: 8, fontWeight: 600 }}>{v.title}</div>
                  <div className="row small faint" style={{ marginTop: 4 }}>
                    <Badge tone="gold">{v.outlier_ratio}×</Badge>{num(v.views)} views · {num(v.subs)} subs · {num(v.views_per_hour)}/h
                  </div>
                </a>
              ))}
            </div>
          )}
      </Card>
    </Page>
  );
}
