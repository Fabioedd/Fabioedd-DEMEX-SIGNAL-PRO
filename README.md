# DEMEX SIGNAL PRO — Python / Bullex (PRACTICE)

Projeto Python para leitura de ativos/candles e execução automática de operações **somente em conta PRACTICE/DEMO**, usando a biblioteca não oficial [CassDs/bullexapi](https://github.com/CassDs/bullexapi). Não é uma API oficial confirmada da corretora; compatibilidade e autorização podem mudar.

## Estratégia e operação

- Estratégia personalizada: `strategies/my_strategy.py` (`get_signal`, `get_pre_signal`, `get_intrabar_signal`).
- Estratégia atual: cruzamento GO 2024 (SMA 1/34 + WMA 5), filtrado por `buffer1` acima/abaixo de zero, RSI 14 acima/abaixo de 50 e preço acima/abaixo da EMA 21.
- Fonte de preço do GO: HLC4 como hipótese para o seletor Lua `inputs.titles = 5`; confirme se corresponde à seleção da plataforma.
- Modalidade: somente opções binárias. A seleção de ativos usa exclusivamente a chave de payout `binary`; payout de Blitz/Turbo nunca habilita um ativo.
- Timeframe configurado: M5 (candles de 300 segundos); expiração: 5 minutos, na vela imediatamente seguinte ao sinal. A entrada é permitida apenas nos primeiros 5 segundos dessa vela.
- Entrada inicial: R$ 5,00.
- Soros nível 1: após o primeiro WIN, a próxima entrada é base + lucro líquido; depois dessa operação o ciclo volta à base. LOSS/TIE reinicia a entrada.
- Stop da sessão: -R$ 15,00; take da sessão: +R$ 30,00.
- Resultado e P&L vêm do retorno da corretora; o terminal informa WIN/LOSS/TIE, valor da operação e acumulado.
- Payout exigido: exatamente 87% no contrato binário. Uma ordem por sinal/vela, uma operação em andamento por vez.

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

## Testes e limitações

- Testes unitários do gerenciamento Soros/stop/take: `python -m unittest discover -s tests`.
- Conexão real, formato dos candles, ativos OTC e execução/retorno de ordens ainda precisam ser validados localmente com sessão PRACTICE. Não foi possível executar uma sessão autenticada a partir do GitHub.
- A biblioteca é de terceiros e pode mudar. Não há garantia de lucro nem de execução sem falhas.
- A estratégia personalizada deve usar apenas candles fechados para evitar sinais intrabar.
