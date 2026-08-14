# Descoberta — Etapa 1

Objetivo deste documento: registrar o que foi **observado de fato** em cada
uma das 3 fontes antes de qualquer decisão de design. Toda decisão registrada
nas ADRs (`docs/adr/`) referencia um achado concreto listado aqui — não há
decisão de arquitetura tomada "no escuro".

Ambiente usado para a exploração: Python 3.11, `sqlite3` (stdlib) e `curl`,
sem gravar nada no BigQuery/GCS nesta etapa (é só leitura/reconhecimento).

---

## 1. Fonte 1 — API de Vendas

**Request de reconhecimento:**

```
GET /api/pedidos?page=1&page_size=5
Authorization: Bearer vena-teste-2026
```

**Resposta:**

```json
{
  "data": [ { "cliente_id": 2254, "data_pedido": "2025-04-25T00:54:38",
              "pedido_id": 1, "produto_id": 251, "quantidade": 2,
              "status": "pago", "updated_at": "2025-04-25T00:54:38",
              "valor_unitario": 151.3 }, ... ],
  "has_next": true, "page": 1, "page_size": 5,
  "total_pages": 9600, "total_records": 48000
}
```

**Achados:**

- `total_records = 48.000`. Com `page_size=500` (máximo permitido pelo
  enunciado) isso dá **96 páginas** por carga completa — volume pequeno,
  cabe tranquilamente em uma execução diária.
- Campos: `cliente_id, data_pedido, pedido_id, produto_id, quantidade,
  status, updated_at, valor_unitario`.
- `status` observado com pelo menos 4 valores: `pago`, `pendente`,
  `cancelado`, `reembolsado`.
- **Padrão em `updated_at`**: quando `status = pago`, `updated_at` costuma
  ser igual a `data_pedido`. Quando `status` é `cancelado` ou `reembolsado`,
  `updated_at` frequentemente vem 1 a 3 dias *depois* de `data_pedido`
  (ex.: `data_pedido=2025-12-15T10:07:01`, pedido `reembolsado` — sinal de
  que o registro é atualizado em uma transição de estado, não é imutável).
  → isso importa para a estratégia de idempotência/upsert (ADR-007).
- **Inconsistência de tipo confirmada em produção**: em uma amostra de ~4.000
  registros (páginas 1–40), encontrei `valor_unitario` como **string**
  em pelo menos 1 registro: `"593.57 BRL"` em vez de `593.57` (numérico).
  Confirma o aviso do enunciado ("campos em formatos inconsistentes") —
  parsing precisa ser defensivo, não assumir tipo fixo por campo.
- **Rate limit confirmado experimentalmente**: 15 requisições sequenciais
  (uma por vez) → 100% `200`. 25 requisições **disparadas em paralelo**
  → as primeiras ~14 voltam `200`, o restante volta `429` em cascata.
  Conclusão prática: a API tolera **baixa concorrência** (na faixa de
  10-14 simultâneas) antes de limitar; não observei header `Retry-After`
  nas respostas 429 testadas. → informa a policy de concorrência/backoff
  (ADR-006).
- Não há parâmetro de filtro incremental na query string (só `page` e
  `page_size`) — não é possível pedir "só o que mudou desde X" no servidor.
  → informa a estratégia de "full pull diário + merge por chave" (ADR-006
  e ADR-007), já que o volume (48k linhas) torna isso barato.

---

## 2. Fonte 2 — Scraping de Concorrentes

**Request de reconhecimento:** 3 chamadas consecutivas ao mesmo endpoint,
sem nenhum parâmetro, intervalo de poucos segundos entre elas.

**Achado central: a estrutura do HTML muda a cada request, e não em apenas
2 variações — observei 3 layouts distintos em 3 chamadas seguidas:**

**Layout A — tabela clássica com classes CSS:**
```html
<table id="tabela-precos">
  <tbody><tr class="produto-row">
    <td class="nome">Tênis Runner Pro</td>
    <td class="categoria">Calçados</td>
    <td class="preco">R$ 340.04</td>
    <td class="concorrente">ConcorrenteA</td>
    <td class="estoque">Indisponível</td>
  </tr>...
```

**Layout B — grid de cards com `data-*` attributes, sem tabela:**
```html
<div id="price-grid">
  <div class="price-card" data-product="Tênis Runner Pro" data-store="ConcorrenteA">
    <span class="pc-cat">Calçados</span>
    <span class="pc-price">324.63</span>
    <span class="pc-stock">Últimas unidades</span>
  </div>...
```

**Layout C — tabela "comparativo", com produto+categoria concatenados num
único campo de texto:**
```html
<table class="comparativo">
  <tbody><tr>
    <td class="col-loja">ConcorrenteA</td>
    <td class="col-item">Tênis Runner Pro (Calçados)</td>
    <td class="col-valor">338.50</td>
    <td class="col-disp">Indisponível</td>
  </tr>...
```

**Achados adicionais:**

- O **preço** vem formatado de forma diferente em cada layout: com prefixo
  `"R$ "` (Layout A) ou puro `"324.63"` (Layouts B e C) — parsing de preço
  precisa normalizar os dois casos.
- No Layout C, **produto e categoria vêm concatenados** em um único campo
  (`"Tênis Runner Pro (Calçados)"`) — exige separar por regex, e categoria
  não é 100% garantida de estar presente/bem formada.
- Campo de disponibilidade tem valores textuais livres observados:
  `"Indisponível"`, `"Últimas unidades"`, `"Em estoque"` — não é booleano.
- Não há paginação nem parâmetros — é uma página única por request.
- Como a estrutura muda **por request, não por dia**, um parser fixo
  quebraria em ~2 de cada 3 execuções reais. → informa diretamente a
  necessidade de um parser com múltiplas estratégias, não um seletor
  único (ADR-006, detalhado tecnicamente na Etapa 3).

---

## 3. Fonte 3 — Banco Transacional (SQLite)

**Schema real** (via `sqlite_master`, sem PK/FK declaradas em nenhuma
tabela — confirma que a integridade referencial não é garantida pelo
schema, é responsabilidade do pipeline):

```sql
CREATE TABLE clientes (
    cliente_id INTEGER, nome TEXT, cpf TEXT, email TEXT,
    cidade TEXT, estado TEXT, data_cadastro TEXT, segmento TEXT
);

CREATE TABLE produtos (
    produto_id INTEGER, nome_produto TEXT, categoria TEXT,
    preco_tabela TEXT, ativo TEXT
);

CREATE TABLE itens_pedido (
    item_id INTEGER, pedido_id INTEGER, cliente_id INTEGER,
    produto_id INTEGER, data_item TEXT, quantidade INTEGER,
    valor_unitario REAL
);
-- único índice existente:
CREATE INDEX idx_itens_pedido_id ON itens_pedido(pedido_id);
```

### 3.1 `clientes` — 6.180 linhas

| Métrica | Valor |
|---|---|
| Total de linhas | 6.180 |
| `cliente_id` distintos | 6.168 (**12 ids duplicados**) |
| `cpf` distintos | 5.995 (**185 CPFs duplicados** — mais duplicidade que por ID) |
| combinação `nome+cpf` distinta | 6.180 (nenhuma linha 100% idêntica a outra) |
| `email` nulo | 378 |
| `estado` nulo | 775 |
| `segmento` nulo | 1.533 |
| `cliente_id` mín/máx | 1 / 7.137 |

Exemplo real de CPF duplicado: `703.164.259-07` aparece em **3** linhas
diferentes (com `cliente_id` diferentes). `estado` só assume valores de
uma lista fechada de UFs (`MG, RJ, SP, RS, PR, SC, BA`) mais `NULL` — não
há valor inválido/lixo, só ausência. Mesmo padrão em `segmento`
(`Varejo, Atacado, Marketplace, NULL`).

**Achado-chave**: como há *mais* duplicidade por CPF (185) do que por
`cliente_id` (12), `cliente_id` **não é uma chave de identidade
confiável** para saber se duas linhas são a mesma pessoa — CPF é o
identificador real de negócio aqui. → ADR-004.

Também há mojibake visível em texto livre (ex.: `"Srta. Alexia Ara�jo"`,
cidade `"Pinto dos Dourados"` ok mas nomes com acento quebrado) — indício
de exportação com encoding incorreto (provavelmente Latin-1 lido como
outra codificação). Tratado como limpeza de staging, não como erro fatal.

### 3.2 `produtos` — 800 linhas

| Métrica | Valor |
|---|---|
| Total de linhas | 800 |
| `produto_id` distintos | 800 (sem duplicidade de chave) |
| `produto_id` mín/máx | 1 / 800 |
| `preco_tabela` com prefixo `"R$ "` | 42 linhas |
| `preco_tabela` nulo | 0 |
| `ativo` nulo | 161 |
| `ativo` valores distintos | `'0'`, `'1'`, `'S'`, `'N'`, `NULL` |

`preco_tabela` é `TEXT`, não `NUMERIC`, e mistura formato puro
(`"765.78"`) com formato com prefixo de moeda (`"R$ 533.46"`) — precisa de
`CAST` defensivo na staging. `ativo` mistura duas convenções booleanas
diferentes (`0/1` e `S/N`) mais nulo — não pode ser lido como booleano
puro sem mapeamento explícito.

### 3.3 `itens_pedido` — 5.000.000 linhas

| Métrica | Valor |
|---|---|
| Total de linhas | 5.000.000 |
| `item_id` distintos | 5.000.000 (chave íntegra, sem duplicidade) |
| `cliente_id` observado | mín 1 / máx **12.180** |
| `produto_id` observado | mín 1 / máx **1.300** |
| linhas com `cliente_id` sem correspondência em `clientes` | 75.201 (1,50%) |
| linhas com `produto_id` sem correspondência em `produtos` | 74.639 (1,49%) |
| `quantidade` nula | 50.169 (1,00%) |
| `valor_unitario` nulo | 0 |
| `quantidade <= 0` ou `valor_unitario <= 0` | 0 |
| `pedido_id` distintos | 1.748.447 |
| Range de `data_item` | `2024-01-01` a `2025-07-29` |

**Achado crítico para a arquitetura**: `itens_pedido.cliente_id` chega a
12.180 e `itens_pedido.produto_id` chega a 1.300 — **ambos maiores que o
maior ID existente em `clientes` (7.137) e `produtos` (800)**. Isso não é
só "FK quebrada pontual": o espaço de IDs referenciado por `itens_pedido`
é estruturalmente maior do que o universo de `clientes`/`produtos`
disponível no mesmo banco. Some-se a isso que o **range de datas de
`itens_pedido` (jan/2024–jul/2025) não se sobrepõe integralmente com o
range de `data_pedido` observado na API de vendas (que já mostrou pedidos
em 2025 e até 2026)** — são dois universos de pedidos gerados
independentemente para o teste, não a mesma tabela de fatos vista por
duas fontes. → ADR-003, decisão com maior impacto no design do mart.

Sem PK/FK declaradas no schema (confirmado via `sqlite_master`), a decisão
de "manter e sinalizar" vs. "descartar" linhas órfãs é 100% responsabilidade
do pipeline — não existe constraint no banco que já filtre isso. → ADR-005.

---

## 4. Resumo dos achados → decisões (rastreabilidade)

| Achado | ADR que trata |
|---|---|
| Stack a escolher para orquestração + transformação em camadas | ADR-001 |
| Necessidade de landing intermediário antes do BigQuery, volume de 5M linhas | ADR-002 |
| `itens_pedido` (SQLite) e API de vendas não são a mesma tabela de fatos | ADR-003 |
| CPF duplica mais que `cliente_id` → identidade real do cliente | ADR-004 |
| ~1,5% de linhas de `itens_pedido` com FK quebrada, sem constraint no schema | ADR-005 |
| Rate limit real em ~14 requisições paralelas; schema drift real do scraping (3 layouts) | ADR-006 |
| API sem filtro incremental; `updated_at` indica mutação de status | ADR-007 |
