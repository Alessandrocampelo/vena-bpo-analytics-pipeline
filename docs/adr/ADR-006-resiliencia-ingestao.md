# ADR-006 — Resiliência de ingestão: concorrência limitada + backoff na API, parser em cadeia no scraping

**Status:** Aceita — Dia 1 (implementação detalhada no Dia 3)

## Contexto

Testes de reconhecimento feitos ao vivo (`docs/01-descoberta.md`):

- API: 15 requisições **sequenciais** → 100% `200`. 25 requisições
  **em paralelo** → as ~14 primeiras `200`, o resto `429` em cascata. Sem
  header `Retry-After` observado nas respostas testadas.
- Scraping: 3 requisições consecutivas ao mesmo endpoint devolveram **3
  estruturas HTML diferentes** (tabela com classes CSS; grid de `div`s com
  `data-*`; tabela "comparativo" com produto+categoria concatenados num
  único campo). Confirma que o drift é por request, não por dia.

## Decisão

**Ingestão da API:**
- Concorrência limitada por semáforo a **3-4 requisições simultâneas**
  (margem de segurança abaixo do limiar de ~14 observado).
- Retry com backoff exponencial + jitter (`tenacity`) em `429` e `500`,
  teto de 5-6 tentativas por página, respeitando `Retry-After` **se**
  presente na resposta (defensivo, mesmo não tendo sido observado nos
  testes).
- Falha de uma página isolada após esgotar tentativas: registrar página
  como pendente e abortar o asset com erro explícito se 3 páginas
  seguidas falharem (circuit breaker simples) — não seguir "quase
  completo" silenciosamente para um dataset que será usado num dashboard
  financeiro.

**Ingestão do scraping:**
- Parser estruturado como **cadeia de estratégias**, tentadas em ordem:
  1. Layout A (tabela `#tabela-precos`, classes `.nome/.categoria/.preco/
     .concorrente/.estoque`)
  2. Layout B (`#price-grid` com `.price-card[data-product][data-store]`)
  3. Layout C (tabela `.comparativo`, com split de `"Produto (Categoria)"`
     por regex)
  4. Fallback genérico: heurística por texto (regex de padrão monetário
     `R?\$?\s?\d+[.,]\d{2}` + agrupamento por estrutura de tags irmãs)
- Se nenhuma estratégia (incluindo o fallback) extrair linhas, a
  execução **não derruba o pipeline inteiro**: grava o HTML bruto em
  `landing/scraping/failed/` para inspeção, marca asset check
  `schema_reconhecido` como `WARN`, e o asset de preços de concorrentes
  fica "stale" por um dia (aceitável — não é dado crítico de receita
  como `itens_pedido`).
- Cada linha extraída carrega o campo técnico `_parser_strategy` (A/B/C/
  fallback) — usado como métrica de observabilidade: se a proporção de
  linhas vindas do fallback subir, é sinal de degradação silenciosa
  mesmo sem falha dura.

## Alternativas consideradas

- **Um único seletor CSS "robusto" tentando cobrir os 3 layouts com XPath
  genérico**: descartada — os 3 layouts têm estruturas de DOM
  fundamentalmente diferentes (tabela vs. div vs. tabela com campo
  concatenado); um seletor único viraria uma regex ilegível tentando
  cobrir casos que são melhor expressos como estratégias separadas e
  testáveis isoladamente.
- **Sem limite de concorrência na API, só retry**: descartada — sem
  limitar concorrência de saída, o pipeline geraria 429 sistematicamente
  a cada execução (25 réplicas simultâneas já é suficiente para saturar,
  segundo o teste), desperdiçando tentativas de retry em vez de evitar o
  problema na origem.
- **Falha proposital "fabricada"**: decidido não fabricar uma falha
  artificial no parser — o próprio schema drift real já gera falha
  orgânica em execuções reais. Para garantir algo demonstrável de forma
  determinística na apresentação de 30-40min (sem depender de qual
  layout a API sortear na hora), será mantida uma flag de configuração
  (`FORCE_UNKNOWN_LAYOUT=true`) que força o asset a cair no fallback/erro
  de propósito, isolada do código de produção do parser.

## Consequências

- Positivo: pipeline sobrevive a rate limit e a drift real sem
  intervenção manual; ambos os requisitos obrigatórios do teste
  ("Resiliência da ingestão", que pesa 25% — o maior peso do teste) são
  atendidos com evidência, não só declaração.
- Positivo: métrica de "% de linhas via fallback" dá visibilidade de
  degradação antes que vire falha total — atende ao requisito de
  observabilidade também.
- Negativo: mais código de parsing para manter (4 estratégias em vez de
  1) — aceito porque é exatamente o ponto que o teste avalia com peso
  maior.
