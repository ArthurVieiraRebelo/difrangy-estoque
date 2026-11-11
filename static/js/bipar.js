// bipar.js — tela de leitura do código de barras.
//
// O leitor funciona como um TECLADO: ele "digita" o código no campo e aperta Enter.
// O Enter enviaria o formulário e RECARREGARIA a página. Nós impedimos isso com
// preventDefault() e mandamos os dados para o servidor com fetch(), por baixo dos panos.
//
// Fluxo:
//   Pijama -> bipou, o estoque é atualizado na hora.
//   Rolo   -> bipou, aparece a etapa "quantos metros?"; digita e aperta Enter.

// ---------- Elementos da página ----------
const formBipar = document.getElementById("form-bipar");
const campoCodigo = document.getElementById("codigo");
const campoQuantidade = document.getElementById("quantidade");
const motivoProduto = document.getElementById("motivo-produto");

const formRolo = document.getElementById("form-rolo");
const campoMetros = document.getElementById("metros");
const motivoRolo = document.getElementById("motivo-rolo");
const botaoConfirmarRolo = document.getElementById("confirmar-rolo");

const caixaResultado = document.getElementById("resultado");
const historico = document.getElementById("historico-bipar");

// Rolo que foi bipado e está esperando o funcionário digitar os metros
let roloAtual = null;

// Fica true enquanto os metros do rolo estão sendo enviados. Impede que
// um Enter apertado duas vezes desconte o corte duas vezes.
let enviandoRolo = false;

// ---------- Funções auxiliares ----------

/** "entrada" ou "saida", conforme o botão marcado. */
function tipoEscolhido() {
  return document.querySelector('input[name="tipo"]:checked').value;
}

/** Preenche um <select> só com os motivos que fazem sentido (ex: rolo + saída). */
function preencherMotivos(select, tipoItem) {
  select.replaceChildren();
  for (const chave of MOTIVOS_PERMITIDOS[tipoItem][tipoEscolhido()]) {
    const opcao = document.createElement("option");
    opcao.value = chave;
    opcao.textContent = MOTIVOS[chave];
    select.append(opcao);
  }
}

/** Coloca o cursor no campo certo: metros (se esperando um rolo) ou código. */
function focarCampoCerto() {
  if (roloAtual) campoMetros.focus();
  else campoCodigo.focus();
}

// Som curto: agudo = deu certo, grave = erro. Ajuda quem está bipando sem olhar a tela.
let contextoAudio = null;
function tocarSom(sucesso) {
  try {
    contextoAudio = contextoAudio || new AudioContext();
    const oscilador = contextoAudio.createOscillator();
    const volume = contextoAudio.createGain();
    oscilador.frequency.value = sucesso ? 880 : 220;
    volume.gain.value = 0.15;
    oscilador.connect(volume).connect(contextoAudio.destination);
    oscilador.start();
    oscilador.stop(contextoAudio.currentTime + (sucesso ? 0.12 : 0.45));
  } catch {
    // Se o navegador não tiver som, segue sem som.
  }
}

function mostrarResultado(texto, sucesso) {
  caixaResultado.textContent = texto;
  caixaResultado.className = `resultado ${sucesso ? "resultado-ok" : "resultado-erro"}`;
  caixaResultado.hidden = false;
  tocarSom(sucesso);
}

function adicionarAoHistorico(item, tipo, quantidade) {
  // Tira a linha "Nada bipado ainda." (se ela ainda estiver lá)
  const linhaNadaBipado = historico.querySelector(".vazio");
  if (linhaNadaBipado) linhaNadaBipado.remove();

  const tr = document.createElement("tr");
  tr.append(
    criarCelula(new Date().toLocaleTimeString("pt-BR")),
    criarCelula(item.codigo, "codigo"),
    criarCelula(item.descricao),
    criarSeloTipo(tipo),
    criarCelula(formatarQuantidade(quantidade, item.tipo_item), "num"),
    criarCelula(formatarQuantidade(item.saldo, item.tipo_item), "num"),
  );
  historico.prepend(tr); // o mais novo fica em cima

  // Mantém só os 30 últimos para a tabela não crescer sem fim
  while (historico.children.length > 30) historico.lastElementChild.remove();
}

// ---------- Envio da movimentação para o servidor ----------

/** Manda a entrada/saída para o servidor. Devolve true se deu certo. */
async function movimentar(codigo, quantidade, motivo) {
  const tipo = tipoEscolhido();
  const dados = await chamarApi("/api/movimentar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ codigo, tipo, quantidade, motivo }),
  });

  if (!dados.ok) {
    mostrarResultado(`✖ ${dados.erro}`, false);
    return false;
  }

  const item = dados.item;
  const operacao = tipo === "entrada" ? "Entrada" : "Saída";
  const quantidadeNumero = Number(String(quantidade).replace(",", ".")); // "2,5" -> 2.5
  mostrarResultado(
    `✔ ${operacao} de ${formatarQuantidade(quantidadeNumero, item.tipo_item)} — ` +
    `${item.descricao} (${item.codigo}). ` +
    `Saldo agora: ${formatarQuantidade(item.saldo, item.tipo_item)}`,
    true,
  );
  adicionarAoHistorico(item, tipo, quantidadeNumero);
  return true;
}

// ---------- Etapa do rolo ----------

/** O usuário logado tem algum motivo permitido para esta operação em rolo?
 *  (O operador não tem: entrada em rolo existente só existe como ajuste.) */
function podeMovimentarRolo() {
  return MOTIVOS_PERMITIDOS.rolo[tipoEscolhido()].length > 0;
}

function abrirEtapaRolo(rolo) {
  if (!podeMovimentarRolo()) {
    mostrarResultado("✖ Entrada em rolo já cadastrado é feita só pelo administrador (ajuste de inventário).", false);
    fecharEtapaRolo();
    return;
  }
  roloAtual = rolo;
  document.getElementById("rolo-codigo").textContent = rolo.codigo;
  document.getElementById("rolo-descricao").textContent =
    `${rolo.descricao} — ${formatarNumero(rolo.saldo, 2)} m no rolo`;
  preencherMotivos(motivoRolo, "rolo");
  campoMetros.value = "";
  formRolo.hidden = false;
  campoMetros.focus();
}

function fecharEtapaRolo() {
  roloAtual = null;
  formRolo.hidden = true;
  campoCodigo.focus();
}

// ---------- Eventos ----------

// 1) Código bipado (o leitor aperta Enter, que dispara o "submit" do formulário)
formBipar.addEventListener("submit", async (evento) => {
  evento.preventDefault(); // NÃO recarregar a página

  const codigo = campoCodigo.value.trim().toUpperCase();
  campoCodigo.value = ""; // limpa logo, já pronto para o próximo bipe
  if (!codigo) {
    campoCodigo.focus(); // Enter no campo de quantidade cai aqui: só volta para o código
    return;
  }

  // Descobre se o código é de um pijama ou de um rolo
  const dados = await chamarApi(`/api/item/${encodeURIComponent(codigo)}`);
  if (!dados.ok) {
    mostrarResultado(`✖ ${dados.erro}`, false);
    campoCodigo.focus();
    return;
  }

  if (dados.item.tipo_item === "rolo") {
    abrirEtapaRolo(dados.item); // pergunta os metros
  } else {
    await movimentar(codigo, campoQuantidade.value, motivoProduto.value);
    campoQuantidade.value = 1; // volta para 1, para não repetir uma quantidade grande sem querer
    campoCodigo.focus();
  }
});

// 2) Metros do rolo confirmados
formRolo.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  if (enviandoRolo || !roloAtual) return; // já está enviando: ignora o Enter repetido

  enviandoRolo = true;
  botaoConfirmarRolo.disabled = true;
  try {
    const deuCerto = await movimentar(roloAtual.codigo, campoMetros.value, motivoRolo.value);
    if (deuCerto) fecharEtapaRolo();
    else campoMetros.select(); // seleciona o valor errado para digitar de novo
  } finally {
    // "finally" roda sempre, deu certo ou não: libera para o próximo envio
    enviandoRolo = false;
    botaoConfirmarRolo.disabled = false;
  }
});

document.getElementById("cancelar-rolo").addEventListener("click", fecharEtapaRolo);

// Esc cancela a etapa do rolo
document.addEventListener("keydown", (evento) => {
  if (evento.key === "Escape" && roloAtual) fecharEtapaRolo();
});

// Trocar Entrada/Saída atualiza as listas de motivos
for (const radio of document.querySelectorAll('input[name="tipo"]')) {
  radio.addEventListener("change", () => {
    preencherMotivos(motivoProduto, "produto");
    if (roloAtual) {
      if (podeMovimentarRolo()) preencherMotivos(motivoRolo, "rolo");
      else fecharEtapaRolo(); // trocou para uma operação que este usuário não pode fazer
    }
    focarCampoCerto();
  });
}

// Depois de escolher um motivo, o cursor volta para o código
motivoProduto.addEventListener("change", focarCampoCerto);

// Se clicar num lugar "vazio" da página, o cursor volta para o campo certo.
// Sem isso, se o campo perder o foco, o leitor "digitaria" no nada.
document.addEventListener("click", (evento) => {
  if (!evento.target.closest("input, select, button, a, label")) focarCampoCerto();
});

// Ao abrir a página
preencherMotivos(motivoProduto, "produto");
campoCodigo.focus();
