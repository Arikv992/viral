import { useEffect, useState } from "react";
import { api, usd, when } from "../api";
import { Badge, Btn, Card, Empty, Page, useAction, useApi } from "../ui";

const CAP_LABEL: Record<string, [string, string]> = {
  llm: ["Claude (cérebro)", "ANTHROPIC_API_KEY — guiões, estratégia, análise"],
  youtube_data: ["YouTube Data API", "YOUTUBE_API_KEY — outliers, comentários, concorrência"],
  youtube_oauth: ["YouTube OAuth", "GOOGLE_CLIENT_SECRETS — upload, agendamento, Analytics"],
  stock_media: ["Stock grátis", "PEXELS_API_KEY / PIXABAY_API_KEY"],
  ai_images: ["Imagens IA", "FAL_API_KEY — Flux"],
  ai_video: ["Vídeo IA", "FAL_API_KEY — Kling/Veo"],
  premium_voice: ["Voz premium", "ELEVENLABS_API_KEY"],
  tiktok: ["TikTok", "TIKTOK_CLIENT_KEY/SECRET (futuro)"],
};

export default function Autopilot() {
  const { data: status, reload } = useApi<any>("/status");
  const { data: runs, reload: reloadRuns } = useApi<any[]>("/autopilot/runs", [], 10000);
  const [form, setForm] = useState<any | null>(null);
  const [dry, setDry] = useState<any | null>(null);
  const { busy, run } = useAction();
  useEffect(() => { if (status && !form) setForm(status.settings); }, [status, form]);

  const save = () => run("save", async () => { await api.put("/settings", { values: form }); reload(); }, "Definições guardadas");
  const start = () => run("run", async () => { await api.post("/autopilot/run", { dry_run: false }); reloadRuns(); }, "Ciclo iniciado em segundo plano");
  const simulate = () => run("dry", async () => setDry(await api.post("/autopilot/run", { dry_run: true })));

  return (
    <Page kicker="Comando" title="Piloto automático"
      sub="O ciclo completo sem intervenção: radar → ideias → alocação de capital → produção dentro do orçamento → agendamento nos melhores horários → sincronização de métricas → escalar/republicar/matar. Por segurança, publica sozinho apenas com “publicação automática” ligada."
      actions={<><Btn busy={busy === "dry"} onClick={simulate}>Simular ciclo</Btn><Btn kind="primary" busy={busy === "run"} onClick={start}>Correr ciclo agora</Btn></>}>
      <div className="grid g2">
        <Card title="Regras do piloto">
          {form && (
            <div className="stack">
              <label className="check"><input type="checkbox" checked={!!form.autopilot_enabled} onChange={(e) => setForm({ ...form, autopilot_enabled: e.target.checked })} />Ligar piloto automático (agendador em background)</label>
              <label className="check"><input type="checkbox" checked={!!form.auto_publish} onChange={(e) => setForm({ ...form, auto_publish: e.target.checked })} />Publicação automática (sem revisão humana)</label>
              <div className="row">
                <label className="f">Intervalo (horas)<input type="number" min={1} value={form.autopilot_interval_hours} onChange={(e) => setForm({ ...form, autopilot_interval_hours: Number(e.target.value) })} style={{ width: 100 }} /></label>
                <label className="f">Máx. vídeos por ciclo<input type="number" min={0} value={form.max_videos_per_cycle} onChange={(e) => setForm({ ...form, max_videos_per_cycle: Number(e.target.value) })} style={{ width: 100 }} /></label>
                <label className="f">Score mínimo da ideia<input type="number" min={0} max={100} value={form.min_idea_score} onChange={(e) => setForm({ ...form, min_idea_score: Number(e.target.value) })} style={{ width: 100 }} /></label>
              </div>
              <div className="row">
                <label className="f">Orçamento base mensal (USD)<input type="number" min={0} value={form.monthly_budget_usd} onChange={(e) => setForm({ ...form, monthly_budget_usd: Number(e.target.value) })} style={{ width: 140 }} /></label>
                <label className="f">Reinvestir da receita (%)<input type="number" min={0} max={100} value={Math.round(form.reinvest_ratio * 100)} onChange={(e) => setForm({ ...form, reinvest_ratio: Number(e.target.value) / 100 })} style={{ width: 120 }} /></label>
              </div>
              <Btn kind="primary" busy={busy === "save"} onClick={save} style={{ alignSelf: "flex-start" }}>Guardar</Btn>
            </div>
          )}
        </Card>
        <Card title="Integrações">
          {status && Object.entries(status.capabilities).map(([k, v]) => (
            <div key={k} className="row spread" style={{ padding: "7px 0", borderBottom: "1px solid var(--line)" }}>
              <div><b>{CAP_LABEL[k]?.[0] ?? k}</b><div className="small faint">{CAP_LABEL[k]?.[1]}</div></div>
              {v ? <Badge tone="teal">ativo</Badge> : <Badge>desligado</Badge>}
            </div>
          ))}
          <p className="small muted mt">Sem chaves a plataforma funciona em modo grátis: heurísticas, voz Edge/Piper, arte procedural e exportação. Cada chave desbloqueia uma camada de qualidade — o Planner só a usa quando o ROI compensa.</p>
        </Card>
      </div>

      {dry && (
        <Card className="mt" title="Simulação (nada foi gasto)">
          {dry.steps.map((s: any) => (
            <div key={s.step} style={{ padding: "6px 0", borderBottom: "1px solid var(--line)" }}>
              <b className="gold">{s.step}</b> <span className="mono small muted">{JSON.stringify(s.result).slice(0, 400)}</span>
            </div>
          ))}
        </Card>
      )}

      <Card className="mt" title="Execuções">
        {!runs?.length ? <Empty>Nenhum ciclo corrido ainda.</Empty> : runs.map((r) => (
          <details key={r.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
            <summary>
              <Badge tone={r.status === "ok" ? "teal" : r.status === "error" ? "red" : "blue"}>{r.status}</Badge> #{r.id} · {when(r.started_at)} {r.finished_at ? `→ ${when(r.finished_at)}` : "(a correr)"}
            </summary>
            <div className="log mt">
              {(r.summary?.steps ?? []).map((s: any) => <div key={s.step}><b>{s.step}</b>{JSON.stringify(s.result).slice(0, 600)}</div>)}
              {r.summary?.error && <div className="red">{r.summary.error}</div>}
            </div>
          </details>
        ))}
        {status && <p className="small faint mt">Orçamento restante este mês: {usd(status.budget.remaining)}</p>}
      </Card>
    </Page>
  );
}
