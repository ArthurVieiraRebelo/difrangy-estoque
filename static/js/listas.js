// listas.js — usado nas páginas Pijamas e Tecidos.
// 1) Abre e fecha a janela (modal) de cadastro.
// 2) Controla as caixinhas de seleção e o botão "Gerar etiquetas".

// ---------- 1) Modal de cadastro ----------
// A janela é uma tag <dialog>. showModal() mostra por cima da página,
// escurece o fundo, prende o Tab dentro dela e já fecha com a tecla Esc.

const modal = document.getElementById("modal-cadastro"); // não existe para o operador
const botaoAbrir = document.getElementById("abrir-cadastro");

function abrirModal() {
  modal.showModal();
  modal.querySelector("input").focus(); // cursor já no primeiro campo
}

if (modal && botaoAbrir) {
  botaoAbrir.addEventListener("click", abrirModal);

  // Botões "×" e "Cancelar"
  for (const botao of modal.querySelectorAll("[data-fechar-modal]")) {
    botao.addEventListener("click", () => modal.close());
  }

  // Clicar no fundo escuro (fora da janela) também fecha.
  // Nesse caso o clique "cai" na própria tag <dialog>, e não num campo dentro dela.
  modal.addEventListener("click", (evento) => {
    if (evento.target === modal) modal.close();
  });

  // Se o cadastro deu erro, o servidor manda a página com data-abrir:
  // reabrimos a janela com o que foi digitado, para só corrigir.
  if (modal.hasAttribute("data-abrir")) abrirModal();
}

// ---------- 2) Seleção de itens para gerar etiquetas ----------

const caixas = Array.from(document.querySelectorAll(".selecao-item"));
const marcarTodos = document.getElementById("selecionar-todos");
const contador = document.getElementById("contador-selecao");
// Um botão por tipo de etiqueta liberado pelo master (código de barras, QR code)
const botoesGerar = Array.from(document.querySelectorAll(".botao-gerar"));

function atualizarSelecao() {
  const marcadas = caixas.filter((caixa) => caixa.checked).length;

  if (marcadas === 0) contador.textContent = "Marque os itens para gerar as etiquetas.";
  else if (marcadas === 1) contador.textContent = "1 item marcado.";
  else contador.textContent = `${marcadas} itens marcados.`;

  for (const botao of botoesGerar) botao.disabled = marcadas === 0;

  // A caixinha do cabeçalho fica marcada se TODAS estão marcadas, e
  // "pela metade" (indeterminate) se só algumas estão.
  marcarTodos.checked = marcadas > 0 && marcadas === caixas.length;
  marcarTodos.indeterminate = marcadas > 0 && marcadas < caixas.length;
}

if (botoesGerar.length === 0) {
  // O master desligou todos os tipos de etiqueta: as caixinhas não servem
  // para nada, então escondemos a coluna inteira.
  for (const celula of document.querySelectorAll(".coluna-selecao")) celula.hidden = true;
} else if (caixas.length === 0) {
  marcarTodos.disabled = true;
  for (const botao of botoesGerar) botao.disabled = true;
} else {
  for (const caixa of caixas) caixa.addEventListener("change", atualizarSelecao);

  marcarTodos.addEventListener("change", () => {
    for (const caixa of caixas) caixa.checked = marcarTodos.checked;
    atualizarSelecao();
  });

  // "pageshow" roda também quando a pessoa volta com o botão Voltar do
  // navegador (que lembra quais caixinhas estavam marcadas).
  window.addEventListener("pageshow", atualizarSelecao);
  atualizarSelecao();

  // Rola a página até o item recém-cadastrado, se houver
  const linhaNova = document.querySelector(".linha-nova");
  if (linhaNova) linhaNova.scrollIntoView({ block: "center" });
}
