# Difrangy Estoque

Sistema web de controle de estoque com leitura de código de barras, feito para uma fábrica de pijamas. Controla o produto acabado (pijamas, em unidades) e a matéria-prima (rolos de tecido, em metros), com histórico completo de cada entrada e saída.

É um sistema de uso interno: roda num computador da fábrica e é acessado pelo navegador dos outros computadores da mesma rede.

![Painel do estoque](docs/img/painel.png)

## Funcionalidades

- **Leitura por código de barras** com leitor USB ou sem fio comum. Nenhum driver é necessário.
- **Pijamas por SKU:** cada combinação de modelo, tamanho e cor tem seu próprio código (ex.: `PJ-FLO-M-AZ`).
- **Rolos de tecido individuais:** cada rolo recebe uma etiqueta própria (`RL-000001`). No corte, basta bipar o rolo e informar quantos metros foram usados.
- **Painel em tempo real:** qualquer computador com o painel aberto vê as movimentações feitas nos outros em até 3 segundos, sem recarregar a página.
- **Etiquetas prontas para impressão** em código de barras (Code128) ou QR code, geradas em lote pelo próprio sistema. Funcionam em folha A4 ou impressora térmica.
- **Histórico de movimentações** com data, motivo, usuário responsável e filtro por código.
- **Relatórios:** itens com estoque baixo, consumo de tecido por mês e pijamas vendidos por mês.
- **Estoque baixo por item:** cada pijama e cada rolo tem o seu limite de alerta, porque os itens que saem mais precisam de aviso mais cedo.
- **Login por funcionário**, com perfis de administrador e operador.
- **Edição, desativação e exclusão de itens** sem perder o histórico.
- **Exportação em CSV** do estoque, do histórico e dos relatórios, formatada para o Excel em português.
- **Backup automático diário** do banco de dados, com download pela própria interface.
- **Tema claro e escuro**, que segue a preferência do sistema operacional até o usuário escolher um tema.

## Como o estoque é controlado

O saldo de um item nunca é alterado diretamente. Toda entrada ou saída grava uma linha na tabela `movimentacoes` com data e motivo (produção, venda, perda/defeito, ajuste de inventário ou corte de tecido). A atualização do saldo e o registro no histórico acontecem na mesma transação: ou as duas operações são salvas, ou nenhuma.

O estoque nunca fica negativo. A conferência do saldo é feita dentro do próprio `UPDATE` (`WHERE quantidade + ? >= 0`), e não numa consulta separada antes. Assim, dois computadores não conseguem dar baixa na última unidade ao mesmo tempo. As tabelas também têm restrições `CHECK` como segunda camada de proteção.

## Integridade do banco de dados

As regras mais importantes não dependem só do código Python: o próprio banco recusa dados errados, mesmo que o programa tenha um erro ou que alguém altere o arquivo por fora do sistema.

| Regra | Como o banco garante |
|---|---|
| Toda movimentação aponta para um item que existe e está ativo | gatilho (`trigger`) antes de cada `INSERT` |
| Toda movimentação aponta para um usuário que existe | chave estrangeira (`REFERENCES usuarios (login)`) |
| O histórico não pode ser alterado nem apagado | gatilhos que recusam `UPDATE` e `DELETE` em `movimentacoes` |
| Itens e usuários nunca são apagados de verdade | gatilhos que recusam `DELETE` (exclusão lógica, ver abaixo) |
| O código de um item nunca muda | gatilho em `produtos.codigo`; em rolos, o código é uma coluna calculada a partir do número (`RL-` + id) |
| O mesmo pijama (modelo + tamanho + cor) não existe duas vezes | índice `UNIQUE`, sem diferenciar maiúsculas e minúsculas |
| Só existe um master, e ele é um administrador ativo | índice `UNIQUE` parcial e `CHECK` |
| Valores válidos (motivo, data, 0/1, pijama em unidades inteiras, código só com A–Z, 0–9 e hífen) | restrições `CHECK` |

A movimentação aponta para um pijama **ou** para um rolo, conforme `tipo_item`. Uma chave estrangeira só aponta para uma tabela, por isso essa ligação é garantida por gatilho.

A tela de **Administração** mostra uma conferência do banco. Ela verifica se o arquivo está íntegro, se toda ligação entre as tabelas está certa e se o saldo de cada item é igual à soma do histórico dele.

### Atualizações da estrutura

O banco guarda o número da sua versão (`PRAGMA user_version`). Cada mudança de estrutura é uma migração numerada em `migracoes.py`. Ao iniciar, o sistema aplica em ordem só as migrações que faltam:

1. faz um backup do banco atual;
2. roda cada migração numa transação: se algo der errado, nada é alterado;
3. confere se nenhuma ligação entre as tabelas ficou quebrada antes de salvar.

Se a atualização não puder ser feita, por exemplo por haver o mesmo pijama cadastrado duas vezes num banco antigo, o sistema não abre e explica o que corrigir. Um banco de uma versão mais nova que o sistema também é recusado.

Para mudar a estrutura no futuro, escreva uma nova função `_migracao_N` e acrescente-a em `MIGRACOES`. Uma migração que já foi usada nunca deve ser alterada.

## Leitura do código de barras

Leitores de código de barras USB funcionam como um teclado: digitam o código e enviam `Enter`. A tela de leitura aproveita isso com um campo de texto sempre focado dentro de um formulário. O JavaScript intercepta o envio, manda o código para a API com `fetch()` e mostra o resultado na própria página. Um sinal sonoro indica sucesso ou erro, para quem está bipando sem olhar para a tela.

O mesmo campo aceita digitação manual. Enquanto a pessoa digita, uma lista sugere os itens que combinam pelo código ou pela descrição ("floral azul" encontra os pijamas Floral azuis), e as setas ↑ ↓ com Enter escolhem um item. A digitação é tolerante: letras minúsculas, acentos e a falta de hífens são corrigidos automaticamente (`pjflomaz` → `PJ-FLO-M-AZ`, `rl12` → `RL-000012`). Essa correção acontece no servidor, então vale também para quem usa a API. O Enter só seleciona uma sugestão quando ela foi escolhida com as setas, para não interferir no leitor.

| Item bipado | O que acontece |
|---|---|
| Pijama | A movimentação é registrada na hora, com a quantidade e o motivo selecionados. |
| Rolo de tecido | O sistema mostra o rolo e a metragem atual e pede quantos metros foram usados. |

![Tela de leitura](docs/img/bipar.png)

## Usuários e permissões

Cada funcionário entra com o próprio login, e toda movimentação fica registrada com o usuário que a fez. A sessão dura 12 horas, o equivalente a um turno, para que ninguém precise digitar a senha a cada bipe.

| Ação | Operador | Administrador | Master |
|---|:---:|:---:|:---:|
| Bipar entradas e saídas | ✓ | ✓ | ✓ |
| Consultar painel, histórico e relatórios, exportar CSV, imprimir etiquetas | ✓ | ✓ | ✓ |
| Ajuste de inventário | | ✓ | ✓ |
| Cadastrar, editar, desativar e excluir pijamas e rolos | | ✓ | ✓ |
| Definir o limite de estoque baixo de cada pijama e rolo | | ✓ | ✓ |
| Gerenciar usuários e backups | | ✓ | ✓ |
| Configurações do sistema (tipos de etiqueta liberados) | | | ✓ |

Na primeira execução, o sistema pede a criação da conta do **master**: o administrador dono do sistema. Ele é o único que altera as configurações, e nenhum outro usuário pode desativá-lo, rebaixá-lo ou redefinir sua senha. Em bancos de versões anteriores, o administrador mais antigo é promovido a master automaticamente.

As senhas são armazenadas apenas como hash (scrypt, via Werkzeug). O sistema impede que o último administrador ativo seja desativado ou rebaixado.

Excluir um item exige dois passos: primeiro desativá-lo, depois excluí-lo na tela de edição. Um item desativado deixa de aparecer no painel e recusa movimentações. A exclusão é lógica: o item some de todas as telas e não pode voltar, mas continua no banco marcado como excluído. Assim, as movimentações dele continuam no histórico e nos relatórios com o nome certo, marcadas como "(excluído)", e os totais de meses anteriores não mudam. O código de um item excluído nunca é reutilizado. Depois de excluir um pijama, a mesma combinação de modelo, tamanho e cor pode ser cadastrada de novo, com outro código.

![Administração](docs/img/admin.png)

## Tecnologias

| Camada | Tecnologia |
|---|---|
| Back-end | Python 3, Flask, servido pelo Waitress |
| Banco de dados | SQLite (módulo `sqlite3`, SQL escrito à mão, modo WAL) |
| Código de barras e QR code | python-barcode (Code128), qrcode, Pillow |
| Front-end | HTML com templates Jinja, CSS e JavaScript sem frameworks |
| Testes | `unittest` da biblioteca padrão |

A escolha por SQLite e SQL sem ORM foi intencional: o volume de dados de uma fábrica pequena cabe tranquilamente num único arquivo, e a instalação não depende de um servidor de banco de dados.

## Estrutura

```
.
├── app.py              # rotas, login e permissões
├── banco.py            # acesso ao banco e regras de estoque
├── migracoes.py        # estrutura das tabelas e atualização de bancos antigos
├── usuarios.py         # cadastro de usuários e verificação de senha
├── backup.py           # cópias de segurança automáticas
├── exportacao.py       # geração dos arquivos CSV
├── configuracoes.py    # configurações do sistema (alteradas pelo master)
├── etiquetas.py        # imagens do código de barras e do QR code
├── templates/          # páginas HTML (Jinja)
├── static/
│   ├── css/estilo.css
│   └── js/             # comum.js, painel.js (atualização), bipar.js (leitura),
│                       # sugestoes.js (sugestões ao digitar), listas.js (cadastro e seleção)
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

O terminal mostra os dois endereços de acesso: `http://localhost:5000`, para o próprio computador, e `http://<IP na rede>:5000`, para os demais. Se a página não abrir nos outros computadores, verifique se o firewall libera a porta 5000.

Na primeira execução são criados automaticamente:

| Arquivo | Conteúdo |
|---|---|
| `estoque.db` | o banco de dados |
| `.chave_secreta` | a chave que assina os cookies de login |
| `backups/` | as cópias diárias do banco (as 30 mais recentes) |

Os três ficam fora do Git e não devem ser compartilhados.

Para usar outra porta, defina a variável de ambiente `ESTOQUE_PORTA` (ex.: `ESTOQUE_PORTA=8080 python app.py`). Se a porta já estiver em uso, o sistema avisa e não inicia, o que normalmente significa que ele já está aberto em outro terminal. Fechar o sistema (Ctrl+C) e abrir de novo logo em seguida funciona normalmente.

## Testes

```bash
python -m unittest -v
```

Os testes cobrem as regras de estoque (saldo negativo, arredondamento de metragem, códigos duplicados ou reservados, limite de estoque baixo de cada item), a correção do código digitado e as sugestões, login e permissões por perfil, as regras garantidas pelo próprio banco (cada uma é testada com SQL direto, sem passar pelo Python), a atualização de bancos de versões anteriores (inclusive uma que falha no meio), a exportação CSV, o backup, as rotas da API e a renderização das páginas. Cada teste usa um banco temporário próprio, então o estoque real nunca é tocado.

## Códigos e etiquetas

| Tipo | Formato | Exemplo |
|---|---|---|
| Pijama | `PJ-<modelo>-<tamanho>-<cor>` | `PJ-FLO-M-AZ` = Floral, M, Azul |
| Rolo | `RL-<número sequencial>` | `RL-000042` |

O código do pijama é gerado a partir das primeiras letras do modelo e da cor, sem acentos, e pode ser digitado manualmente no cadastro. O prefixo `RL-` é reservado para rolos.

O cadastro é feito numa janela modal. O item recém-cadastrado já volta marcado na lista. Para imprimir, marque um ou vários itens e escolha **Gerar código de barras** ou **Gerar QR code**. A página de impressão permite definir o número de cópias de cada item. O master pode desligar qualquer um dos dois botões nas configurações do sistema.

Os dois formatos guardam o mesmo texto, o código do item, e funcionam igualmente na tela Bipar. Leitores laser comuns leem apenas código de barras. Para ler QR code é necessário um leitor de imagem (2D).

![Etiquetas](docs/img/etiqueta.png)

## Relatórios

![Relatórios](docs/img/relatorios.png)

Um item aparece como estoque baixo quando o saldo fica igual ou menor que o limite dele.

Cada pijama e cada rolo tem o seu limite, definido pelo administrador no cadastro ou na tela de edição.

- **Pijamas** (campo *Estoque baixo com até*, em unidades): um pijama que vende muito pode avisar com 30 unidades, e um que vende pouco, com 2. Com limite 0, o aviso aparece só quando o pijama acaba.
- **Rolos de tecido** (campo *Quase acabando com até*, em metros, aceita decimais): um tecido muito usado pode avisar com 10 m, e um pouco usado, com 1,5 m. Um rolo com 0 m já acabou e não entra na lista de quase acabando.

Itens novos vêm com 5 unidades ou 3 metros, valores das constantes `LIMITE_PIJAMAS_BAIXO` e `LIMITE_METROS_BAIXO` em `banco.py`. O painel, as listas e os relatórios usam o limite de cada item, e a exportação CSV inclui essa coluna.

## Limitações conhecidas

- **Sem HTTPS.** O sistema foi feito para a rede interna. As senhas trafegam sem criptografia entre o navegador e o servidor, então não exponha a porta 5000 à internet.
- **Backup no mesmo computador.** O backup automático protege contra exclusão acidental e dados corrompidos, mas não contra falha do disco. Copie a pasta `backups/` para outro lugar periodicamente.
- **Sem limite de tentativas de login.** Aceitável numa rede interna, mas necessário antes de qualquer acesso externo.

## Próximos passos

- Limite de tentativas de login
- Contagem de inventário guiada pelo leitor, com relatório de divergências
- Cópia automática dos backups para outro computador ou para a nuvem

## Licença

Distribuído sob a licença MIT. Veja o arquivo [LICENSE](LICENSE).
