# ADR-002 — Camadas raw/staging/mart, landing via GCS e carga em lote (não streaming)

**Status:** Aceita — Etapa 1

## Contexto

O enunciado pede modelagem "raw → staging → mart" no BigQuery e fornece um
bucket GCS (`gs://vena-teste-candidato-ae`) explicitamente para "landing e
arquivos intermediários do pipeline". `itens_pedido` tem 5.000.000 de linhas
e o enunciado avisa que **não deve ser carregado inteiro em memória**
(`README_CANDIDATO.md`, item 3) — essa restrição também empurra a decisão
de como os dados chegam ao BigQuery.

## Decisão

- Toda fonte, antes de chegar ao BigQuery, é materializada como arquivo
  em `gs://vena-teste-candidato-ae/landing/<fonte>/dt=YYYY-MM-DD/...`
  (JSON para API, HTML bruto para scraping, Parquet particionado em chunks
  para a extração do SQLite).
- A carga para as tabelas `raw` do BigQuery é feita via **load job em
  lote** (`bq load` / `LoadJobConfig` do client BigQuery) a partir desses
  arquivos no GCS — nunca via streaming insert linha a linha.
- `itens_pedido` é extraído do SQLite com cursor em **chunks de 50.000
  linhas** (`fetchmany`), cada chunk gravado como um arquivo Parquet
  separado no GCS; a carga no BigQuery lê todos os arquivos do
  particionamento do dia em um único load job.

## Alternativas consideradas

- **Streaming insert (`insertAll`/`WriteApi`) direto no BigQuery**:
  descartada. Tem custo por linha, limites de quota, e não tem controle de
  dedup nativo — para uma carga batch diária de 5M linhas, é a ferramenta
  errada (streaming insert existe para casos de latência sub-segundo, que
  não é o requisito aqui: "dashboard **diário**").
- **Carregar `itens_pedido` inteiro em pandas e escrever direto no
  BigQuery via `pandas-gbq`**: descartada — é exatamente o padrão que o
  enunciado pede para evitar ("não carregue tudo em memória de uma vez").
- **Pular o GCS e ler o SQLite diretamente de dentro do BigQuery**: não é
  possível — BigQuery não lê arquivo SQLite nativamente; seria necessário
  de qualquer forma um passo de extração/conversão antes.

## Consequências

- Positivo: o passo de extração do SQLite (Etapa 2) fica simples de
  implementar corretamente desde o início — cursor sequencial, sem
  `OFFSET` gigante, sem pressão de memória, independentemente de o volume
  crescer no futuro.
- Positivo: arquivos no GCS servem como ponto de reprocessamento — se a
  camada `raw` do BigQuery precisar ser recriada, não é necessário voltar
  às fontes originais (a API pode não devolver os mesmos dados
  novamente).
- Positivo: caminho determinístico por data (`dt=YYYY-MM-DD`) facilita a
  idempotência (ADR-007) — reprocessar o mesmo dia sobrescreve o mesmo
  prefixo em vez de acumular arquivos infinitamente.
- Negativo: mais um salto (SQLite/API/HTML → GCS → BigQuery) em vez de
  carga direta — latência adicional de segundos, irrelevante para
  atualização diária.
