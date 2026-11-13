# Configuração do DEMEX Signal PRO

## Configuração ativa

- Mercado OTC; timeframe M1; expiração de 1 minuto.
- Estratégia principal: **GO 2024 FILTRADO**, em `strategies/my_strategy.py`.
- Varredura: 2 segundos (`scan_interval_seconds: 2`).
- Intervalo global entre entradas: **60 segundos** (`entry_cooldown_seconds: 60`), contado somente após confirmação da ordem pela corretora.
- Backtest desativado; ativos OTC disponíveis são liberados para análise.
- Atualização da lista de ativos: 900 segundos.
- Gestão financeira: entrada inicial R$ 5,00, Soros nível 1, stop-loss R$ 15,00 e take-profit R$ 50,00.
- Execução protegida por confirmação de conta PRACTICE/DEMO.

## Indicador GO 2024 FILTRADO

A tradução em Python preserva o script Lua recebido:

1. Fonte MaValue=5 traduzida para HL2 ((high + low) / 2).
2. SMA rápida de 1 período e SMA lenta de 34 períodos.
3. `buffer1 = SMA(1) - SMA(34)`; `buffer2 = WMA(buffer1, 5)`.
4. EMA(21) e EMA(45) sobre o fechamento.
5. ADX(14) com suavização EMA(27), pois o Lua define `wilder = 2 * Adx_period - 1`; a mesma suavização é aplicada a TR, +DM, -DM e DX.
6. CALL: cruzamento ascendente, close > EMA21, EMA21 > EMA45 e ADX >= 35.
7. PUT: cruzamento descendente, close < EMA21, EMA21 < EMA45 e ADX >= 35.

A estratégia não adiciona RSI, Bollinger, Harami, Engolfo ou filtros que não constam no script. As estratégias adicionais Harami/Engolfo e Sniper Confluence foram removidas.

## Entrada e confirmação

O sinal intrabar é provisório. Antes da ordem, o DEMEX revalida o sinal, o candle M1 original e o relógio da corretora. A entrada permanece restrita à mesma vela M1 e à tolerância de reconhecimento de 5 segundos. O intervalo global de 60 segundos começa apenas depois da confirmação da corretora.

## Segurança

O envio de ordens exige `BULLEX_ACCOUNT_TYPE=PRACTICE` e confirmação de `get_balance_mode() == "PRACTICE"`. Credenciais ficam no `.env`, fora do GitHub. Testes automatizados não autenticam na BullX nem comprovam disponibilidade em tempo real.
