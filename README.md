# DEMEX SIGNAL PRO — Python / Bullex (PRACTICE)

Projeto Python para leitura de ativos/candles e execução automática de operações **somente em conta PRACTICE/DEMO**, usando a biblioteca não oficial [CassDs/bullexapi](https://github.com/CassDs/bullexapi). Não é uma API oficial confirmada da corretora; compatibilidade e autorização podem mudar.

## Estratégia e operação

- Estratégia personalizada ativa: **SNIPER — Confluência**, implementada em Python em `strategies/sniper_confluence.py`.
- Lógica do indicador Lua preservada:
  - SMA rápida de 1 período e SMA lenta de 34 períodos.
  - Diferença `buffer1 = SMA(1) - SMA(34)` e linha de sinal `buffer2 = WMA(buffer1, 5)`.
  - EMA de preço de 21 períodos e EMA de tendência de 45 períodos.
  - **CALL:** cruzamento ascendente de buffer1 sobre buffer2, fechamento acima da EMA21, EMA21 acima da EMA45 e Harami de alta OU Engolfo de alta na mesma vela.
  - **PUT:** cruzamento descendente de buffer1 abaixo de buffer2, fechamento abaixo da EMA21, EMA21 abaixo da EMA45 e Harami de baixa OU Engolfo de baixa na mesma vela.
  - O seletor original `MaValue=5` continua representado por HL2 `(high + low) / 2`; as duas EMAs usam `close`.
  - A entrada continua sendo validada pela lógica de tempo do DEMEX na vela M1 imediatamente seguinte; o sinal intrabar é provisório até a confirmação exigida pelo motor.
- O DEMEX recebe candles M1. O sinal provisório intrabar é revalidado no candle fechado antes de autorizar a entrada.
- Modalidade: somente opções binárias. A seleção de ativos usa exclusivamente a chave de payout `binary`; payout de Blitz/Turbo nunca habilita um ativo.
- Timeframe configurado: M1 (candles de 60 segundos); expiração: 1 minuto, na vela imediatamente seguinte ao sinal. A entrada é permitida apenas nos primeiros 5 segundos dessa vela.
- Entrada inicial: R$ 5,00.
- Soros nível 1: após o primeiro WIN, a próxima entrada é base + lucro líquido; depois dessa operação o ciclo volta à base. LOSS/TIE reinicia a entrada.
- Resultado e P&L vêm do retorno da corretora; o terminal informa WIN/LOSS/TIE, valor da operação e acumulado.
- Payout exigido: mínimo de 84% no contrato binário. Antes de liberar um ativo, o DEMEX testa os últimos 100 candles M1 e exige pelo menos 1 operação decisiva e taxa de acerto estritamente acima de 70%; não há quantidade mínima de operações históricas. A lista é atualizada a cada 30 minutos. Cada varredura completa substitui a lista anterior, inclusive por uma lista vazia; uma varredura interrompida preserva a lista anterior. Uma ordem por sinal/vela, uma operação em andamento por vez.

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
- A estratégia ativa do DEMEX é HARAMI + ENGOLFO (EMA 21/45): reconhece os quatro padrões do indicador Lua e aplica somente os filtros de tendência EMA 21/45. Não exige cruzamento SMA/WMA. Os testes verificam padrões, filtros e ausência de filtros extras.
- Conexão real, formato dos candles, ativos OTC e execução/retorno de ordens ainda precisam ser validados localmente com sessão PRACTICE. Não foi possível executar uma sessão autenticada a partir do GitHub.
- A biblioteca é de terceiros e pode mudar. Não há garantia de lucro nem de execução sem falhas.

## Atualização automática no Termux

O script `demex-auto-update.sh` consulta a branch `main` do GitHub a cada 60 segundos. Ele só aplica atualizações quando o robô está parado, a branch local é `main`, o histórico permite avanço rápido e não há alterações locais em arquivos rastreados. Arquivos locais não rastreados, como `.env`, são preservados. Se dependências mudarem, instala `requirements.txt`; depois valida a sintaxe e executa os testes. Se a validação falhar, reverte o código para o commit anterior. O atualizador nunca inicia, para ou reinicia o robô. Consulte o status com `bash ~/.demex-auto-update.sh status`.


A estratégia HARAMI + ENGOLFO ativa fica em `strategies/harami_engolfo_tendencia.py` e é importada pelo motor principal. As estratégias SNIPER e GO 2024 permanecem no repositório como legado/testes, mas não são usadas pelo motor principal.
