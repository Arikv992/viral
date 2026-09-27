import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, ChannelPicker, Empty, Page, useAction, useChannels, useToast } from "../ui";

function Copy({ text }: { text: string }) {
  const toast = useToast();
  return <Btn sm kind="ghost" onClick={() => navigator.clipboard.writeText(text).then(() => toast("Copiado"))}>Copiar</Btn>;
}

export default function Studio() {
  const { data: channels, reload } = useChannels();
  const [cid, setCid] = useState<number | null>(null);
  const { busy, run } = useAction();
  useEffect(() => {
    if (!cid && channels?.length) setCid(channels.find((c) => c.status !== "killed")?.id ?? null);
  }, [channels, cid]);
  const ch = channels?.find((c) => c.id === cid);
  const kit = ch?.branding ?? {};
  const urls = ch?.branding_urls ?? {};
  const bust = `?v=${(kit.description ?? "").length}${kit.tagline ?? ""}`;

  const build = (premium: boolean) =>
    run("brand", async () => {
      await api.post(`/channels/${cid}/branding`, { premium });
      reload();
    }, "Kit de marca gerado");
  const setStatus = (status: string) => run("st", async () => { await api.patch(`/channels/${cid}`, { status }); reload(); });

  return (
    <Page kicker="Criar" title="Estúdio de canal"
      sub="Kit completo pronto a carregar no YouTube: descrição SEO (primeiros 150 caracteres com a palavra-chave), keywords, avatar legível a 48px, banner 2560×1440 com texto dentro da safe-area de telemóvel, marca d'água e trailer."
      actions={<>
        <ChannelPicker value={cid} onChange={setCid} channels={channels} />
        <Btn busy={busy === "brand"} disabled={!cid} onClick={() => build(false)}>Gerar kit</Btn>
        <Btn kind="primary" busy={busy === "brand"} disabled={!cid} onClick={() => build(true)}>Gerar kit premium (Flux Pro)</Btn>
      </>}>
      {!ch ? <Empty>Cria um canal em Estratégia de canais.</Empty> : (
        <>
          <Card>
            <div className="row spread">
              <div className="row">
                <h3 style={{ fontSize: 20 }}>{ch.name}</h3>
                <span className="mono faint">@{ch.handle}</span>
                <Badge tone={ch.status === "active" ? "teal" : undefined}>{ch.status}</Badge>
                <Badge>{ch.niche_key}</Badge><Badge>{ch.language}</Badge>
                {ch.has_youtube ? <Badge tone="teal">YouTube ligado</Badge> : <Badge tone="gold">YouTube por ligar</Badge>}
              </div>
              <div className="row">
                {ch.status !== "active" && <Btn sm onClick={() => setStatus("active")}>Ativar</Btn>}
                {ch.status === "active" && <Btn sm onClick={() => setStatus("paused")}>Pausar</Btn>}
                <a className="btn sm" href={`/api/publish/oauth/start/${ch.id}`}>Ligar YouTube (OAuth)</a>
              </div>
            </div>
          </Card>

          {!kit.description ? <div className="mt"><Empty>Ainda sem kit — carrega em “Gerar kit”.</Empty></div> : (
            <>
              <div className="card mt" style={{ padding: 0, overflow: "hidden" }}>
                {urls.banner_url && <img className="kit-banner" style={{ borderRadius: 0, border: 0 }} src={urls.banner_url + bust} alt="banner" />}
                <div className="row" style={{ padding: "0 22px 18px", marginTop: -48 }}>
                  {urls.avatar_url && <img className="kit-avatar" src={urls.avatar_url + bust} alt="avatar" />}
                  <div style={{ marginTop: 50 }}>
                    <h3 style={{ fontSize: 22 }}>{ch.name}</h3>
                    <div className="muted small">@{ch.handle} · {kit.tagline}</div>
                  </div>
                  <div className="row" style={{ marginLeft: "auto", marginTop: 50 }}>
                    {urls.avatar_url && <a className="btn sm" href={urls.avatar_url} download>Avatar 800×800</a>}
                    {urls.banner_url && <a className="btn sm" href={urls.banner_url} download>Banner 2560×1440</a>}
                    {urls.watermark_url && <a className="btn sm" href={urls.watermark_url} download>Marca d'água</a>}
                  </div>
                </div>
              </div>

              <div className="grid g2 mt">
                <Card title="Descrição do canal" action={<Copy text={kit.description} />}>
                  <p style={{ whiteSpace: "pre-wrap" }}>{kit.description}</p>
                  <div className="small faint">{kit.description.length} caracteres · primeiros 150 aparecem na pesquisa</div>
                </Card>
                <div className="stack">
                  <Card title="Keywords do canal" action={<Copy text={(kit.keywords ?? []).join(", ")} />}>
                    <div className="chip-list">{(kit.keywords ?? []).map((k: string) => <span key={k} className="chip">{k}</span>)}</div>
                  </Card>
                  <Card title="Paleta">
                    <div className="row">{(kit.palette ?? []).map((c: string) => (
                      <div key={c} className="stack" style={{ alignItems: "center", gap: 4 }}>
                        <div style={{ width: 54, height: 54, borderRadius: 10, background: c, border: "1px solid var(--line-2)" }} />
                        <span className="mono small">{c}</span>
                      </div>))}</div>
                  </Card>
                </div>
              </div>
              <div className="grid g3 mt">
                <Card title="Trailer do canal (45s)" action={<Copy text={kit.trailer_script} />}><p className="small">{kit.trailer_script}</p></Card>
                <Card title="Comentário fixado modelo" action={<Copy text={kit.first_comment_template} />}><p className="small">{kit.first_comment_template}</p></Card>
                <Card title="Prompts de imagem">
                  <details open><summary>Avatar</summary><p className="small muted">{kit.avatar_prompt}</p></details>
                  <details><summary>Banner</summary><p className="small muted">{kit.banner_prompt}</p></details>
                </Card>
              </div>
            </>
          )}
        </>
      )}
    </Page>
  );
}
