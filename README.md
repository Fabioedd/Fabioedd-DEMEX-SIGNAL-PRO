# DEMEX SIGNAL PRO — Python / Bullex (PRACTICE)

Projeto Python para leitura de ativos/candles e execução automática de operações **somente em conta PRACTICE/DEMO**, usando a biblioteca não oficial [CassDs/bullexapi](https://github.com/CassDs/bullexapi). Não é uma API oficial confirmada da corretora; compatibilidade e autorização podem mudar.

## Estratégia e operação

- Estratégia ativa: **HARAMI + ENGOLFO (Tendência EMA 21/45)**, implementada em Python em `strategies/harami_engolfo_tendencia.py`.
- Regras preservadas do indicador Lua:
  - **CALL:** Harami de alta OU Engolfo de alta na vela analisada, com fechamento acima da EMA(21) e EMA(21) acima da EMA(45).
  - **PUT:** Harami de baixa OU Engolfo de baixa na vela analisada, com fechamento abaixo da EMA(21) e EMA(21) abaixo da EMA(45).
  - Os padrões usam somente os corpos dos dois candles, exatamente pelas comparações de abertura/fechamento do script original.
  - Não há cruzamento SMA/WMA, RSI, Bollinger ou outro filtro adicional nesta estratégia.
- O DEMEX recebe candles M1. O sinal é calculado sobre a vela fechada e só libera entrada na vela M1 seguinte, nos primeiros 5 segundos, após confirmar o relógio da corretora e o padrão novamente.
- Modalidade: opções da família binária. Para expiração M1/M5, a API da BullX classifica o contrato como Turbo; a seleção consulta o grupo de ativos correspondente à expiração. O DEMEX não faz fallback para Blitz ou Digital. Payout não é usado como critério de seleção.
- Timeframe configurado: M1 (candles de 60 segundos); expiração: 1 minuto, na vela imediatamente seguinte ao sinal. A entrada é permitida apenas nos primeiros 5 segundos dessa vela.
- Entrada inicial: R$ 5,00.
- Soros nível 1: após o primeiro WIN, a próxima entrada é base + lucro líquido; depois dessa operação o ciclo volta à base. LOSS/TIE reinicia a entrada.
- Resultado e P&L vêm do retorno da corretora; o terminal informa WIN/LOSS/TIE, valor da operação e acumulado.
- Seleção automática: a cada ciclo, o DEMEX identifica os ativos OTC binários disponíveis e executa novamente o backtest dos últimos 100 candles M1 fechados de cada ativo, usando exatamente HARAMI + ENGOLFO com EMA 21/45. São contabilizados WIN, LOSS e TIE; a assertividade é WIN / (WIN + LOSS), sem mínimo de operações e sem filtro de payout. Só são aprovados ativos com assertividade estritamente acima de 70%. O resultado completo substitui a lista anterior; apenas os aprovados entram na varredura de sinais e nas entradas. O histórico de aquecimento da EMA (60 candles) é buscado antes dos 100 candles avaliados. O DEMEX registra progresso, tempo decorrido e estimativa de tempo restante durante cada ciclo.

## Trava de segurança

O envio de ordens só passa se **ambas** as verificações confirmarem PRACTICE: `BULLEX_ACCOUNT_TYPE=PRACTICE` no ambiente e `get_balance_mode() == "PRACTICE"` na sessão conectada. Se qualquer verificação falhar, o robô interrompe sem enviar ordem. Não configure conta REAL.

## Instalação

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS/Termux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Preencha `.env` localmente e mantenha-o fora do GitHub:
```env
BULLEX_EMAIL=seu_email
BULLEX_PASSWORD=sua_senha
BULLEX_ACCOUNT_TYPE=PRACTICE
```

Inicie com `python main.py`. A execução automática está habilitada em `settings.json`, mas o robô só envia ordens binárias após conexão e confirmação da conta PRACTICE.


## Controle remoto pelo Telegram

O projeto inclui comandos privados para ligar e desligar o DEMEX pelo Telegram. Configure `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` no arquivo local `.env` (nunca publique o token). Inicie o listener uma vez com:

```bash
bash telegram-control.sh iniciar
```

Depois, envie `/start`, `/stop`, `/status` ou `/help` em uma conversa privada com seu bot. O comando `/stop` solicita parada segura e aguarda a operação em andamento terminar. Ao iniciar pelo `bash demex.sh iniciar`, o listener também é iniciado automaticamente quando as credenciais estão configuradas. Detalhes em [TELEGRAM_CONTROL.md](TELEGRAM_CONTROL.md).

## Testes e limitações

- Execute os testes com `python -m unittest discover -s tests`.
- A estratégia ativa do DEMEX é HARAMI + ENGOLFO (EMA 21/45): reconhece os quatro padrões do indicador Lua e aplica somente os filtros de tendência EMA 21/45. Não exige cruzamento SMA/WMA. O backtest reproduz essa mesma função de sinal candle a candle, sem olhar candles futuros.
- Conexão real, formato dos candles, ativos OTC e execução/retorno de ordens ainda precisam ser validados localmente com sessão PRACTICE. Não foi possível executar uma sessão autenticada a partir do GitHub.
- A biblioteca é de terceiros e pode mudar. Não há garantia de lucro nem de execução sem falhas.

## Atualização automática no Termux

O script `demex-auto-update.sh` consulta a branch `main` do GitHub a cada 60 segundos. Ele só aplica atualizações quando o robô está parado, a branch local é `main`, o histórico permite avanço rápido e não há alterações locais em arquivos rastreados. Arquivos locais não rastreados, como `.env`, são preservados. Se dependências mudarem, instala `requirements.txt`; depois valida a sintaxe e executa os testes. Se a validação falhar, reverte o código para o commit anterior. O atualizador nunca inicia, para ou reinicia o robô. Consulte o status com `bash ~/.demex-auto-update.sh status`.


A estratégia HARAMI + ENGOLFO ativa fica em `strategies/harami_engolfo_tendencia.py` e é importada pelo motor principal. As estratégias SNIPER e GO 2024 permanecem no repositório como legado/testes, mas não são usadas pelo motor principal.
