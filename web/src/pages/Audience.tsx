import { useState } from "react";
import { api, usd } from "../api";
import { Badge, Bar, Btn, Card, ChannelPicker, Empty, Page, useAction, useApi, useChannels } from "../ui";

export default function Audience() {
  const { data: meta } = useApi<any>("/meta");
  const { data: channels } = useChannels();
  const [channelId, setChannelId] = useState<number | null>(null);
  const [niche, setNiche] = useState("finance_explained");
  const [language, setLanguage] = useState("en");
  const [geo, setGeo] = useState("US");
  const [res, setRes] = useState<any | null>(null);
  const { busy, run } = useAction();
  const { data: geoTable } = useApi<any[]>(`/audience/geo?niche=${niche}&language=${language}`, [niche, language]);

  const pickChannel = (id: number | null) => {
    setChannelId(id);
    const c = channels?.find((x) => x.id === id);
    if (c) {
      setNiche(c.niche_key);
      setLanguage(c.language);
      setGeo(c.target_geos?.[0] ?? "US");
    }
  };
  const analyze = () =>
    run("an", async () => setRes(await api.post("/audience", { niche_key: niche, language, geo, deep: true, channel_id: channelId })),
      channelId ? "Brief guardado no canal — as próximas ideias usam-no." : undefined);

  const b = res?.brief;
  return (
    <Page kicker="Descobrir" title="Público & CPM"
      sub="Quem atingir e onde está o dinheiro: RPM por país, o que o público escreve na pesquisa do YouTube e o que diz nos comentários da concorrência — convertido numa persona e em lacunas de conteúdo monetizáveis.">
      <Card>
        <div className="row">
          <ChannelPicker value={channelId} onChange={pickChannel} channels={channels} allowAll />
          <select value={niche} onChange={(e) => setNiche(e.target.value)}>
            {(meta?.niches ?? []).map((n: any) => <option key={n.key} value={n.key}>{n.name}</option>)}
          </select>
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            {(meta?.languages ?? []).map((l: any) => <option key={l.code} value={l.code}>{l.name}</option>)}
          </select>
          <select value={geo} onChange={(e) => setGeo(e.target.value)}>
            {(meta?.countries ?? []).map((c: any) => <option key={c.code} value={c.code}>{c.code}</option>)}
          </select>
          <Btn kind="primary" busy={busy === "an"} onClick={analyze}>Analisar público</Btn>
        </div>
      </Card>

      <div className="grid g-side mt">
        <Card title="Onde está o dinheiro (por país)">
          <table>
            <thead><tr><th>País</th><th className="right">Audiência</th><th className="right">RPM longo</th><th className="right">RPM Short</th><th>Quota da receita</th></tr></thead>
            <tbody>
              {(geoTable ?? []).map((g) => (
                <tr key={g.geo}>
                  <td><b>{g.geo}</b> <span className="faint small">{g.name}</span></td>
                  <td className="right mono">{(g.audience_share * 100).toFixed(0)}%</td>
                  <td className="right mono">{usd(g.rpm_long)}</td>
                  <td className="right mono">{usd(g.rpm_short, 3)}</td>
                  <td style={{ minWidth: 140 }}><div className="row"><div style={{ flex: 1 }}><Bar value={g.revenue_share * 100} /></div><span className="mono small">{(g.revenue_share * 100).toFixed(0)}%</span></div></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted mt">Regra de ouro: otimiza títulos, temas e horários para os países com maior quota de RECEITA, não de views.</p>
        </Card>
        <Card title="Economia do nicho">
          {res ? (
            <div className="stack">
              <div className="stat"><div className="label">RPM longo efetivo</div><div className="value gold">{usd(res.economics.rpm_long)}</div></div>
              <div className="stat"><div className="label">RPM Short efetivo</div><div className="value">{usd(res.economics.rpm_short, 3)}</div></div>
              <div className="small muted">{res.demand.count} pesquisas reais recolhidas · {res.comments_sample.length} comentários analisados</div>
              <Badge tone={res.source === "llm" ? "teal" : undefined}>{res.source === "llm" ? "Brief por Claude" : "Brief heurístico"}</Badge>
            </div>
          ) : <Empty>Corre a análise.</Empty>}
        </Card>
      </div>

      {b && (
        <>
          <div className="grid g3 mt">
            <Card title="Persona">
              <h3>{b.persona.name}</h3>
              <div className="small muted">{b.persona.age_range} · {b.persona.gender_skew}</div>
              <p className="small">{b.persona.wants}</p>
              <div className="small muted">Onde vê: {b.persona.watch_context}</div>
            </Card>
            <Card title="Desejos"><ul className="small">{b.core_desires.map((x: string) => <li key={x}>{x}</li>)}</ul></Card>
            <Card title="Medos"><ul className="small">{b.core_fears.map((x: string) => <li key={x}>{x}</li>)}</ul></Card>
          </div>
          <div className="grid g3 mt">
            <Card title="Lacunas de conteúdo ($)" className="hl"><ul className="small">{b.content_gaps.map((x: string) => <li key={x}>{x}</li>)}</ul></Card>
            <Card title="Perguntas recorrentes"><ul className="small">{b.recurring_questions.map((x: string) => <li key={x}>{x}</li>)}</ul></Card>
            <Card title="Fórmulas de título"><ul className="small">{b.title_formulas.map((x: string) => <li key={x}>{x}</li>)}</ul></Card>
          </div>
          <div className="grid g2 mt">
            <Card title="Segmento de maior valor"><p>{b.highest_value_segment}</p>
              <h2 className="mt">Evitar</h2><ul className="small">{b.avoid.map((x: string) => <li key={x}>{x}</li>)}</ul></Card>
            <Card title="Palavras do público">
              <div className="chip-list">{b.their_words.map((x: string) => <span key={x} className="chip">{x}</span>)}</div>
              <h2 className="mt">O que pesquisam (amostra)</h2>
              <div className="chip-list" style={{ maxHeight: 220, overflow: "auto" }}>
                {res.demand.queries.slice(0, 80).map((q: string) => <span key={q} className="chip small">{q}</span>)}
              </div>
            </Card>
          </div>
        </>
      )}
    </Page>
  );
}
