# Configuração do DEMEX Signal PRO

O `settings.json` controla o scanner e a execução automática em conta PRACTICE/DEMO.

## Configuração atualmente ativa

- **Mercado:** OTC (`market_mode: "OTC"`).
- **Tipo de contrato:** família binária compatível com expiração M1. A integração da BullX pode identificar contratos Turbo para essa duração; o robô não faz fallback para Blitz ou Digital.
- **Timeframe:** M1, com expiração de 1 minuto.
- **Estratégia ativa:** HARAMI + ENGOLFO com filtros de tendência EMA 21/45, carregada de `strategies/harami_engolfo_tendencia.py`.
- **Varredura:** intervalo de 2 segundos (`scan_interval_seconds: 2`).
- **Backtest:** desativado (`backtest_enabled: false`). O DEMEX não executa testes históricos nem filtra ativos por assertividade.
- **Seleção de ativos:** todos os ativos OTC que a BullX informar como disponíveis para a expiração configurada são liberados diretamente para a varredura de sinais.
- **Atualização dos ativos:** a lista de disponibilidade é renovada a cada 900 segundos (15 minutos), sem backtest.
- **Entrada:** sinal calculado e confirmado sobre candle fechado; entrada somente nos primeiros 5 segundos da vela M1 seguinte, após nova validação.
- **Gestão financeira:** entrada inicial de R$ 5,00; Soros nível 1; stop-loss de R$ 15,00; take-profit de R$ 50,00.
- **Execução automática:** habilitada no arquivo, mas protegida por confirmação dupla de PRACTICE na inicialização e imediatamente antes do envio de ordens.

## Estratégia HARAMI + ENGOLFO (EMA 21/45)

A estratégia ativa reconhece Harami de alta/baixa e Engolfo de alta/baixa usando os corpos dos dois candles, conforme as condições do indicador original.

- **CALL:** padrão de alta, fechamento acima da EMA(21) e EMA(21) acima da EMA(45).
- **PUT:** padrão de baixa, fechamento abaixo da EMA(21) e EMA(21) abaixo da EMA(45).
- Não exige cruzamento SMA/WMA, RSI, Bollinger ou outros filtros adicionais.
- O motor de sinais continua usando a estratégia nos candles atuais/fechados; o backtest histórico está desativado e não participa da seleção.

Os scripts GO 2024 e SNIPER podem permanecer no repositório como legado, mas não são a estratégia carregada pelo motor principal nesta configuração.

## Segurança da conta

O DEMEX foi configurado exclusivamente para PRACTICE/DEMO. O envio de ordens exige que `BULLEX_ACCOUNT_TYPE=PRACTICE` no ambiente e que a sessão autenticada confirme `get_balance_mode() == "PRACTICE"`. A validação é repetida imediatamente antes do envio. Se a confirmação falhar, a ordem é bloqueada.

As credenciais BullX ficam somente no arquivo local `.env`; nunca as publique no GitHub. A conexão real, os ativos disponíveis e a resposta de ordens precisam ser verificados no próprio Termux com a conta PRACTICE. Testes automatizados do GitHub não autenticam na conta do usuário e não comprovam disponibilidade da corretora em tempo real.

## Atualização automática

O atualizador `demex-auto-update.sh` consulta a branch `main` a cada 60 segundos. Só instala atualizações quando a branch local é `main`, os arquivos rastreados não têm alterações locais, o histórico permite avanço fast-forward e o DEMEX está parado. Depois atualiza dependências quando necessário, verifica a sintaxe e executa os testes; se a validação falhar, tenta reverter o código. O atualizador não inicia, para nem reinicia o robô.

Consulte o estado local com:

```bash
bash ~/.demex-auto-update.sh status
```

## Limitações importantes

Com o backtest desativado, todos os ativos OTC disponíveis podem ser analisados; isso não representa probabilidade garantida de vitória nem garante lucro. A integração utiliza uma biblioteca de terceiros não oficial; compatibilidade, autenticação, dados de mercado e execução dependem da BullX e precisam ser confirmados em sessão PRACTICE.
