# Notificações de sinais pelo Telegram

O Telegram funciona somente como canal de recebimento de sinais confirmados do DEMEX.

## Configuração

No arquivo local `.env`, configure:

```env
TELEGRAM_BOT_TOKEN=token_do_seu_bot
TELEGRAM_CHAT_ID=seu_chat_id
```

Mantenha o arquivo `.env` privado e nunca compartilhe o token.

## O que chega no Telegram

Quando a estratégia confirma e seleciona um sinal, o DEMEX envia:
- Ativo;
- Direção COMPRA/CALL ou VENDA/PUT;
- Período M1 e expiração de 1 minuto;
- Valor do RSI usado na confirmação.

## O que o Telegram não faz

- Não inicia o robô;
- Não para o robô;
- Não consulta o estado do robô;
- Não recebe nem executa comandos como `/start`, `/stop`, `/status` ou `/help`;
- Não envia ordens à corretora.

O início e a parada do DEMEX são feitos exclusivamente pelo Termux. A execução automática na corretora continua independente do Telegram e permanece protegida pela confirmação da conta PRACTICE/DEMO.

A mensagem de sinal é apenas informativa. Se o Telegram estiver indisponível, o DEMEX continua seu fluxo normal; uma falha de notificação não deve repetir nem cancelar uma ordem.
