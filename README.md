# DEMEX SIGNAL PRO — Python / Bullex (PRACTICE)

Projeto Python para leitura de ativos/candles e execução automática de operações **somente em conta PRACTICE/DEMO**, usando a biblioteca não oficial [CassDs/bullexapi](https://github.com/CassDs/bullexapi). Não é uma API oficial confirmada da corretora; compatibilidade e autorização podem mudar.

## Estratégia e operação

- Estratégia personalizada ativa: **GO 2024**, implementada em Python em `strategies/my_strategy.py`.
- Tradução da lógica do indicador original:
  - SMA rápida de 1 período.
  - SMA lenta de 34 períodos.
  - Diferença `buffer1 = SMA(1) - SMA(34)`.
  - Linha de sinal `buffer2 = WMA(buffer1, 5)`.
  - EMA de preço de 21 períodos e EMA de tendência de 45 períodos.
  - **CALL:** cruzamento ascendente de buffer1 sobre buffer2, fechamento acima da EMA21 e EMA21 acima da EMA45.
  - **PUT:** cruzamento descendente de buffer1 abaixo de buffer2, fechamento abaixo da EMA21 e EMA21 abaixo da EMA45.
  - O seletor original `MaValue=5` é representado por HL2 `(high + low) / 2`; as duas EMAs usam `close`, como no indicador Lua.
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

## Testes e limitações

- Execute os testes com `python -m unittest discover -s tests`.
- Os testes de GO 2024 verificam SMA, WMA, EMA, cruzamentos de compra/venda e confirmação em candle fechado.
- Conexão real, formato dos candles, ativos OTC e execução/retorno de ordens ainda precisam ser validados localmente com sessão PRACTICE. Não foi possível executar uma sessão autenticada a partir do GitHub.
- A biblioteca é de terceiros e pode mudar. Não há garantia de lucro nem de execução sem falhas.

## Atualização automática no Termux

O script `demex-auto-update.sh` consulta a branch `main` do GitHub a cada 60 segundos. Ele só aplica atualizações quando o robô está parado, a branch local é `main`, o histórico permite avanço rápido e não há alterações locais em arquivos rastreados. Arquivos locais não rastreados, como `.env`, são preservados. Se dependências mudarem, instala `requirements.txt`; depois valida a sintaxe e executa os testes. Se a validação falhar, reverte o código para o commit anterior. O atualizador nunca inicia, para ou reinicia o robô. Consulte o status com `bash ~/.demex-auto-update.sh status`.
