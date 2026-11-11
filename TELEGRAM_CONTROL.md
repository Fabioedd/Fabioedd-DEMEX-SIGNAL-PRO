# Controle remoto do DEMEX pelo Telegram

O serviço `telegram_control.py` recebe comandos privados do Telegram e controla o processo `main.py` no mesmo Termux.

## Pré-requisitos

- `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` configurados no arquivo local `.env`.
- O serviço deve permanecer ativo no Termux para receber comandos.
- Não compartilhe o token do bot.

## Iniciar o serviço de controle no Termux

Na pasta do projeto:

```bash
cd ~/Fabioedd-DEMEX-SIGNAL-PRO
nohup python telegram_control.py > "$HOME/DEMEX_TELEGRAM_CONTROL.log" 2>&1 &
```

Esse comando inicia somente o serviço de controle, não inicia o robô de operações.

## Comandos privados no Telegram

- `/start` — inicia `main.py`, se não houver outro processo DEMEX em execução. O próprio robô continua bloqueando qualquer conta diferente de PRACTICE/DEMO.
- `/stop` — cria o sinal de parada usado pelo robô. Não mata o processo à força: se uma operação já estiver em andamento, ele aguarda a apuração antes de encerrar e não inicia outra entrada.
- `/status` — informa se o processo está ligado ou desligado.
- `/help` — mostra os comandos.

Somente mensagens privadas vindas do `TELEGRAM_CHAT_ID` configurado são aceitas. Outros chats são ignorados.

## Segurança e limites

- O serviço não envia ordens à corretora; somente `main.py` executa a estratégia existente.
- O comando `/stop` é cooperativo e depende do processo principal continuar executando até terminar a operação em andamento.
- O serviço não altera estratégia, ativos OTC, timeframe, expiração, valores, Soros, stop loss, take profit ou conta.
- O Android pode encerrar processos em segundo plano. Se isso acontecer, o serviço precisará ser iniciado novamente no Termux.
- O serviço não é iniciado automaticamente após reinicialização do telefone.
