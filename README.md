# DEMEX SIGNAL PRO — Python / Bullex (PRACTICE)

Projeto Python para leitura de ativos/candles e execução automática de operações **somente em conta PRACTICE/DEMO**, usando a biblioteca não oficial [CassDs/bullexapi](https://github.com/CassDs/bullexapi). Não é uma API oficial confirmada da corretora; compatibilidade e autorização podem mudar.

## Estratégia e operação

- Estratégia personalizada: `strategies/my_strategy.py` (`get_signal`, `get_pre_signal`, `get_intrabar_signal`).
- Estratégia atual: **SCRIPT AHORA BB**, traduzida para Python:
  - **PUT/VENDA:** toque na banda superior de Bollinger (SMA 20, desvio 2), retração para baixo confirmada e, depois, toque na C1 (máxima do M15 anterior) em candle verde.
  - **CALL/COMPRA:** toque na banda inferior de Bollinger (SMA 20, desvio 2), retração para cima confirmada e, depois, toque na C2 (mínima do M15 anterior) em candle vermelho.
  - A retração exige uma vela posterior ao toque da banda fechando de volta para dentro da banda e na direção da retração. O toque na zona precisa acontecer em uma vela posterior à retração.
  - A sequência deve ocorrer dentro do mesmo bloco M15 e expira após 15 candles M1.
  - C1/C2 são reconstruídas a partir dos quinze candles M1 completos que formam a vela M15 anterior. Se os quinze candles necessários não estiverem disponíveis, o sinal é descartado por segurança.
- O DEMEX recebe candles M1. O backtest simula a entrada na abertura da vela seguinte e o resultado no fechamento dessa vela, sem usar candles futuros para formar o sinal.
- Sinais que autorizam ordens usam somente o último candle fechado; o método intrabar é apenas diagnóstico e é revalidado no fluxo normal de execução.
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
- Os testes de SCRIPT AHORA BB verificam as Bandas de Bollinger, a reconstrução da M15, a sequência banda → retração → C1/C2 e a confirmação em candle fechado.
- Conexão real, formato dos candles, ativos OTC e execução/retorno de ordens ainda precisam ser validados localmente com sessão PRACTICE. Não foi possível executar uma sessão autenticada a partir do GitHub.
- A biblioteca é de terceiros e pode mudar. Não há garantia de lucro nem de execução sem falhas.

## Atualização automática no Termux

O script `demex-auto-update.sh` consulta a branch `main` do GitHub a cada 60 segundos. Ele só aplica atualizações quando o robô está parado, a branch local é `main`, o histórico permite avanço rápido e não há alterações locais em arquivos rastreados. Arquivos locais não rastreados, como `.env`, são preservados. Se dependências mudarem, instala `requirements.txt`; depois valida a sintaxe e executa os testes. Se a validação falhar, reverte o código para o commit anterior. O atualizador nunca inicia, para ou reinicia o robô. Consulte o status com `bash ~/.demex-auto-update.sh status`.
