# Controle remoto do DEMEX pelo Telegram

O serviço `telegram_control.py` recebe comandos privados do Telegram e controla o processo `main.py` no mesmo Termux. Ele pode iniciar o DEMEX quando estiver parado e solicitar uma parada segura quando estiver ligado.

## 1. Configuração única

No arquivo local `.env` da pasta do projeto, configure:

```env
TELEGRAM_BOT_TOKEN=token_fornecido_pelo_BotFather
TELEGRAM_CHAT_ID=seu_chat_id
```

Crie o bot pelo `@BotFather` no Telegram e obtenha seu Chat ID. **Não envie o token no chat e não o publique no GitHub.** O arquivo `.env` é local e não deve ser versionado.

## 2. Ativar o controle remoto no Termux

Na pasta do projeto, execute uma vez:

```bash
cd ~/Fabioedd-DEMEX-SIGNAL-PRO
bash telegram-control.sh iniciar
```

Esse comando inicia somente o serviço de controle; ele não liga o robô de operações. O serviço permanece ativo em segundo plano para receber comandos mesmo quando o DEMEX estiver desligado.

Para consultar ou parar somente o listener:

```bash
bash telegram-control.sh status
bash telegram-control.sh parar
```

Quando o robô for iniciado por `bash demex.sh iniciar`, o controle Telegram também será iniciado automaticamente, caso as credenciais estejam configuradas. Se você inicia o robô diretamente com `python main.py`, mantenha o listener iniciado separadamente pelo comando acima.

## 3. Comandos privados no Telegram

Envie os comandos em uma conversa privada com o seu bot:

- `/start` — liga o DEMEX, se não houver outro processo em execução.
- `/stop` — solicita desligamento seguro. Não encerra à força: se houver uma operação em andamento, aguarda o resultado e não inicia outra entrada.
- `/status` — informa se o processo está ligado ou desligado.
- `/help` ou `/ajuda` — mostra os comandos.

Somente mensagens privadas vindas do `TELEGRAM_CHAT_ID` configurado são aceitas. Outros chats e grupos são ignorados.

## Segurança e limites

- O listener não envia ordens à corretora; somente `main.py` executa a estratégia.
- O robô continua bloqueado para conta diferente de PRACTICE/DEMO. O comando `/start` não contorna a confirmação dupla de conta.
- O comando `/stop` é cooperativo: solicita que o robô pare novas entradas e aguarde o resultado de uma operação já aberta.
- O serviço não altera estratégia, ativos OTC, timeframe, expiração, valores, Soros, stop loss ou take profit.
- O listener precisa permanecer ativo no Termux para receber comandos. Depois de reiniciar o Android, inicie-o novamente, a menos que tenha configurado o Termux:Boot.
- O Android pode encerrar processos em segundo plano; mantenha o Termux permitido para execução em segundo plano.
