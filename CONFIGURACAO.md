# Configuração do DEMEX Signal PRO

O `settings.json` controla o scanner e o robô automático PRACTICE.

- **Mercado:** `market_mode` aceita OTC ou mercado aberto.
- **Payout:** `minimum_payout_percent` define o mínimo (padrão 84%) e `maximum_payout_percent` o teto (padrão 100%). Somente payout da modalidade binária é considerado; Blitz/Turbo não libera ativo.
- **Backtest:** `backtest_candles` define o histórico M1 (100 candles) e `backtest_min_trades` exige ao menos 5 operações históricas decisivas. O ativo só é aprovado com taxa estritamente maior que 70%; 70% exatos são bloqueados. Empates não entram no cálculo da taxa.
- **Atualização:** a lista de ativos aprovados é recalculada na inicialização e a cada 30 minutos, enquanto o scanner continua trabalhando entre as atualizações.
- **Entrada:** o sinal é calculado na vela M1 fechada; a entrada ocorre somente nos primeiros 5 segundos da vela imediatamente seguinte, com expiração de 1 minuto.
- **Execução:** somente opções binárias em conta PRACTICE/DEMO, com confirmação dupla da conta. A conta REAL é bloqueada.

A taxa histórica é apenas um filtro estatístico sobre uma amostra curta; não representa probabilidade garantida de vitória e não garante lucro. Faça a primeira validação observando a conta PRACTICE.

## Script personalizado

O modo `custom_script` usa `strategies/my_strategy.py`. O script atual é SCRIPT AHORA; preserve suas regras se for alterá-lo. Scripts Python executam código no aparelho onde rodam.
