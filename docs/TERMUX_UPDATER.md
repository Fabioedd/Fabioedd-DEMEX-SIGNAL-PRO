# Atualizador DEMEX para Termux

O projeto está migrando para releases estáveis e instalações versionadas.

## Arquitetura

- `termux/demex-bootstrap.sh`: ponto de entrada pequeno e independente. Se o atualizador principal estiver ausente ou inválido, baixa o pacote da última release estável, confere o SHA256 e recupera somente o módulo do atualizador.
- `termux/termux_updater.py`: consulta a última GitHub Release estável, valida pacote e checksum, prepara uma versão isolada e troca o link `~/.demex/current`.
- `~/.demex/versions/<tag>`: instalações independentes, cada uma com sua própria `.venv`.
- `~/.demex/shared`: mantém `.env`, `settings.json` e logs compartilhados entre versões.
- `~/Fabioedd-DEMEX-SIGNAL-PRO`: caminho de compatibilidade, convertido em link simbólico para a versão ativa após a primeira instalação. O checkout anterior é preservado em `~/.demex/legacy`.

## Segurança e publicação

O workflow `.github/workflows/tests.yml` valida PRs e commits na `main`. Uma tag `v*` executa a mesma validação e, somente depois, publica `demex-source.tar.gz` e `SHA256SUMS` em uma GitHub Release.

O checksum protege contra corrupção e divergência entre pacote e manifesto. SHA256 sozinho não autentica o publicador se ambos os assets forem substituídos; assinatura/atestado verificável fica como reforço futuro.

O atualizador usa trava por diretório com identificação de PID e recuperação de trava abandonada. Não usa `flock`. Bloqueia atualizações se detectar o robô ou os agentes antigos ainda ativos.

## Migração e operação

O script `demex-auto-update.sh` é a ponte de compatibilidade para o arquivo antigo `~/.demex-auto-update.sh`. Ao ser executado a partir do checkout, instala o bootstrapper e o módulo principal no diretório privado do Termux e delega a operação.

Depois de integrar este PR, publique uma tag estável `v*` somente após a aprovação do workflow. A primeira execução migra o checkout existente, preserva os arquivos locais importantes e não inicia o robô.

Comandos:
- `bash ~/.demex-auto-update.sh atualizar` — atualiza.
- `bash ~/.demex-auto-update.sh status` — mostra versão e estado.
- `bash ~/.demex-bootstrap.sh atualizar` — chama diretamente o bootstrapper.

## Limitações de validação

CI valida Python 3.13, Bash, testes unitários, estrutura do pacote e parâmetros protegidos. Não simula filesystem Android real, falta física de energia, falta real de espaço no aparelho nem uma sessão real do Termux. Esses cenários precisam de teste de integração no aparelho antes de declarar a migração de produção concluída.
