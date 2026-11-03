# Empório da Música — Agente de Atendimento

Protótipo de agente de atendimento por mensagem de texto para a Empório da Música, loja fictícia de instrumentos musicais em Campo Grande/MS. Desafio técnico AI Engineer — Artefact.

O agente assume a persona **Léo**, consulta dados vivos (catálogo, preços, estoque, pedidos) por ferramentas, consulta as políticas da loja por busca no manual em PDF, calcula em código o que não deve ser deixado ao LLM (parcelas, PIX, prazos de devolução) e recusa com gentileza o que foge do escopo.

> **Status:** o código, os testes e a suíte de avaliação estão prontos. **Ainda não rodei o agente contra um LLM real**, por falta de chave de API no ambiente de desenvolvimento. Por isso a seção [Exemplos de interação](#exemplos-de-interação) está pendente, e nenhum resultado de avaliação com modelo é afirmado aqui.

## Sumário

1. [Como rodar](#como-rodar)
2. [Visão geral da solução](#visão-geral-da-solução)
3. [Decisões técnicas e justificativas](#decisões-técnicas-e-justificativas)
4. [Suposições sobre dados e políticas](#suposições-sobre-dados-e-políticas)
5. [Pontos de Decisão Para Negócio](#pontos-de-decisão-para-negócio)
6. [Testes e avaliação](#testes-e-avaliação)
7. [Limitações conhecidas e próximos passos](#limitações-conhecidas-e-próximos-passos)
8. [Uso de assistentes de código](#uso-de-assistentes-de-código)
9. [Exemplos de interação](#exemplos-de-interação)

## Como rodar

Requisitos: Python 3.11 ou superior e uma chave de API da **Anthropic** ou da **OpenAI** (só para conversar com o agente; os testes não precisam de chave).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
pip install -e .                # instala o pacote `emporio`
cp .env.example .env            # preencha ANTHROPIC_API_KEY ou OPENAI_API_KEY
```

| Comando | O que faz |
|---|---|
| `python -m emporio check` | Verifica os dados, o índice de políticas e a conexão com o LLM |
| `python -m emporio chat` | Abre a conversa no terminal |
| `python -m emporio chat --debug` | Idem, mostrando as ferramentas chamadas e seus resultados |
| `python -m emporio chat --session cliente1` | Retoma (ou cria) uma sessão com histórico salvo |
| `python -m evals.run_evals` | Avaliação com o LLM real (22 casos); `-k texto` filtra por id |
| `python -m pytest` | Testes automatizados, sem rede |

Comandos dentro da conversa: `novo` reinicia, `sessoes` lista as salvas, `sair` encerra.

Variáveis em `.env`:

| Variável | Descrição |
|---|---|
| `EMPORIO_PROVIDER` | `anthropic` ou `openai`. Vazio = usa o que tiver chave (Anthropic primeiro, se as duas existirem) |
| `ANTHROPIC_API_KEY` | Chave da Anthropic |
| `OPENAI_API_KEY` | Chave da OpenAI |
| `OPENAI_BASE_URL` | Opcional. Aponta o provedor `openai` para uma API compatível (Gemini, Groq, OpenRouter, Ollama etc.); defina também `EMPORIO_MODEL` |
| `EMPORIO_MODEL` | Modelo. Vazio = padrão do provedor (`claude-haiku-5-5` ou `gpt-4o-mini`) |
| `EMPORIO_TODAY` | Data de referência `AAAA-MM-DD` (vazio = hoje). Afeta os prazos de devolução. |

Exemplo com a OpenAI:

```bash
EMPORIO_PROVIDER=openai OPENAI_API_KEY=sk-... python -m emporio chat --debug
```

**Sobre a data:** os pedidos da base são de 2025 e 2026. Com a data real, quase todos estão fora dos prazos de devolução. Para ver uma devolução dentro da janela, use por exemplo `EMPORIO_TODAY=2026-02-20` com o pedido 7.

## Visão geral da solução

```
cliente ─► Agent (loop de function calling, máx. 6 passos)
              │  system prompt: persona + regras + data/hora + loja aberta?
              ▼
        ┌───────────────────────── ferramentas ──────────────────────────┐
        │ search_products / get_product      CSVs de produtos + promoções │
        │ get_order_status                   pedidos + clientes (LGPD)    │
        │ check_return_eligibility           pedido + prazos do manual    │
        │ calculate_installments             regras de pagamento          │
        │ get_store_info                     endereço, horários, aberta?  │
        │ search_policies                    BM25 sobre o manual em PDF   │
        └─────────────────────────────────────────────────────────────────┘
```

Código em `src/emporio/`:

| Arquivo | Responsabilidade |
|---|---|
| `agent.py` | Loop de function calling, schemas das ferramentas, execução defensiva, janela de contexto |
| `prompts.py` | Persona, regras e contexto dinâmico |
| `tools.py` | Catálogo, pedidos, loja e pagamento |
| `returns.py` | Elegibilidade de troca e devolução |
| `policies.py` | Extração do PDF, divisão por seção e busca BM25 |
| `pricing.py` | Preço promocional, PIX e parcelamento |
| `data.py` | Carga e tratamento dos CSVs |
| `sessions.py` | Histórico de conversa em JSON |
| `llm.py` | Provedores (Anthropic e OpenAI) e adaptador de formato |
| `config.py`, `text.py` | Configuração e normalização de texto |

## Decisões técnicas e justificativas

### Abordagem: agente híbrido com function calling

O enunciado pede que o agente saiba quando consultar dados e quando consultar políticas. São dois tipos de informação diferentes, então usei duas estratégias:

- **Dados estruturados** (preço, estoque, pedido): ferramentas tipadas com filtros, sem RAG e sem text-to-SQL. O manual exige que preço, estoque e prazo nunca sejam informados sem consultar o sistema, o que pede exatidão. Com 65 produtos e 20 pedidos, ferramentas tipadas são mais seguras (não existe SQL gerado por LLM para dar errado), mais fáceis de testar e dispensam um banco.
- **Texto de políticas**: busca por trechos do manual.
- **Contas em código**: parcelas, desconto de PIX, prazos de devolução e "a loja está aberta agora?" são determinísticos. Deixar o LLM fazer contas de data e de dinheiro é a fonte mais provável de erro numa loja; o modelo só comunica o resultado.

O loop de function calling é escrito à mão sobre o SDK da Anthropic ([agent.py](src/emporio/agent.py)), sem LangChain ou similar. O fluxo é pequeno, e assim cada passo fica visível, depurável e testável com um cliente falso. A desvantagem é reimplementar o que um framework já traz (retries, tracing).

### Modelo e provedor

Dois provedores suportados, escolhidos por `EMPORIO_PROVIDER`: **Anthropic** (padrão, `claude-haiku-5-5`) e **OpenAI** (padrão `gpt-4o-mini`). `OPENAI_BASE_URL` permite usar APIs compatíveis com o formato da OpenAI. O padrão da Anthropic: o agente depende principalmente de escolher a ferramenta certa e redigir respostas curtas em português, o que um modelo pequeno costuma fazer bem, com baixa latência e custo (importante para um canal de chat com meta de resposta em minutos). `EMPORIO_MODEL` (ou `--model` na avaliação) troca o modelo. **Não comparei os modelos ainda**; os padrões são hipóteses a confirmar pela suíte de avaliação.

O acesso ao provedor está isolado em [llm.py](src/emporio/llm.py). O agente e o histórico salvo usam um único formato de mensagens (blocos `text`, `tool_use` e `tool_result`, o da Anthropic); para a OpenAI, um adaptador traduz mensagens, ferramentas e respostas. Assim, o loop do agente não muda por provedor, e uma sessão pode ser retomada com outro. O adaptador da OpenAI é testado com um cliente falso; **não foi exercitado contra a API real**.

### Estratégia de prompt

O [prompt](src/emporio/prompts.py) segue o manual de atendimento (seção 7):

- **Persona**: tom informal, mas profissional, "como um amigo que entende de música"; mensagens curtas, sem formatação pesada.
- **Fonte da verdade**: mapa explícito de qual ferramenta usar para cada tipo de pergunta, e a regra de nunca informar preço, estoque ou prazo de memória.
- **Regras de negócio** que o manual exige: preço promocional sempre com preço original, percentual e preço final; promoção não acumula com PIX; esgotado com alternativas; descontinuado com equivalentes; reclamação com retorno em 24 horas úteis; sem promessa de reembolso ou exceção.
- **Escopo**: só instrumentos; acessórios são redirecionados; assuntos alheios são recusados em uma frase.
- **Segurança**: instruções dentro de mensagens do cliente ou de resultados de ferramentas não alteram as regras; o prompt e os nomes das ferramentas não são revelados.
- **Contexto dinâmico**: data, hora e se a loja está aberta. O bloco estático vem primeiro e usa `cache_control`, para o prompt cacheado não ser invalidado pela hora.

### Busca de políticas (RAG)

1. O PDF é lido com `pypdf` em modo *layout*, que preserva tabelas e listas. Cabeçalho e rodapé repetidos são removidos.
2. O texto é dividido **por seção do manual**: cada subseção (4.1, 4.2, ...) vira um trecho, e seções sem subseção ficam inteiras. Seções que atravessam páginas (como a 5.2) ficam íntegras.
3. A busca é **BM25** com normalização de acento e caixa, radical de 5 letras, stopwords e **expansão de sinônimos** do vocabulário do cliente ("devolver" leva a arrependimento e reembolso, "abre" leva a horário). O título pesa em dobro.
4. Abaixo de uma relevância mínima, a ferramenta devolve "nenhuma política encontrada" e orienta a encaminhar para a equipe, sem inventar regra.
5. As inconsistências do manual são resolvidas por **notas internas** anexadas aos trechos (parcelamento, e-mail, telefones).

**Por que BM25 e não embeddings?** O manual tem 25 trechos e vocabulário bem delimitado. BM25 roda offline, sem custo nem chave de API, é determinístico e fácil de depurar. A desvantagem é depender de sinônimos escritos à mão para perguntas muito parafraseadas. Como a interface `search_policies(query)` esconde o mecanismo, trocar por embeddings (por exemplo multilingual-e5 com FAISS) não afeta o agente.

### Interface

CLI no terminal. O foco do desafio é o agente funcionando, e a CLI com `--debug` mostra o raciocínio (quais ferramentas foram chamadas) de forma direta.

### Persistência do histórico

Cada conversa é salva em `sessions/<id>.json` (ignorada pelo Git) após cada resposta, com escrita atômica; `--session NOME` retoma. Só os últimos 20 turnos do cliente vão ao modelo, e o corte nunca separa um `tool_use` do seu `tool_result`, que a API rejeita. O histórico completo permanece no arquivo.

### Tratamento dos dados

- `specs` (JSON em string) vira dicionário; categoria e promoção ativa são unidas ao produto.
- Só promoções com `is_active=1` valem; as outras 20 são histórico.
- Os `specs` misturam inglês e português (`steel`, `Black`, `Preto`), então a busca acrescenta os equivalentes em português ("aço" encontra `steel`).
- Nomes de produto são comparados sem acento, caixa e pontuação: "takamine gd 20" encontra "Takamine GD20".
- Esgotado, descontinuado e "em breve" nunca são oferecidos como disponíveis.

### Segurança e privacidade (LGPD)

- Pedidos só são exibidos mediante o número do pedido mais **e-mail ou telefone do titular**. Pedido inexistente e verificação falha dão a mesma resposta, para não revelar quais números existem.
- As ferramentas só aceitam os argumentos do schema, então o modelo não consegue injetar parâmetros internos. Exceções viram erro recuperável, e uma falha de API não deixa o histórico quebrado.

### Devolução e troca (`check_return_eligibility`)

Cruza o pedido com os prazos do manual: arrependimento em 7 dias corridos do recebimento (4.1), preferência em 7 dias (4.3), defeito em 30 dias da compra (4.2) e garantia legal de 90 dias do recebimento (8.1). Trata também pedidos cancelados, em trânsito e ainda não enviados, e lista as condições que o agente deve confirmar com o cliente (embalagem, sem uso, item não personalizado).

## Suposições sobre dados e políticas

- **Promoção e PIX** não acumulam (manual 6.2). Produto em promoção não recebe os 5%.
- **Parcelamento:** valem as faixas da seção 3.1 (até 3x: mínimo R$50; 4 a 6x: R$80; 7 a 12x: R$100), em vez do "mínimo R$100" genérico da tabela da seção 3, por serem mais específicas.
- **Contato:** (67) 3341-4444 é o telefone da loja e (67) 3321-4500 é o WhatsApp. O e-mail correto é `contato@emporiodamusica.com.br`, sem o acento que aparece num trecho do manual.
- **Filtros de preço** usam o preço praticado (com promoção, sem desconto de PIX).
- **Data de recebimento:** os dados não têm a data real de entrega; para pedidos entregues usamos a previsão (`estimated_delivery`).
- **Compra online:** todos os pedidos são tratados como online. Compra presencial não tem o direito de arrependimento de 7 dias.
- **Condições não verificáveis** (uso, embalagem, personalização, "venda final") não estão nos dados; o agente as confirma com o cliente.
- **Cancelar pedido ainda não enviado** não está no manual; o caso é encaminhado à equipe.
- **Feriados** não são modelados em "loja aberta agora".

## Pontos de Decisão Para Negócio

Pontos que dependem de uma definição da loja. Adotamos uma suposição provisória em cada um, para o agente funcionar até haver resposta.

| # | Ponto | Suposição atual | Quem decide |
|---|---|---|---|
| 1 | **Telefone da loja:** o manual traz (67) 3341-4444 (cabeçalho e dados da empresa) e (67) 3321-4500 (seção WhatsApp). | O primeiro é o telefone da loja e o segundo é o WhatsApp. | Loja |
| 2 | **Categorias sem produtos:** existem as categorias de sopro (madeiras e metais) e cordas orquestrais, mas o CSV não tem produtos nelas. O manual diz que o catálogo tem mais de 300 instrumentos, e o CSV tem 65. | O agente trabalha só com o que está no CSV. Se perguntarem por sopro ou cordas, informa que não há itens no momento. | Loja |
| 3 | **Pedido 3 com produto "em breve":** o pedido 3, entregue em 2025, inclui o produto 130, que está como `coming_soon`. | Tratamos como inconsistência dos dados. O pedido é exibido como está, e o produto não é oferecido para compra. | Loja / dados |
| 4 | **E-mail repetido entre clientes:** há um e-mail duplicado em `customers.csv`, o que pode afetar a verificação de identidade por e-mail. | A verificação usa e-mail ou telefone, e o telefone não tem repetição. | Loja / dados |

## Testes e avaliação

**Testes automatizados** (`python -m pytest`, 83 testes, sem rede):

- ferramentas de catálogo, pedidos, loja e pagamento;
- recuperação de políticas: 21 perguntas com a seção esperada entre os 3 primeiros resultados;
- elegibilidade de devolução, incluindo o último dia da janela e o dia seguinte;
- o adaptador da OpenAI (tradução de mensagens, ferramentas e respostas) e a escolha do provedor;
- o laço da CLI (comandos `novo`, `sessoes`, `sair` e modo `--debug`);
- o loop do agente, com um cliente LLM falso: execução de ferramenta, limite de passos, erro de API sem corromper o histórico, janela de contexto e sessões;
- o avaliador e a consistência dos casos de avaliação.

**Avaliação com o modelo real** (`python -m evals.run_evals`): 22 casos em conversas novas, gerando `evals/last_run.md`. As checagens são determinísticas: quais ferramentas foram chamadas (ou proibidas) e padrões esperados ou proibidos na resposta. Os valores esperados (preços, parcelas, e-mails) são calculados a partir dos CSVs, não digitados. Os casos cobrem catálogo, preço, PIX e parcelas, promoção ativa e vencida, estoque, descontinuado, acessório, assunto fora do escopo, prompt injection, frete, reclamação, devolução (sem dados, no prazo e fora do prazo), pedido de outro cliente e contexto entre turnos.

**O que isso ainda não prova:** os testes com cliente falso verificam a lógica do agente, não o comportamento do modelo. A suíte de avaliação foi escrita sem ter sido executada contra um LLM, então seus regex podem precisar de ajuste. Regex também não avalia tom nem naturalidade.

## Limitações conhecidas e próximos passos

**Limitações**

- **Sem validação com LLM real** (nem Anthropic, nem OpenAI) até aqui: escolha de ferramentas, tom e robustez a prompt injection são hipóteses.
- **Verificação de identidade fraca:** conhecer o e-mail ou o telefone do titular basta. Em produção, o canal de WhatsApp já identifica o número de origem, o que permitiria uma verificação melhor.
- **Retrieval por palavras-chave:** perguntas muito parafraseadas dependem da lista de sinônimos.
- **Dados limitados:** sem data real de entrega, sem distinção entre compra online e presencial, sem produtos de sopro e cordas, sem feriados.
- **Sem encaminhamento humano real:** o agente diz que a equipe retorna em 24 horas úteis, mas não registra a reclamação em lugar nenhum.
- **Sem finalização de compra:** o agente informa preço e condições, mas não vende nem recebe pagamento no chat.
- **Prompt injection** é mitigada por instruções e por restrição de argumentos, não eliminada.

**Com mais tempo**

1. Rodar a avaliação com Haiku e Sonnet, comparar custo, latência e acerto, e ajustar prompt e ferramentas.
2. Juiz LLM para tom e naturalidade, além dos regex.
3. Embeddings com reranking na busca de políticas, mantendo o BM25 como fallback.
4. Registro de reclamações e passagem para atendente humano (ticket ou fila).
5. Integração com WhatsApp (webhook) e verificação pelo número de origem.
6. Streaming de respostas, observabilidade (traces das chamadas de ferramenta) e cache de consultas.
7. Resolver os pontos de decisão de negócio acima com a loja.

## Uso de assistentes de código

Usei o **Claude Code** (extensão do VS Code, modelo Claude Sonnet 5.5) como par de programação ao longo de todo o projeto. O fluxo foi:

1. **Leitura e planejamento:** pedi ao assistente que lesse o enunciado, o manual em PDF e os CSVs e propusesse uma abordagem e um plano em sprints. Daí saíram a decisão pelo agente híbrido com ferramentas tipadas e a lista de inconsistências do manual (dois telefones, regras de parcelamento conflitantes, produto "em breve" em pedido entregue).
2. **Implementação por sprint:** o assistente escreveu o código e os testes de cada sprint (dados e ferramentas, busca de políticas, agente, persistência e avaliação), e eu aprovei cada etapa antes da seguinte. Os commits do histórico têm o assistente como coautor.
3. **Testes como rede de segurança:** cada módulo veio com testes escritos junto, o que pegou erros reais durante o desenvolvimento (por exemplo, valores de `specs` em inglês quebrando a busca por "aço", e um teste do agente que comparava uma lista mutada depois da chamada).
4. **Limite do que foi verificado:** o assistente não tinha chave de API no ambiente, então nada do que depende do comportamento do modelo foi exercitado. Isso está declarado acima.

## Exemplos de interação

**Pendente.** As conversas de exemplo (entre 3 e 5, incluindo ao menos uma não trivial de devolução ou consulta em tempo real) precisam ser geradas com o modelo real, e eu não vou escrevê-las à mão para não apresentar como resultado do agente algo que ele não produziu. Depois de preencher a chave em `.env`, o plano é salvá-las em `examples/` com `python -m emporio chat --debug`, cobrindo:

1. consulta de catálogo com filtro de preço ("violões disponíveis até R$1000");
2. informações da loja (endereço e horário);
3. preço de um produto ("Quanto custa o Takamine GD20?"), incluindo PIX e parcelas;
4. **não trivial:** devolução com `EMPORIO_TODAY=2026-02-20` e o pedido 7;
5. pedido fora de escopo ou acessório.
