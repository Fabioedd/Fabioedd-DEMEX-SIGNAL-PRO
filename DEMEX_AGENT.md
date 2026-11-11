# DEMEX Agent (Termux)

O agente sincroniza o repositorio GitHub com a pasta local do DEMEX. Ele **nao inicia, para nem reinicia** o robo de operacoes.

## Instalar no Termux

Depois que esta alteracao for integrada em `main`, dentro de `~/Fabioedd-DEMEX-SIGNAL-PRO`:

```bash
curl -fsSL https://raw.githubusercontent.com/Fabioedd/Fabioedd-DEMEX-SIGNAL-PRO/main/demex-agent.sh -o demex-agent.sh
bash demex-agent.sh instalar
bash demex-agent.sh iniciar
```

O agente consulta o GitHub a cada 60 segundos. Para verificar:

```bash
bash demex-agent.sh status
tail -n 40 .demex-agent.log
```

Para parar somente o agente:

```bash
bash demex-agent.sh parar
```

## Regras de seguranca

- Atualiza somente a branch local `main`, por fast-forward, depois de compilar o Python e passar os testes.
- Faz backup dos arquivos que serao atualizados em `.demex-agent-backups/`.
- Nunca executa `reset --hard`, `clean`, `pull` com merge, nem sobrescreve alteracoes locais.
- Alteracoes locais rastreadas em arquivos-fonte permitidos sao commitadas e enviadas para uma branch separada `termux-sync-<dispositivo>`, nunca diretamente para `main`. Elas precisam de revisao/PR antes de virarem versao oficial.
- Arquivos nao rastreados ou fora da lista permitida bloqueiam a atualizacao remota.
- Nao envia `.env`, logs, PID, backups, dependencias ou arquivos nao rastreados.
- Nao altera `settings.json` por conta propria e nao muda a estrategia.
- Nao envia ordens e nao altera o estado da conta da corretora.
- O processo do robô que ja estiver rodando continua com o codigo carregado em memoria; reiniciar o robô e uma acao separada e manual.

## Sincronizacao nos dois sentidos

- GitHub -> Termux: instala commits ja integrados em `main`, apos validacao local.
- Termux -> GitHub: publica mudancas de codigo/configuracao rastreadas em branch de sincronizacao, para revisao. O push exige credenciais Git com permissao de escrita configuradas no Termux. O agente nao armazena nem solicita tokens.
- GitHub nao consegue executar comandos no Android; o agente local e quem consulta o repositorio.

## Limites atuais

O agente nao cria nem integra Pull Requests automaticamente. Se houver alteracoes locais, o agente publica uma branch; a integracao dessa branch deve ser revisada e aprovada no GitHub. O Android pode suspender processos em segundo plano; para maior continuidade, mantenha o Termux permitido em bateria/segundo plano.
