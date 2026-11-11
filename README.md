# DEMEX SIGNAL PRO — Python / Bullex (PRACTICE)

Projeto Python para leitura de ativos/candles e execução automática de operações **somente em conta PRACTICE/DEMO**, usando a biblioteca não oficial [CassDs/bullexapi](https://github.com/CassDs/bullexapi). Não é uma API oficial confirmada da corretora; compatibilidade e autorização podem mudar.

## Estratégia e operação

- Estratégia personalizada: `strategies/my_strategy.py` (`get_signal`, `get_pre_signal`, `get_intrabar_signal`).
- Estratégia atual: cruzamento GO 2024 (SMA 1/34 + WMA 5), filtrado por `buffer1` acima/abaixo de zero, RSI 14 acima/abaixo de 50 e preço acima/abaixo da EMA 21.
- Fonte de preço do GO: HLC4 como hipótese para o seletor Lua `inputs.titles = 5`; confirme se corresponde à seleção da plataforma.
- Universo de ativos: somente payout entre 85% e 90%, inclusive. Ativos fora dessa faixa não entram na análise de candles. Ativos com pré-sinal ficam no início da fila, mas os demais ativos dentro da faixa continuam sendo monitorados.
- Timeframe configurado: M1; expiração: 1 minuto.
- Entrada inicial: R$ 5,00.
- Soros nível 1: após o primeiro WIN, a próxima entrada é base + lucro líquido; depois dessa operação o ciclo volta à base. LOSS/TIE reinicia a entrada.
- Stop da sessão: -R$ 15,00; take da sessão: +R$ 30,00.
- Resultado e P&L vêm do retorno da corretora; o terminal informa WIN/LOSS/TIE, valor da operação e acumulado.
- Uma ordem por sinal/vela, uma operação em andamento por vez.

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

Inicie com `python main.py`. A execução automática está habilitada em `settings.json`, mas o robô só envia ordens após conexão e confirmação da conta PRACTICE.

## Testes e limitações

- Testes unitários do gerenciamento Soros/stop/take: `python -m unittest discover -s tests`.
- Conexão real, formato dos candles, ativos OTC e execução/retorno de ordens ainda precisam ser validados localmente com sessão PRACTICE. Não foi possível executar uma sessão autenticada a partir do GitHub.
- A biblioteca é de terceiros e pode mudar. Não há garantia de lucro nem de execução sem falhas.
- A estratégia personalizada deve usar apenas candles fechados para evitar sinais intrabar.
