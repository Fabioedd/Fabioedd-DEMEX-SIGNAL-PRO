# Atualizador DEMEX para Termux

O projeto está migrando para releases estáveis e instalações versionadas.

## Arquitetura

- `termux/demex-bootstrap.sh`: ponto de entrada pequeno, separado do atualizador principal.
- `termux/termux_updater.py`: consulta a última GitHub Release estável, baixa pacote e SHA256, valida, prepara uma versão isolada e troca o link `~/.demex/current`.
- `~/.demex/versions/<tag>`: instalações independentes, cada uma com sua própria `.venv`.
- `~/.demex/shared`: configurações e arquivos persistentes compartilhados.
- `~/Fabioedd-DEMEX-SIGNAL-PRO`: caminho de compatibilidade, convertido em link simbólico para a versão ativa após a primeira instalação.

O atualizador não inicia, para ou reinicia o robô. A troca é bloqueada enquanto um processo `main.py` do DEMEX estiver ativo.

## Publicação

O workflow `.github/workflows/tests.yml` valida PRs e commits na `main`. Uma tag `v*` executa a mesma validação e, somente depois, publica `demex-source.tar.gz` e `SHA256SUMS` em uma GitHub Release.

O checksum protege contra corrupção e divergência entre pacote e manifesto. Para um modelo de confiança mais forte contra substituição maliciosa de ambos os assets, a publicação deverá futuramente adicionar assinatura/atestado verificável.

## Migração

O script de compatibilidade `demex-auto-update.sh` instala o bootstrapper e o atualizador principal no diretório privado do Termux. O atualizador preserva o checkout antigo em `~/.demex/legacy`, preserva `.env` e `settings.json` em `~/.demex/shared`, e converte o caminho conhecido do projeto em link para a versão ativa.

Antes da primeira atualização por release, é necessário publicar uma tag estável `v*) após a aprovação e integração do PR.

## Limitações de validação

Os testes automatizados de CI não simulam o filesystem Android real, perda física de energia ou falta de espaço real no aparelho. Esses cenários precisam de teste de integração em um Termux de teste antes de declarar a migração de produção concluída.
