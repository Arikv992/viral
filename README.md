# VIRAL·OPS — plataforma de canais dark para YouTube, Shorts e (em breve) TikTok

Um sistema de ponta a ponta que decide **que canais criar**, **que vídeos fazer**, **como produzi-los ao menor custo
com a maior qualidade**, **quando publicar** e **o que escalar, republicar ou matar** — com cada cêntimo registado e o
orçamento reinvestido automaticamente onde rende mais.

```
 Radar de tendências ─┐
 Estratégia de canais ├─► Banco de ideias ─► Fábrica de vídeos ─► Guardião ─► Publicação ─► Análise & escala ─┐
 Público & CPM ───────┘         ▲                (planner de ROI)   (políticas)  (horários $)   (veredictos)     │
                                └──────────────── vencedores → sequelas · joias escondidas → republicar ◄──────┘
                                              Cofre de lucro: orçamento, reinvestimento, alocação por canal
                                              Piloto automático: o ciclo inteiro a cada N horas
```

## Arranque rápido

```bash
cp .env.example .env      # opcional: preenche as chaves que tiveres
./run.sh                  # instala, compila a UI e abre em http://localhost:8000
```

Requisitos: Python 3.10+ e Node 18+. **Não é preciso instalar ffmpeg** (vem embutido via `imageio-ffmpeg`).
Desenvolvimento da UI com hot-reload: `cd backend && uvicorn app.main:app --reload` + `cd web && npm run dev` (porta 5173).
Testes: `cd backend && pytest` (23 testes, incluindo render real de vídeos com ffmpeg).

### Chaves (todas opcionais — cada uma desbloqueia uma camada)

| Chave | Desbloqueia | Custo |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude: estratégia, guiões com engenharia de retenção, packaging, análise de público, diagnóstico | pago por token (registado no Cofre) |
| `YOUTUBE_API_KEY` | vídeos outlier, comentários da concorrência, concorrência por nicho | grátis (10k unidades/dia) |
| `GOOGLE_CLIENT_SECRETS` | upload + agendamento `publishAt`, YouTube Analytics (CTR, retenção, receita) | grátis |
| `PEXELS_API_KEY` / `PIXABAY_API_KEY` | vídeo/foto de stock | grátis |
| `FAL_API_KEY` | imagens Flux (branding, cenas, thumbnails) e vídeo IA Kling/Veo | pago, só quando o ROI compensa |
| `ELEVENLABS_API_KEY` | voz premium | pago, só quando o ROI compensa |

Sem chaves: heurísticas, voz grátis (Edge TTS → Piper local), arte procedural, exportação para upload manual.

## As secções

### 1. Radar de tendências — o que está a subir e quanto tempo vai durar
Recolhe de **Google Trends RSS**, **autocomplete do YouTube** (o que as pessoas escrevem), **Reddit** (top semanal dos
subreddits do nicho), **YouTube Data API** (vídeos *outlier*: views ≫ subscritores = foi o tema que puxou, não o canal)
e **séries diárias do Wikipedia** (até 18 meses de interesse público).
A série temporal é classificada matematicamente (`services/trends.py::analyze_series`):
- **Flash** — pico recente sobre base baixa; a vida útil é estimada pelo decaimento exponencial desde o pico → Shorts em 48h.
- **Onda** — crescimento sustentado → série de 3-8 vídeos.
- **Evergreen** — base alta e estável face ao pico → investir em longos.
- **Sazonal** — autocorrelação anual → produzir antes da época.

Score de oportunidade = momentum × longevidade × (1 − saturação) × valor do nicho (RPM). O Claude acrescenta veredicto
(`ride_now` / `build_series` / `evergreen_asset` / `skip`), dias de vida e 3 ângulos dark por tema.

### 2. Estratégia de canais — que canais criar e com que nome
Catálogo de 26 nichos faceless (`knowledge/niches.py`) com RPM longo/Short, concorrência, evergreen, viralidade,
adequação a IA/recortes, **risco de políticas** e complexidade. O RPM é convertido em **RPM efetivo** pela mistura
real de países de cada língua (`knowledge/geo.py`) — p.ex. um canal em português rende ~21% de um canal em inglês com a
mesma audiência. O Claude gera conceitos de canal com posicionamento único, pilares, estilo de assinatura, caminho
até à monetização, projeção a 12 meses, **critérios de corte** e os primeiros 10 vídeos (cluster temático). O gerador
de nomes pontua memorabilidade/clareza e verifica se o **@handle** está livre.

### 3. Estúdio de canal — descrição, foto de perfil e capa
Kit completo: descrição SEO (os 150 primeiros caracteres com a palavra-chave aparecem na pesquisa), keywords, paleta,
**avatar 800×800** legível a 48px, **banner 2560×1440** com o texto dentro da safe-area de telemóvel (1546×423),
marca d'água 150×150 (sobreposta em todos os vídeos), trailer de 45s e comentário fixado modelo. Com `FAL_API_KEY` as
imagens são geradas por Flux (Pro no modo premium); sem chave, arte procedural + tipografia.

### 4. Público & CPM — quem atingir e o que procuram
Tabela de RPM por país com **quota da receita** (não de views), recolha de centenas de pesquisas reais via autocomplete
("alphabet soup" + prefixos de pergunta) e comentários dos vídeos outlier da concorrência. O Claude transforma isto
em persona, desejos, medos, perguntas recorrentes, **lacunas de conteúdo monetizáveis**, as palavras exatas do
público, fórmulas de título e o segmento de maior valor. O brief fica guardado no canal e alimenta as ideias.

### 5. Banco de ideias — organizar e consolidar
Cada ideia tem título, gancho literal dos primeiros 3 segundos, ângulo e scores (procura, CTR, RPM do formato,
momentum, evergreen, facilidade, risco) → **views e receita esperadas**. Duplicados são fundidos (Jaccard) e as
ideias agrupadas em **séries** (clusters ensinam o algoritmo mais depressa). Quadro kanban, tabela e vista de séries.

### 6. Fábrica de vídeos — IA, recorte ou stock? (decidido por ROI)
O **Planner** (`production/planner.py`) calcula para cada ideia o custo (LLM + voz + visuais + vídeo IA + render), o
valor esperado (views × multiplicador de qualidade do modo × RPM) e o risco, e escolhe o maior lucro que cabe no teto
diário do canal:

| Modo | Quando ganha |
|---|---|
| **Imagens IA + narração (Ken Burns)** | história, mistério, espaço, terror — visual único e coerente |
| **Stock + narração** | finanças, engenharia, natureza — qualidade alta a custo ~0 |
| **Vídeo IA (Kling/Veo)** | Shorts de alto potencial ou "hero shots" pontuais — só se o retorno pagar |
| **História em texto (estilo Reddit)** | volume em Shorts a custo mínimo |
| **Recorte + comentário** | só com fonte Creative Commons ou autorização — custo ~0 |

Melhorias pagas (voz premium, Flux Dev/Pro, clips de vídeo IA) só entram quando **retorno marginal ≥ 3× custo
marginal**. O pipeline: guião com engenharia de retenção → packaging (5 títulos com gatilhos diferentes, thumbnail,
descrição, tags, comentário) → Guardião (antes de gastar em visuais) → voz cena a cena (sincronia exata) → visuais em
paralelo → montagem ffmpeg (Ken Burns, cortes, **legendas palavra-a-palavra animadas**, música com *ducking*,
marca d'água, loudness −14 LUFS) → thumbnail de alto contraste → Guardião final.

### 7. Guardião de monetização (a secção que acrescentei, com o Cofre e o Piloto)
Nada é publicado sem passar aqui: termos que limitam anúncios no título e nos primeiros 30s (com correção automática),
licença obrigatória nos recortes, comentário original suficiente (política de conteúdo reutilizado), **semelhança com
os últimos 40 vídeos do canal** (conteúdo "inautêntico"/em massa), limites técnicos, rótulo de conteúdo sintético.
A revisão por Claude corre só onde o risco a justifica (longos, nichos sensíveis, alertas) — uma desmonetização custa
mais do que qualquer poupança.

### 8. Publicação — horários e frequência
Para cada uma das 168 horas da semana soma-se a atividade esperada de cada país ponderada por **quota de audiência ×
RPM do país**, publicando antes do pico (longos ~2h, Shorts ~1h). Com ≥20 vídeos medidos, o mapa passa a aprender com
as views às 24h dos teus próprios vídeos. A frequência depende da fase do canal, do orçamento e da **canibalização
observada** (se mais uploads baixam as views por vídeo, reduz). Upload via API como privado + `publishAt`,
thumbnail, rótulo sintético e comentário inicial; sem OAuth, exporta uma pasta pronta (MP4 + thumbnail + metadata.json
com a hora ideal). TikTok: adaptador da Content Posting API pronto.

### 9. Análise & escala
Cada vídeo é comparado com a baseline do próprio canal à mesma idade (**outlier score**) e diagnosticado numa matriz
CTR × retenção: **escalar** (5 sequelas com prioridade máxima), **reembalar** (novo título aplicado no próprio vídeo via
API), **novo gancho**, **republicar joia escondida** (retenção/engajamento fortes, distribuição nula), **matar**
(série despromovida) ou aguardar. O Claude acrescenta novos títulos, ganchos e lições para o portefólio.

### 10. Cofre de lucro
Livro-razão de todos os custos (cada chamada ao Claude, imagem, segundo de vídeo IA, voz) e receitas (Analytics ou
manual). Orçamento mensal = base + **reinvestimento automático** de X% da receita do mês anterior. Alocação de capital
entre canais por **Thompson sampling** sobre o retorno por dólar, com piso de exploração para canais novos e alerta de
congelamento para quem falha os critérios de corte. P&L por canal/vídeo e projeção até ao YPP.

### 11. Piloto automático
A cada N horas: orçamento → radar → reposição do banco de ideias → realocação de capital → produção até cobrir a
frequência das próximas 48h (dentro do orçamento e acima do score mínimo) → agendamento → sincronização de métricas →
execução dos veredictos. Publica sozinho apenas com `auto_publish` ligado; caso contrário deixa tudo pronto para rever.

## Os prompts
`backend/app/prompts.py` contém os prompts-mestre: um system estável (em cache) que codifica o algoritmo (CTR ×
duração × satisfação; "viewed vs swiped" nos Shorts), a realidade da monetização (YPP, mid-rolls a partir de 8 min,
Q4, políticas de conteúdo reutilizado/inautêntico, anúncios limitados, rótulo sintético) e princípios de operador
(evidência, lucro, especificidade, qualidade como fosso). Cada tarefa tem o seu prompt com regras concretas — p.ex. o
guião de Short exige quebra de padrão em 2s, micro-revelação a cada 3-5s, loop aberto fechado no fim e última frase que
liga à primeira. Todas as respostas são JSON validado por schema (structured outputs), com o esforço de raciocínio
ajustado por tarefa (baixo para classificação, alto para guiões e estratégia) e custo lançado no Cofre.

## Arquitetura

```
backend/app/
  config.py, models.py, db.py, state.py   configuração, modelo de dados (SQLite), definições em runtime
  llm.py, prompts.py                       Claude (structured outputs, fallbacks, cache) + prompts-mestre
  knowledge/                               nichos, geografia/RPM, tabela de preços dos fornecedores
  services/
    trends.py, youtube_data.py             radar
    strategy.py, audience.py, branding.py  estratégia, público, estúdio
    ideas.py                               banco de ideias
    production/                            planner, guião, voz, visuais, legendas, montagem, thumbnails, recortes
    compliance.py                          guardião
    timing.py, publisher.py                horários, frequência, upload/exportação
    analytics.py                           diagnóstico e escala
    finance.py, autopilot.py               cofre, piloto automático
  api.py, main.py                          API REST + serve a UI
web/                                       React + Vite (UI em português)
```

Dados e media ficam em `data/` (base de dados, vídeos, kits, exportações). Música própria: coloca MP3 royalty-free em
`data/music/`; fundos para histórias em texto em `data/backgrounds/`.

## Limites honestos
- Os RPM/CPM do catálogo são estimativas de mercado de partida; o Analytics substitui-os pelos números reais.
- Sem `ANTHROPIC_API_KEY` os guiões são esqueletos estruturais (servem para testar o pipeline, não para publicar).
- Recortes só com licença CC ou autorização — por desenho. É o que mantém os canais monetizados.
- Thumbnails personalizadas exigem canal verificado no YouTube; comentários não podem ser fixados via API.
