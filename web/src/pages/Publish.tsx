import { useEffect, useState } from "react";
import { api, when } from "../api";
import { Badge, Btn, Card, ChannelPicker, Empty, Heatmap, Page, Tabs, useAction, useApi, useChannels } from "../ui";

const PSTATUS: Record<string, any> = { scheduled: "blue", published: "teal", exported: "gold", failed: "red" };

export default function Publish() {
  const { data: channels } = useChannels();
  const [cid, setCid] = useState<number | null>(null);
  useEffect(() => { if (!cid && channels?.length) setCid(channels[0].id); }, [channels, cid]);
  const { data: plan } = useApi<any>(cid ? `/publish/plan/${cid}` : null, [cid]);
  const { data: pubs, reload } = useApi<any[]>(cid ? `/publications?channel_id=${cid}` : null, [cid], 15000);
  const [fmt, setFmt] = useState<"short" | "long">("short");
  const { busy, run } = useAction();
  const ch = channels?.find((c) => c.id === cid);

  const schedule = (now: boolean) => run("sch", async () => {
    const r = await api.post<any[]>(`/publish/schedule/${cid}?publish_now=${now}`);
    reload();
    return r;
  }, now ? "Agendado e enviado" : "Agendado nos melhores horários");
  const publishOne = (id: number) => run(`p${id}`, async () => { await api.post(`/publish/${id}`); reload(); }, "Publicação processada");

  return (
    <Page kicker="Distribuir" title="Publicação"
      sub="Horários escolhidos para maximizar RECEITA: atividade de cada país × quota de audiência × RPM do país, publicando antes do pico (longos ~2h, Shorts ~1h). Com 20+ vídeos medidos, o mapa aprende com os teus próprios dados."
      actions={<>
        <ChannelPicker value={cid} onChange={setCid} channels={channels} />
        <Btn busy={busy === "sch"} disabled={!cid} onClick={() => schedule(false)}>Agendar vídeos prontos</Btn>
        <Btn kind="primary" busy={busy === "sch"} disabled={!cid} onClick={() => schedule(true)}>Agendar e publicar</Btn>
      </>}>
      {!ch ? <Empty>Cria um canal primeiro.</Empty> : (
        <>
          {!ch.has_youtube && <div className="note warn">Este canal ainda não tem o YouTube ligado: os vídeos são <b>exportados</b> (MP4 + thumbnail + metadata.json com a hora ideal) para upload manual. Liga o OAuth no Estúdio de canal para publicação automática com agendamento.</div>}
          <div className="grid g-side mt">
            <Card title="Mapa de valor por hora (UTC)" action={<Tabs value={fmt} onChange={setFmt} options={[["short", "Shorts"], ["long", "Longos"]]} />}>
              {plan ? <Heatmap data={plan.heatmap[fmt]} /> : "A calcular…"}
              <div className="small faint mt">Mais claro = mais receita esperada ao publicar nessa hora.</div>
            </Card>
            <Card title="Frequência recomendada">
              {plan && (
                <>
                  <div className="row" style={{ gap: 24 }}>
                    <div className="stat"><div className="label">Shorts / dia</div><div className="value gold">{plan.frequency.shorts_per_day}</div></div>
                    <div className="stat"><div className="label">Longos / semana</div><div className="value gold">{plan.frequency.long_per_week}</div></div>
                  </div>
                  <Badge>{plan.frequency.stage}</Badge>
                  <ul className="small muted">{plan.frequency.reasons.map((r: string) => <li key={r}>{r}</li>)}</ul>
                </>
              )}
            </Card>
          </div>
          <Card className="mt" title={`Melhores horários — ${fmt === "short" ? "Shorts" : "Longos"}`}>
            {plan && (
              <table>
                <thead><tr><th>#</th><th>UTC</th><th>Hora local da audiência</th><th className="right">Valor</th></tr></thead>
                <tbody>{plan.slots[fmt].map((s: any, i: number) => (
                  <tr key={i}><td className="mono">{i + 1}</td><td className="mono">{s.day} {String(s.hour_utc).padStart(2, "0")}:00</td>
                    <td className="small">{Object.entries(s.local).map(([g, t]) => `${g}: ${t}`).join(" · ")}</td>
                    <td className="right mono gold">{(s.score * 100).toFixed(0)}</td></tr>))}</tbody>
              </table>
            )}
          </Card>
          <Card className="mt" title="Calendário de publicações">
            {!pubs?.length ? <Empty>Nada agendado. Produz vídeos e carrega em “Agendar vídeos prontos”.</Empty> : (
              <table>
                <thead><tr><th /><th>Título</th><th>Formato</th><th>Quando</th><th>Estado</th><th /></tr></thead>
                <tbody>{pubs.map((p) => (
                  <tr key={p.id}>
                    <td style={{ width: 70 }}>{p.thumbnail_url && <img src={p.thumbnail_url} className="thumb" alt="" />}</td>
                    <td><b>{p.title}</b>{p.attempt > 1 && <> <Badge tone="teal">republicação</Badge></>}
                      <div className="small faint">{p.url && (p.url.startsWith("http") ? <a href={p.url} target="_blank" rel="noreferrer">{p.url}</a> : <span className="mono">{p.url}</span>)}</div>
                      {p.diagnosis?.error && <div className="small red">{p.diagnosis.error}</div>}</td>
                    <td>{p.format}</td>
                    <td className="mono small">{when(p.scheduled_at)}</td>
                    <td><Badge tone={PSTATUS[p.status]}>{p.status}</Badge></td>
                    <td>{["scheduled", "failed"].includes(p.status) && <Btn sm busy={busy === `p${p.id}`} onClick={() => publishOne(p.id)}>Publicar já</Btn>}</td>
                  </tr>))}</tbody>
              </table>
            )}
          </Card>
        </>
      )}
    </Page>
  );
}
