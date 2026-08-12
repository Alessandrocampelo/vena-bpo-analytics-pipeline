# ADR-007 — Idempotência via MERGE por chave natural, não append cego

**Status:** Aceita — Dia 1 (prova formal de idempotência no Dia 5)

## Contexto

Requisito obrigatório: "o pipeline deve poder rodar duas vezes seguidas
sem duplicar dados". A API de vendas não expõe filtro incremental
(`docs/01-descoberta.md`, seção 1) — não há como pedir ao servidor "só o
que mudou desde ontem". Ao mesmo tempo, o campo `updated_at` mostra que
registros **mudam de estado depois de criados** (ex.: pedido criado como
`pago`, `updated_at` avança dias depois quando o status vira
`cancelado`/`reembolsado`).

Isso cria duas necessidades simultâneas que uma estratégia só de "append"
não resolve: (1) não duplicar ao reprocessar o mesmo dia, e (2) capturar
mudança de status de um pedido já carregado anteriormente.

## Decisão

- **Raw**: cada execução faz o pull completo das 96 páginas (barato — 48k
  linhas) e grava em `MERGE` na tabela raw por `pedido_id`, usando
  `updated_at` como critério de "a linha nova é mais recente que a
  existente? então substitui". Chunks de `itens_pedido`/`clientes`/
  `produtos` idem, chave natural (`item_id`, `cliente_id`+`cpf`,
  `produto_id`).
- Arquivos de landing no GCS usam caminho **determinístico por data**
  (`dt=YYYY-MM-DD/`) — reprocessar o mesmo dia sobrescreve o mesmo
  prefixo, não acumula arquivo duplicado.
- **Staging/Mart (dbt)**: modelos incrementais com `unique_key` (
  `incremental_strategy: merge`) — reprocessar não duplica porque o merge
  é por chave de negócio, não por append.
- **Prova formal de idempotência** (Dia 5): materializar o DAG completo
  duas vezes seguidas contra o mesmo dia de dados e comparar `COUNT(*)` +
  checksum agregado (`SUM`/`hash` de colunas-chave) de cada tabela mart
  entre a 1ª e a 2ª execução — isso é um asset check formal, não só uma
  afirmação no README.

## Alternativas consideradas

- **Append simples + `DISTINCT` na leitura**: descartada — empurra o
  custo de dedup para toda query de leitura do mart (inclusive as do BI),
  em vez de resolver uma vez na escrita; também não resolve mudança de
  status de um pedido já existente (só dedup, não upsert).
- **Truncate-and-reload completo em toda execução**: considerada como
  alternativa mais simples, mas descartada para a camada raw/staging —
  quebraria o histórico de SCD2 do cliente (ADR-004) a cada rerun, que
  depende de comparar estado atual vs. novo. Mantida, porém, como
  estratégia aceitável especificamente para tabelas de dimensão pequena
  sem histórico (ex.: `stg_produtos`, que não tem SCD2).
- **Filtro incremental client-side por `updated_at` para reduzir volume
  de pull da API**: descartada por ora — como não há parâmetro de query
  no servidor para isso, "filtrar depois de baixar tudo" não economiza
  chamada de API nenhuma; só adicionaria complexidade sem ganho, dado que
  48k linhas por pull diário já é barato.

## Consequências

- Positivo: idempotência é uma propriedade verificável (teste automatizado
  de dupla execução), não uma promessa no README.
- Positivo: mudança de status de pedidos antigos é capturada
  automaticamente pelo merge por `updated_at`, sem lógica extra.
- Negativo: todo pull da API é sempre completo (96 páginas), mesmo que só
  1 pedido tenha mudado — aceitável dado o volume atual (48k linhas); se o
  volume real crescesse ordens de magnitude, essa decisão precisaria ser
  revisitada (documentado como limitação conhecida, não escondida).
