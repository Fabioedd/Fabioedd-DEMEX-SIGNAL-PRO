# DEMEX SIGNAL PRO — Python / BullX (PRACTICE)

Projeto Python para leitura de ativos/candles e execução automática em conta **PRACTICE/DEMO**. A integração utiliza uma biblioteca não oficial da BullX; compatibilidade e autorização podem mudar.

## Estratégia ativa: GO 2024 FILTRADO

O indicador Lua enviado foi traduzido para Python em `strategies/my_strategy.py`, preservando os parâmetros e as condições:

- Fonte `MaValue=5`: HL2 ((high + low) / 2), mantendo as EMAs calculadas sobre `close).
- `buffer1 = SMA(1) - SMA(21)`.
- `buffer2 = WMA(buffer1, 3)`.
- EMA(21) como filtro de preço e EMA(45) como filtro de tendência.
- ADX(14): o Lua define a suavização como EMA de `2*n-1`, portanto EMA(27) para TR, +DM, -DM, DX e ADX.
- **CALL:** cruzamento ascendente de `buffer1` sobre `buffer2`, fechamento acima da EMA(21), EMA(21) acima da EMA(45) e ADX >= 35.
- **PUT:** cruzamento descendente, fechamento abaixo da EMA(21), EMA(21) abaixo da EMA(45) e ADX >= 35.

O DEMEX analisa candles M1 e mantém as validações intrabar e imediatamente antes do envio da ordem. O sinal precisa continuar válido na mesma vela M1; a janela de reconhecimento permanece em 5 segundos.

## Operação e proteção

- Mercado configurado: OTC.
- Tipo de contrato: família binária compatível com expiração de 1 minuto.
- Entrada inicial: R$ 5,00; Soros nível 1; stop-loss e take-profit conforme `settings.json`.
- Varredura de sinais: 2 segundos.
- Intervalo global entre entradas: **60 segundos**, iniciado somente depois que a corretora confirma a ordem.
- Apenas uma ordem pode ficar aberta ou pendente; confirmações desconhecidas são reconciliadas antes de liberar nova entrada.
- Seleção de ativos segue a configuração atual; com `backtest_enabled: false`, todos os ativos OTC disponíveis são liberados para varredura.
- A lista de disponibilidade é atualizada a cada 15 minutos.

As estratégias adicionais Harami/Engolfo e Sniper Confluence foram removidas. A estratégia principal carregada em `settings.json` continua sendo `strategies/my_strategy.py`.

## Segurança

O envio de ordens exige confirmação de PRACTICE no ambiente e na sessão conectada. Conta REAL é bloqueada. Credenciais ficam somente no arquivo local `.env`; não publique tokens ou senhas.

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

No Termux, o atualizador automático pode instalar os commits validados da branch `main`. Não inicie o robô durante a atualização.
