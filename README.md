# DEMEX SIGNAL PRO — Integração Python Bullex (somente leitura)

Este repositório inicia uma camada Python para testar conexão e leitura de ativos/candles usando a biblioteca de terceiros [`CassDs/bullexapi`](https://github.com/CassDs/bullexapi). **Não é uma API oficial confirmada da Bullex.** A compatibilidade, disponibilidade e autorização do acesso devem ser verificadas antes de qualquer uso.

## Escopo desta primeira integração

- Conectar usando credenciais fornecidas por variáveis de ambiente.
- Informar quando a conexão falhar ou exigir 2FA.
- Consultar a lista de ativos.
- Consultar candles M1 (60 segundos) e M5 (300 segundos).
- Não contém chamadas para abrir, modificar ou fechar operações.

## Segurança

1. Nunca coloque e-mail, senha, cookies, tokens ou códigos 2FA no código ou em commits.
2. Copie `.env.example` para `.env` no seu computador e preencha localmente.
3. O `.env` não deve ser enviado ao GitHub.
4. Comece somente com conta PRACTICE/DEMO, se disponível.
5. Revise os termos da corretora e da biblioteca antes de conectar uma conta.

## Instalação local

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS/Termux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edite .env localmente; não compartilhe suas credenciais.
python main.py
```

Configure `BULLEX_ACTIVE` com um símbolo que realmente exista na lista retornada pelo método de ativos. O exemplo usa `EURUSD` apenas como valor inicial e pode precisar ser alterado.

## Limitações conhecidas

- O pacote é de terceiros e pode quebrar se a corretora alterar seus protocolos.
- O método de conexão pode exigir um fluxo 2FA adicional; este primeiro teste apenas identifica essa necessidade e não armazena códigos.
- A lista de ativos retornada pelo pacote não garante que todos estejam abertos ou disponíveis para OTC.
- Não foi validada equivalência entre cotações de candles e preços executáveis exibidos na interface da corretora.
- Nenhum sinal de trading deve ser gerado enquanto a conexão e a atualidade dos candles não forem verificadas.

## Próxima etapa

Executar o teste local em conta de prática, confirmar conexão, validar a estrutura real dos candles e só então construir o serviço de streaming e o motor de análise.
