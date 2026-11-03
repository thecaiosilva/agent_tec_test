# Empório da Música — Agente de Atendimento

Protótipo de agente de atendimento (chat de texto) para a Empório da Música, loja fictícia de instrumentos musicais em Campo Grande/MS. Desafio técnico AI Engineer — Artefact.

> **Status:** em desenvolvimento (Sprints 0–4 concluídas: fundação, dados, ferramentas, busca de políticas, agente, persistência e suíte de avaliação. Falta rodar a avaliação com um LLM real, ajustar prompt/ferramentas com o resultado e gerar os exemplos de conversa (Sprint 5)).

## Como rodar

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
pip install -e .                # instala o pacote `emporio`
cp .env.example .env            # preencha ANTHROPIC_API_KEY
python -m emporio check         # verifica dados e conexão com o LLM
python -m emporio chat --debug  # conversa com o agente (--debug mostra as ferramentas chamadas)
python -m emporio chat --session cliente1   # retoma (ou cria) uma sessão com histórico salvo
python -m evals.run_evals       # avaliação com o LLM real (20+ casos)
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
| `check_return_eligibility` | pedido + prazos do manual (seções 4 e 8) | ✅ |
| `search_policies` | RAG do PDF (BM25 por seção) | ✅ |

### Agente e prompt

- **Loop de function calling** escrito à mão sobre o SDK da Anthropic ([agent.py](src/emporio/agent.py)), limitado a 6 passos por mensagem. Sem framework: o fluxo é pequeno e assim fica fácil de depurar e testar.
- **Persona "Léo"** e regras no [prompts.py](src/emporio/prompts.py): tom informal-profissional do manual (7.1), "nunca informar preço, estoque ou prazo sem consultar", escopo só de instrumentos (acessórios são redirecionados), recusa gentil de assuntos alheios, reclamação com retorno em 24h úteis, e instruções vindas do cliente ou de resultados de ferramentas não alteram as regras.
- **Contexto dinâmico:** data, hora e se a loja está aberta entram no prompt; a parte estática é cacheável (`cache_control`).
- **Guardrails em código:** a ferramenta só aceita os argumentos do schema (o modelo não consegue injetar `store` ou `today`); exceções viram erro recuperável; erro de API não deixa histórico quebrado.
- **Contas em código, não no LLM:** parcelas, PIX, prazos de devolução e horário de funcionamento.
- **Os testes do agente usam um cliente LLM falso** (loop, limite de passos, erros). O comportamento real do modelo (escolha de ferramentas, tom) ainda precisa ser validado com chave de API; isso entra na avaliação da Sprint 4.

### Histórico e sessões

Cada conversa é salva em `sessions/<id>.json` (ignorada pelo Git) após cada resposta, com escrita atômica. `--session NOME` retoma a conversa; sem o argumento, cria uma sessão nova com data e hora. Só os últimos 20 turnos do cliente vão ao modelo (`window`), e o corte nunca separa um `tool_use` do seu `tool_result`, que a API rejeita. O histórico completo continua no arquivo.

### Avaliação

`python -m evals.run_evals` roda 22 casos em conversas novas contra o modelo real e gera `evals/last_run.md`. As checagens são determinísticas, sem LLM-juiz: quais ferramentas foram chamadas (ou proibidas) e padrões esperados ou proibidos na resposta, como o preço calculado ou o nome de um produto esgotado. Os valores esperados são calculados a partir dos CSVs, não digitados. Os casos cobrem catálogo, preço, PIX e parcelas, promoção ativa e vencida, estoque, descontinuado, acessório, assunto fora do escopo, prompt injection, frete, reclamação, devolução (sem dados, no prazo e fora do prazo), pedido de outro cliente e contexto entre turnos. Limite: checar texto por regex não avalia tom nem naturalidade, que exigem leitura humana ou um juiz LLM.

### Devolução e troca (`check_return_eligibility`)

Cruza o pedido com os prazos do manual: arrependimento 7 dias corridos do recebimento (4.1), preferência 7 dias (4.3), defeito 30 dias da compra (4.2) e garantia legal de 90 dias do recebimento (8.1). Trata também pedidos cancelados, em trânsito e ainda não enviados. Exige a mesma verificação de titular do status do pedido. Suposições:

- Os dados não têm a data real de entrega; usamos `estimated_delivery` como data de recebimento.
- Todos os pedidos são tratados como compra online. Compra presencial não tem o direito de arrependimento de 7 dias.
- Uso, embalagem, personalização e "venda final" não estão nos dados; a ferramenta lista essas condições para o agente confirmar com o cliente.
- Cancelar um pedido ainda não enviado não está no manual; o caso é encaminhado à equipe.
- A data de hoje vem de `EMPORIO_TODAY` (ou do relógio). Os pedidos da base são de 2025–2026, então para demonstrar prazos "dentro da janela" use, por exemplo, `EMPORIO_TODAY=2026-02-20`.

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
