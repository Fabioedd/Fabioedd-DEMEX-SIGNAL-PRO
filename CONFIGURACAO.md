# Configuração do DEMEX Signal Scanner

Edite `settings.json` para escolher OTC/Mercado aberto, M1/M5, expiração, payout mínimo, confiança mínima, padrões e indicadores.

- **Payout mínimo**: só considera ativos cujo payout retornado pela biblioteca seja >= 80%. O payout é o valor informado pelo feed no momento da consulta e pode mudar.
- **Confiança**: é a concordância/confluência entre regras selecionadas, não é probabilidade estatística de vitória.
- **Sinais**: somente alertas informativos; não há execução de ordens.
- **Ativos abertos**: a biblioteca de terceiros não garante status oficial de negociação. O scanner usa a lista de ativos e payout disponível; indisponibilidade ou ausência de payout exclui o ativo.

## Script personalizado

Defina `strategy_mode` como `custom_script` e crie `strategies/my_strategy.py` com uma função `get_signal(candles, config)` que devolva `CALL`, `PUT` ou `None`. Só use scripts seus e confiáveis: scripts Python executam código no aparelho/servidor onde rodam.
