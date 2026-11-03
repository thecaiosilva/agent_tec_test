# Empório da Música — Agente de Atendimento

Protótipo de agente de atendimento (chat de texto) para a Empório da Música, loja fictícia de instrumentos musicais em Campo Grande/MS. Desafio técnico AI Engineer — Artefact.

> **Status:** em desenvolvimento (Sprints 0–2 concluídas: fundação, dados, ferramentas e busca de políticas).

## Como rodar

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env            # preencha ANTHROPIC_API_KEY
python -m emporio               # verifica dados e conexão com o LLM
python -m pytest                # testes (não precisam de API key)
```

Variáveis em `.env`:

| Variável | Descrição |
|---|---|
| `ANTHROPIC_API_KEY` | Chave da API do provedor |
| `EMPORIO_MODEL` | Modelo (padrão `claude-haiku-5-5`) |
| `EMPORIO_TODAY` | Data de referência `AAAA-MM-DD` (vazio = hoje). Afeta prazos de devolução. |

## Arquitetura (planejada)

Agente **híbrido com function calling**: o LLM decide entre ferramentas determinísticas (dados vivos dos CSVs) e busca em políticas (RAG sobre o manual em PDF).

| Ferramenta | Fonte | Status |
|---|---|---|
| `search_products`, `get_product` | `products.csv` + `promotions.csv` | ✅ |
| `get_order_status` (com verificação de identidade) | `orders.csv`, `customers.csv`, `order_items.csv` | ✅ |
| `calculate_installments` | regras do manual | ✅ |
| `get_store_info` | manual (seções 1–2) | ✅ |
| `search_policies` | RAG do PDF (BM25 por seção) | ✅ |

### Busca de políticas (RAG)

1. O PDF é lido com `pypdf` em modo *layout*, que preserva tabelas e listas. Cabeçalho e rodapé repetidos são removidos.
2. O texto é dividido **por seção do manual**: cada subseção (4.1, 4.2, ...) vira um trecho, e seções sem subseção ficam inteiras. Seções que atravessam páginas (ex.: 5.2) ficam íntegras. Cada trecho guarda número, título e seção-pai.
3. A busca é **BM25** com normalização (sem acento e caixa), radical de 5 letras, remoção de stopwords e **expansão de sinônimos** do vocabulário do cliente ("devolver" → arrependimento/reembolso, "abre" → horário). O título pesa em dobro.
4. Abaixo de uma relevância mínima, a ferramenta devolve "nenhuma política encontrada" e orienta a encaminhar para a equipe, sem inventar regra.
5. Inconsistências do manual são resolvidas com **notas internas** anexadas aos trechos (parcelamento, e-mail, telefones).

**Por que BM25 e não embeddings?** O manual tem cerca de 25 trechos e vocabulário bem delimitado. BM25 roda offline, sem custo nem chave de API, é determinístico e fácil de depurar. A desvantagem é depender de sinônimos manuais para perguntas muito parafraseadas. Como a interface `search_policies(query)` esconde o mecanismo, trocar por embeddings (ex.: multilingual-e5 + FAISS) não muda o agente. A qualidade é medida em `tests/test_policies.py` (21 perguntas com a seção esperada).

## Suposições sobre dados e políticas

- **Só promoções com `is_active=1` valem**; as demais são histórico. Promoção e PIX (5%) não acumulam (manual 6.2).
- **Parcelamento:** usamos as faixas da seção 3.1 (3x: mín. R$50; 4–6x: R$80; 7–12x: R$100) em vez do "mín. R$100" genérico da tabela da seção 3, por serem mais específicas.
- **Contato:** o manual traz dois telefones — (67) 3341-4444 (cabeçalho/dados da empresa) e (67) 3321-4500 (seção WhatsApp). Usamos o primeiro como telefone da loja e o segundo como WhatsApp.
- **Produtos:** `discontinued`, `coming_soon` e estoque 0 nunca são oferecidos como disponíveis. Filtros de preço usam o preço praticado (com promoção, sem PIX).
- **Pedidos:** só são exibidos mediante verificação (nº do pedido + e-mail **ou** telefone do cliente), por LGPD. Falha de verificação e pedido inexistente dão a mesma resposta.
- **Feriados** não são modelados no cálculo de "loja aberta agora".
- Existem categorias de sopro e cordas orquestrais, mas o CSV não tem produtos nelas.

## Pontos de Decisão Para Negócio

Pontos que dependem de uma definição da loja. Adotamos uma suposição provisória em cada um, para o agente funcionar até haver resposta.

| # | Ponto | Suposição atual | Quem decide |
|---|---|---|---|
| 1 | **Telefone da loja:** o manual traz (67) 3341-4444 (cabeçalho e dados da empresa) e (67) 3321-4500 (seção WhatsApp). | O primeiro é o telefone da loja e o segundo é o WhatsApp. | Loja |
| 2 | **Categorias sem produtos:** existem as categorias de sopro (madeiras e metais) e cordas orquestrais, mas o CSV não tem produtos nelas. O manual diz que o catálogo tem mais de 300 instrumentos, e o CSV tem 65. | O agente trabalha só com o que está no CSV. Se perguntarem por sopro ou cordas, informa que não há itens no momento. | Loja |
| 3 | **Pedido 3 com produto "em breve":** o pedido 3, entregue em 2025, inclui o produto 130, que está como `coming_soon`. | Tratamos como inconsistência dos dados. O pedido é exibido como está, e o produto não é oferecido para compra. | Loja / dados |
| 4 | **E-mail repetido entre clientes:** há um e-mail duplicado em `customers.csv`, o que pode afetar a verificação de identidade por e-mail. | A verificação usa e-mail ou telefone, e o telefone não tem repetição. | Loja / dados |
