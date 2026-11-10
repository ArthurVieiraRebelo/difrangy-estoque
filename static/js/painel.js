// painel.js — busca os dados no servidor a cada 3 segundos e redesenha as tabelas.
//
// É isso que permite acompanhar o estoque de OUTRO computador: o painel
// pergunta ao servidor "como está o estoque agora?" de tempos em tempos
// (essa técnica se chama "polling"). Quando alguém bipa na produção, em
// no máximo 3 segundos o painel do escritório mostra a mudança.

const INTERVALO_MS = 3000;

// Guarda o saldo de cada código na atualização anterior, para destacar
// (piscar) as linhas que mudaram desde a última vez.
const saldosAnteriores = {};
let primeiraCarga = true;

async function atualizarPainel() {
  try {
    // Com tempo limite: se o servidor travar, o pedido é cancelado e o
    // painel tenta de novo, em vez de ficar parado para sempre.
    const resposta = await buscarComTempoLimite("/api/painel");
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const dados = await resposta.json();

    desenharResumo(dados.resumo);
    desenharProdutos(dados.produtos, dados.limites.pijamas);
    desenharRolos(dados.rolos, dados.limites.metros);
    desenharMovimentacoes(dados.movimentacoes);

    primeiraCarga = false;
    mostrarStatus(`Atualizado às ${new Date().toLocaleTimeString("pt-BR")}`, false);
  } catch {
    mostrarStatus("Sem conexão com o servidor — tentando de novo…", true);
  } finally {
    // setTimeout DEPOIS de terminar (em vez de setInterval): se o servidor
    // demorar, os pedidos não se acumulam um em cima do outro.
    setTimeout(atualizarPainel, INTERVALO_MS);
  }
}

function mostrarStatus(texto, erro) {
  const status = document.getElementById("status-atualizacao");
  status.textContent = texto;
  status.classList.toggle("status-erro", erro);
}

/** plural(1, "rolo", "rolos") -> "rolo"; plural(3, "rolo", "rolos") -> "rolos" */
function plural(quantidade, singular, palavraPlural) {
  return quantidade === 1 ? singular : palavraPlural;
}

function desenharResumo(resumo) {
  document.getElementById("total-pijamas").textContent = formatarNumero(resumo.pijamas_unidades);
  document.getElementById("total-skus").textContent =
    `${resumo.pijamas_skus} ${plural(resumo.pijamas_skus, "item cadastrado", "itens cadastrados")}`;
  document.getElementById("total-metros").textContent = `${formatarNumero(resumo.rolos_metros, 2)} m`;
  document.getElementById("total-rolos").textContent =
    `em ${resumo.rolos_quantidade} ${plural(resumo.rolos_quantidade, "rolo", "rolos")}`;
  document.getElementById("total-baixos").textContent = resumo.itens_baixos;
}

/** Se o saldo mudou desde a última atualização, a linha "pisca" (classe CSS "mudou"). */
function destacarSeMudou(tr, codigo, saldo) {
  if (!primeiraCarga && saldosAnteriores[codigo] !== saldo) {
    tr.classList.add("mudou");
  }
  saldosAnteriores[codigo] = saldo;
}

function desenharProdutos(produtos, limite) {
  const corpo = document.getElementById("tabela-produtos");
  corpo.replaceChildren(); // apaga as linhas antigas

  if (produtos.length === 0) {
    corpo.append(linhaVazia(5, "Nenhum pijama cadastrado."));
    return;
  }
  for (const p of produtos) {
    const tr = document.createElement("tr");
    tr.append(
      criarCelula(p.codigo, "codigo"),
      criarCelula(p.modelo),
      criarCelula(p.tamanho),
      criarCelula(p.cor),
      criarCelula(formatarNumero(p.quantidade), "num"),
    );
    if (p.quantidade <= limite) tr.classList.add("baixo");
    destacarSeMudou(tr, p.codigo, p.quantidade);
    corpo.append(tr);
  }
}

function desenharRolos(rolos, limite) {
  const corpo = document.getElementById("tabela-rolos");
  corpo.replaceChildren();

  if (rolos.length === 0) {
    corpo.append(linhaVazia(4, "Nenhum rolo com tecido."));
    return;
  }
  for (const r of rolos) {
    const tr = document.createElement("tr");
    tr.append(
      criarCelula(r.codigo, "codigo"),
      criarCelula(r.tipo_tecido),
      criarCelula(r.cor),
      criarCelula(formatarNumero(r.metragem_atual, 2), "num"),
    );
    if (r.metragem_atual <= limite) tr.classList.add("baixo");
    destacarSeMudou(tr, r.codigo, r.metragem_atual);
    corpo.append(tr);
  }
}

function desenharMovimentacoes(movimentacoes) {
  const corpo = document.getElementById("tabela-movimentacoes");
  corpo.replaceChildren();

  if (movimentacoes.length === 0) {
    corpo.append(linhaVazia(6, "Nenhuma movimentação ainda."));
    return;
  }
  for (const m of movimentacoes) {
    const tr = document.createElement("tr");
    tr.append(
      criarCelula(formatarDataHora(m.data)),
      criarCelula(m.codigo_item, "codigo"),
      criarCelula(m.descricao || "—"),
      criarSeloTipo(m.tipo),
      criarCelula(formatarQuantidade(m.quantidade, m.tipo_item), "num"),
      criarCelula(MOTIVOS[m.motivo] || m.motivo),
    );
    corpo.append(tr);
  }
}

// Começa a primeira atualização assim que a página abre
atualizarPainel();
