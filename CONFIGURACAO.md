# Configuração do DEMEX Signal PRO

O `settings.json` controla o scanner e o robô automático PRACTICE.

- **Mercado:** `market_mode` aceita OTC ou mercado aberto.
- **Payout:** somente payout da modalidade binária é considerado; Blitz/Turbo não libera ativo.
- **Backtest:** o filtro histórico mantém os critérios configurados no projeto: taxa de acerto estritamente acima de 70%, sem exigir quantidade mínima de operações históricas.
- **Atualização:** a lista de ativos aprovados é recalculada na inicialização e a cada 30 minutos, enquanto o scanner continua trabalhando entre as atualizações.
- **Entrada:** o sinal GO 2024 é revalidado na vela M1 fechada; a entrada ocorre somente nos primeiros 5 segundos da vela imediatamente seguinte, com expiração de 1 minuto.
- **Execução:** somente opções binárias em conta PRACTICE/DEMO, com confirmação dupla da conta. A conta REAL é bloqueada.

A taxa histórica é apenas um filtro estatístico sobre uma amostra curta; não representa probabilidade garantida de vitória e não garante lucro. Faça a primeira validação observando a conta PRACTICE.

## Estratégia ativa: GO 2024

O modo `custom_script` carrega `strategies/my_strategy.py`. A conversão Python preserva os períodos e condições do indicador enviado: SMA(1), SMA(34), WMA(5), EMA(21) e EMA(45). Não altera os parâmetros de execução, gestão financeira, conexão ou segurança do robô.
