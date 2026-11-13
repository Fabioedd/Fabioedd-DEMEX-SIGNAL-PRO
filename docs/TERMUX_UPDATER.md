# Atualizador DEMEX para Termux

O projeto está migrando para releases estáveis e instalações versionadas.

## Arquitetura

- `termux/demex-bootstrap.sh`: ponto de entrada pequeno e independente. Consulta a última Release estável e mantém o módulo principal atualizado; se estiver ausente ou inválido, recupera-o depois de conferir o SHA256 do pacote.
- `termux/termux_updater.py`: consulta a Release, verifica pacote e checksum, prepara uma versão isolada e troca atomicamente o link `~/.demex/current`.
- `~/.demex/versions/<tag>`: instalações independentes, cada uma com sua própria `.venv`.
- `~/.demex/shared`: mantém `.env`, `settings.json` e logs compartilhados entre versões.
- `~/Fabioedd-DEMEX-SIGNAL-PRO`: caminho de compatibilidade convertido em link simbólico para a versão ativa. O checkout antigo é preservado em `~/.demex/legacy`.

## Segurança e publicação

O workflow `.github/workflows/tests.yml` valida PRs e commits na `main` com Python 3.13, Bash, módulos rastreados, testes, arquivos essenciais e parâmetros protegidos. Uma tag `v*` só publica `demex-source.tar.gz` e `SHA256SUMS` depois da validação e se o commit da tag já fizer parte do histórico aprovado da `main`.

O checksum detecta corrupção ou divergência entre pacote e manifesto. SHA256 sozinho não autentica o publicador se ambos os assets forem substituídos; assinatura/atestado verificável é um reforço futuro.

A trava usa diretório e PID, sem depender de `flock`. O atualizador bloqueia a migração se detectar o robô ou um dos agentes antigos em execução. Em atualizações posteriores, se o listener Telegram estiver ativo, ele é encerrado com SIGTERM e iniciado novamente a partir da nova versão; se a troca falhar, o listener é restaurado a partir da versão anterior. O atualizador nunca usa SIGKILL e nunca inicia, para ou reinicia o robô. Na primeira migração, se o listener ainda estiver rodando diretamente no checkout antigo, a migração é bloqueada para evitar que o processo fique preso em um diretório que será movido.

## Primeira migração

Depois que o PR for integrado na `main` e a primeira Release estável `v*` estiver publicada, execute este bloco único no Termux. Ele para somente os agentes antigos de atualização e o listener Telegram (não o robô), exige árvore Git sem alterações rastreadas, atualiza o checkout por fast-forward, instala o novo launcher, ativa a verificação automática e inicia novamente o listener Telegram na versão nova. Não inicia o robô.

```bash
cd "$HOME/Fabioedd-DEMEX-SIGNAL-PRO" &&
bash ./demex-agent.sh parar &&
bash "$HOME/.demex-auto-update.sh" parar &&
if [ -f telegram-control.sh ]; then bash telegram-control.sh parar; fi &&
git diff --quiet &&
git diff --cached --quiet &&
git fetch origin main &&
git merge --ff-only origin/main &&
install -m 700 demex-auto-update.sh "$HOME/.demex-auto-update.sh" &&
bash "$HOME/.demex-auto-update.sh" atualizar &&
bash "$HOME/.demex-auto-update.sh" iniciar &&
if [ -f "$HOME/Fabioedd-DEMEX-SIGNAL-PRO/telegram-control.sh" ]; then bash "$HOME/Fabioedd-DEMEX-SIGNAL-PRO/telegram-control.sh" iniciar; fi
```

Se o Git informar alterações rastreadas, o bloco para antes de atualizar; não use `reset --hard` para forçar.

## Comandos depois da migração

- `bash ~/.demex-auto-update.sh atualizar` — verifica e instala a última release estável.
- `bash ~/.demex-auto-update.sh iniciar` — liga o agente de atualização periódica (consulta a cada 60 segundos).
- `bash ~/.demex-auto-update.sh parar` — para somente o agente de atualização.
- `bash ~/.demex-auto-update.sh status` — mostra versão, estado do agente e do robô.

## Limitações de validação

CI valida Python 3.13, Bash, testes unitários, estrutura do pacote e parâmetros protegidos. Não simula filesystem Android real, falta física de energia, falta real de espaço no aparelho nem uma sessão real do Termux. Esses cenários precisam de teste de integração no aparelho antes de declarar a migração de produção concluída.
