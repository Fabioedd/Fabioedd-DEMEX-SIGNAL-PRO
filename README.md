# DEMEX SIGNAL PRO — Python / Bullex (PRACTICE)

Projeto Python para leitura de ativos/candles e execução automática de operações **somente em conta PRACTICE/DEMO**, usando a biblioteca não oficial [CassDs/bullexapi](https://github.com/CassDs/bullexapi). Não é uma API oficial confirmada da corretora; compatibilidade e autorização podem mudar.

## Estratégia e operação

- Estratégia ativa: **GO 2024 SUPER**, implementada em Python em `strategies/my_strategy.py`.
- Regras preservadas do indicador Lua:
  - `buffer1 = SMA(1) - SMA(34)` e `buffer2 = WMA(buffer1, 5)`.
  - A fonte `MaValue=5` é traduzida para HL2 ((high + low) / 2); os filtros EMA usam o fechamento.
  - **CALL:** cruzamento ascendente de `buffer1` sobre `buffer2`, fechamento acima da EMA(21) e EMA(21) acima da EMA(45).
  - **PUT:** cruzamento descendente, fechamento abaixo da EMA(21) e EMA(21) abaixo da EMA(45).
  - Não adiciona RSI, Bollinger, Harami, Engolfo ou filtros que não existem no indicador enviado.
- O DEMEX recebe candles M1. O sinal é calculado sobre a vela fechada e só libera entrada na vela M1 seguinte, nos primeiros 5 segundos, após confirmar o relógio da corretora e o padrão novamente.
- Modalidade: opções da família binária. Para expiração M1/M5, a API da BullX classifica o contrato como Turbo; a seleção consulta o grupo de ativos correspondente à expiração. O DEMEX não faz fallback para Blitz ou Digital. Payout não é usado como critério de seleção.
- Timeframe configurado: M1 (candles de 60 segundos); expiração: 1 minuto, na vela imediatamente seguinte ao sinal. A entrada é permitida apenas nos primeiros 5 segundos dessa vela.
- Entrada inicial: R$ 5,00.
- Soros nível 1: após o primeiro WIN, a próxima entrada é base + lucro líquido; depois dessa operação o ciclo volta à base. LOSS/TIE reinicia a entrada.
- Resultado e P&L vêm do retorno da corretora; o terminal informa WIN/LOSS/TIE, valor da operação e acumulado.
- Seleção automática: o backtest histórico está desativado (`backtest_enabled: false`). O DEMEX libera diretamente para a varredura todos os ativos OTC que a BullX informar como disponíveis para a expiração configurada. A lista de disponibilidade é renovada a cada 15 minutos, sem executar backtest.

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

Inicie com `python main.py`. A execução automática está habilitada em `settings.json`, mas o robô só envia contratos compatíveis com a expiração configurada após conexão e confirmação da conta PRACTICE.


## Controle remoto e notificações pelo Telegram

O projeto oferece comandos privados para ligar/desligar o DEMEX e também envia notificações de início, resultado de operação e relatório final. Configure `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` no arquivo local `.env`; nunca publique o token.

Ative o listener no Termux:
```bash
bash telegram-control.sh iniciar
```

Comandos privados no bot:
- `/start` — inicia o DEMEX se estiver parado.
- `/stop` — solicita parada segura e aguarda a operação aberta terminar.
- `/status` — informa se o robô está ligado.
- `/help` — mostra os comandos.

Ao iniciar com `bash demex.sh iniciar`, o listener também é iniciado automaticamente quando as credenciais estão configuradas. O listener aceita apenas mensagens privadas do Chat ID configurado; ele não envia ordens à corretora. Detalhes em [TELEGRAM_CONTROL.md](TELEGRAM_CONTROL.md).

Quando a confirmação de uma ordem fica desconhecida, o DEMEX preserva o identificador da solicitação original e não reenvia aquela ordem. Após aguardar uma expiração M1 (um minuto), ele pode liberar a análise e a busca por uma nova entrada, enquanto continua tentando reconciliar o resultado da solicitação original. Se a resposta tardia chegar, o resultado é associado à ordem original e o placar/notificação são atualizados. Enquanto a ordem estiver sem confirmação, o resultado financeiro e os limites da sessão podem ficar temporariamente incompletos; se nunca houver reconciliação, confira manualmente o histórico da BullX antes de confiar no fechamento financeiro da sessão.

## Testes e limitações

- Execute os testes com `python -m unittest discover -s tests`.
- A estratégia ativa do DEMEX é HARAMI + ENGOLFO (EMA 21/45): reconhece os quatro padrões do indicador Lua e aplica somente os filtros de tendência EMA 21/45. Não exige cruzamento SMA/WMA. O backtest histórico está desativado na configuração atual; a lógica de geração e confirmação dos sinais permanece ativa.
- Conexão real, formato dos candles, ativos OTC e execução/retorno de ordens ainda precisam ser validados localmente com sessão PRACTICE. Não foi possível executar uma sessão autenticada a partir do GitHub.
- A biblioteca é de terceiros e pode mudar. Não há garantia de lucro nem de execução sem falhas.

## Atualização automática no Termux

O script `demex-auto-update.sh` consulta a branch `main` do GitHub a cada 60 segundos. Ele só aplica atualizações quando o robô está parado, a branch local é `main`, o histórico permite avanço rápido e não há alterações locais em arquivos rastreados. Arquivos locais não rastreados, como `.env`, são preservados. Se dependências mudarem, instala `requirements.txt`; depois valida a sintaxe e executa os testes. Se a validação falhar, reverte o código para o commit anterior. O atualizador nunca inicia, para ou reinicia o robô. Consulte o status com `bash ~/.demex-auto-update.sh status`.


A estratégia GO 2024 SUPER ativa fica em `strategies/my_strategy.py` e é importada pelo motor principal. A estratégia SNIPER permanece separada em `strategies/sniper_confluence.py` e não é combinada com o GO 2024.
