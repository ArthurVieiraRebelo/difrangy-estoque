# Difrangy Estoque

Sistema web de controle de estoque com leitura de código de barras, feito para uma fábrica de pijamas. Controla o produto acabado (pijamas, em unidades) e a matéria-prima (rolos de tecido, em metros), com histórico completo de cada entrada e saída.

É um sistema de uso interno: roda num computador da fábrica e é acessado pelo navegador dos outros computadores da mesma rede.

![Painel do estoque](docs/img/painel.png)

## Funcionalidades

- **Leitura por código de barras** com leitor USB ou sem fio comum. Nenhum driver é necessário.
- **Pijamas por SKU:** cada combinação de modelo, tamanho e cor tem seu próprio código (ex.: `PJ-FLO-M-AZ`).
- **Rolos de tecido individuais:** cada rolo recebe uma etiqueta própria (`RL-000001`). No corte, basta bipar o rolo e informar quantos metros foram usados.
- **Painel em tempo real:** qualquer computador com o painel aberto vê as movimentações feitas nos outros em até 3 segundos, sem recarregar a página.
- **Etiquetas prontas para impressão** em Code128, geradas pelo próprio sistema. Funcionam em folha A4 ou impressora térmica.
- **Histórico de movimentações** com data, motivo e filtro por código.
- **Relatórios:** itens com estoque baixo, consumo de tecido por mês e pijamas vendidos por mês.

## Como o estoque é controlado

O saldo de um item nunca é alterado diretamente. Toda entrada ou saída grava uma linha na tabela `movimentacoes` com data e motivo (produção, venda, perda/defeito, ajuste de inventário ou corte de tecido). A atualização do saldo e o registro no histórico acontecem na mesma transação: ou as duas operações são salvas, ou nenhuma.

O estoque nunca fica negativo. A conferência do saldo é feita dentro do próprio `UPDATE` (`WHERE quantidade + ? >= 0`), e não numa consulta separada antes. Assim, dois computadores não conseguem dar baixa na última unidade ao mesmo tempo. As tabelas também têm restrições `CHECK` como segunda camada de proteção.

## Leitura do código de barras

Leitores de código de barras USB funcionam como um teclado: digitam o código e enviam `Enter`. A tela de leitura aproveita isso com um campo de texto sempre focado dentro de um formulário. O JavaScript intercepta o envio, manda o código para a API com `fetch()` e mostra o resultado na própria página. Um sinal sonoro indica sucesso ou erro, para quem está bipando sem olhar para a tela.

| Item bipado | O que acontece |
|---|---|
| Pijama | A movimentação é registrada na hora, com a quantidade e o motivo selecionados. |
| Rolo de tecido | O sistema mostra o rolo e a metragem atual e pede quantos metros foram usados. |

![Tela de leitura](docs/img/bipar.png)

## Tecnologias

| Camada | Tecnologia |
|---|---|
| Back-end | Python 3, Flask |
| Banco de dados | SQLite (módulo `sqlite3`, SQL escrito à mão, modo WAL) |
| Código de barras | python-barcode (Code128) + Pillow |
| Front-end | HTML com templates Jinja, CSS e JavaScript sem frameworks |
| Testes | `unittest` da biblioteca padrão |

A escolha por SQLite e SQL sem ORM foi intencional: o volume de dados de uma fábrica pequena cabe tranquilamente num único arquivo, e a instalação não depende de um servidor de banco de dados.

## Estrutura

```
.
├── app.py              # rotas das páginas e da API JSON
├── banco.py            # acesso ao banco e regras de negócio
├── etiquetas.py        # geração da imagem do código de barras
├── templates/          # páginas HTML (Jinja)
├── static/
│   ├── css/estilo.css
│   └── js/             # comum.js, painel.js (atualização), bipar.js (leitura)
├── testes/             # testes automatizados
└── requirements.txt
```

## Instalação

Requisitos: Python 3.10 ou mais recente.

```bash
git clone https://github.com/ArthurVieiraRebelo/difrangy-estoque.git
cd difrangy-estoque

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Execução

```bash
python app.py
```

O sistema fica disponível em `http://localhost:5000`. O banco de dados (`estoque.db`) é criado automaticamente na primeira execução.

Nos outros computadores da rede, acesse `http://<IP do computador servidor>:5000`. O endereço aparece no terminal quando o sistema inicia. Se a página não abrir, verifique se o firewall libera a porta 5000.

## Testes

```bash
python -m unittest -v
```

Os testes cobrem as regras de estoque (saldo negativo, arredondamento de metragem, códigos duplicados ou reservados), as rotas da API e a renderização das páginas. Cada teste usa um banco temporário próprio, então o estoque real nunca é tocado.

## Códigos e etiquetas

| Tipo | Formato | Exemplo |
|---|---|---|
| Pijama | `PJ-<modelo>-<tamanho>-<cor>` | `PJ-FLO-M-AZ` = Floral, M, Azul |
| Rolo | `RL-<número sequencial>` | `RL-000042` |

O código do pijama é gerado a partir das primeiras letras do modelo e da cor, sem acentos, e pode ser digitado manualmente no cadastro. O prefixo `RL-` é reservado para rolos.

Depois de cada cadastro, o sistema abre a página da etiqueta, onde é possível escolher o número de cópias e imprimir.

![Etiquetas](docs/img/etiqueta.png)

## Relatórios

![Relatórios](docs/img/relatorios.png)

Os limites de estoque baixo (5 unidades e 3 metros) ficam no início de `banco.py`, nas constantes `LIMITE_PIJAMAS_BAIXO` e `LIMITE_METROS_BAIXO`.

## Limitações conhecidas

- **Sem autenticação.** Qualquer pessoa com acesso à rede interna pode registrar movimentações. Não exponha o sistema à internet.
- **Servidor de desenvolvimento.** O `app.run()` do Flask atende bem poucos computadores. Para uso contínuo, o recomendado é um servidor WSGI como o [Waitress](https://docs.pylonsproject.org/projects/waitress/).
- **Backup manual.** Todo o estoque fica no arquivo `estoque.db`. Faça cópias periódicas dele.

## Próximos passos

- Login de usuários, com registro de quem fez cada movimentação
- Edição e desativação de itens cadastrados
- Exportação dos relatórios para planilha
- Backup automático do banco

## Licença

Distribuído sob a licença MIT. Veja o arquivo [LICENSE](LICENSE).
