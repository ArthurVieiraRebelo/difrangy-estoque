// sugestoes.js — lista de sugestões que aparece embaixo de um campo de código
// enquanto a pessoa digita (usada na tela Bipar).
//
// Como funciona:
// 1) Tudo que é digitado vira MAIÚSCULO na hora.
// 2) Depois de 150 ms sem digitar (para não fazer um pedido por letra),
//    pergunta ao servidor quais itens combinam: /api/sugestoes?q=<texto>.
// 3) Mostra a lista. Setas ↑ ↓ escolhem, Enter confirma, Esc fecha.
//    Clicar numa sugestão também confirma.
// 4) O leitor de código de barras continua funcionando igual: se nenhuma
//    sugestão foi escolhida com as setas, o Enter envia o que foi digitado.
//
// Acessibilidade: o campo é um "combobox" e a lista um "listbox". O foco do
// teclado fica sempre no campo; aria-activedescendant diz ao leitor de tela
// qual sugestão está destacada.

const ESPERA_ANTES_DE_BUSCAR_MS = 150;

/**
 * Liga as sugestões num campo.
 * campo       -> o <input> onde a pessoa digita
 * lista       -> o <ul> onde as sugestões aparecem
 * aoEscolher  -> função chamada com o item escolhido ({codigo, descricao, ...})
 * Devolve { fechar } para quem usa poder fechar a lista (ex: ao enviar o formulário).
 */
function ativarSugestoes(campo, lista, aoEscolher) {
  let sugestoes = [];      // itens mostrados agora
  let destacada = -1;      // posição da sugestão destacada pelas setas (-1 = nenhuma)
  let timer = null;        // controla a espera antes de buscar
  let numeroDoPedido = 0;  // para ignorar respostas que chegam fora de ordem

  function fechar() {
    clearTimeout(timer);
    numeroDoPedido++; // respostas que ainda estão a caminho passam a ser ignoradas
    sugestoes = [];
    destacada = -1;
    lista.replaceChildren();
    lista.hidden = true;
    campo.setAttribute("aria-expanded", "false");
    campo.removeAttribute("aria-activedescendant");
  }

  function destacar(posicao) {
    destacada = posicao;
    lista.querySelectorAll("[role=option]").forEach((opcao, i) => {
      const ativa = i === posicao;
      opcao.classList.toggle("destacada", ativa);
      opcao.setAttribute("aria-selected", ativa ? "true" : "false");
      if (ativa) {
        campo.setAttribute("aria-activedescendant", opcao.id);
        opcao.scrollIntoView({ block: "nearest" }); // mantém visível se a lista rolar
      }
    });
  }

  function escolher(posicao) {
    const item = sugestoes[posicao];
    fechar();
    aoEscolher(item);
  }

  function mostrar(itens) {
    lista.replaceChildren();
    sugestoes = itens;
    destacada = -1;

    if (itens.length === 0) {
      const aviso = document.createElement("li");
      aviso.className = "sem-sugestao";
      aviso.textContent = "Nenhum item encontrado.";
      lista.append(aviso);
    }

    itens.forEach((item, posicao) => {
      const opcao = document.createElement("li");
      opcao.id = `sugestao-${posicao}`;
      opcao.setAttribute("role", "option");
      opcao.setAttribute("aria-selected", "false");

      const codigo = document.createElement("span");
      codigo.className = "codigo";
      codigo.textContent = item.codigo;
      const descricao = document.createElement("span");
      descricao.className = "sugestao-descricao";
      descricao.textContent = item.descricao;
      const saldo = document.createElement("span");
      saldo.className = "num";
      saldo.textContent = formatarQuantidade(item.saldo, item.tipo_item);
      opcao.append(codigo, descricao, saldo);

      // mousedown (e não click): acontece ANTES de o campo perder o foco,
      // e o preventDefault impede que ele perca o foco.
      opcao.addEventListener("mousedown", (evento) => {
        evento.preventDefault();
        escolher(posicao);
      });
      lista.append(opcao);
    });

    lista.hidden = false;
    campo.setAttribute("aria-expanded", "true");
  }

  async function buscar(texto) {
    const meuPedido = ++numeroDoPedido;
    const dados = await chamarApi(`/api/sugestoes?q=${encodeURIComponent(texto)}`);
    // Se outro pedido saiu depois deste, ou o campo já foi limpo
    // (o leitor bipou e enviou), esta resposta não serve mais.
    if (meuPedido !== numeroDoPedido || campo.value.trim() === "") return;
    if (dados.ok) mostrar(dados.sugestoes);
  }

  campo.addEventListener("input", () => {
    // Maiúsculas enquanto digita, sem tirar o cursor do lugar
    const inicio = campo.selectionStart;
    const fim = campo.selectionEnd;
    campo.value = campo.value.toUpperCase();
    campo.setSelectionRange(inicio, fim);

    clearTimeout(timer);
    const texto = campo.value.trim();
    if (!texto) {
      fechar();
      return;
    }
    timer = setTimeout(() => buscar(texto), ESPERA_ANTES_DE_BUSCAR_MS);
  });

  campo.addEventListener("keydown", (evento) => {
    if (lista.hidden || sugestoes.length === 0) return; // lista fechada: teclas normais

    if (evento.key === "ArrowDown") {
      evento.preventDefault(); // não mover o cursor dentro do campo
      destacar((destacada + 1) % sugestoes.length);
    } else if (evento.key === "ArrowUp") {
      evento.preventDefault();
      destacar(destacada <= 0 ? sugestoes.length - 1 : destacada - 1);
    } else if (evento.key === "Enter" && destacada >= 0) {
      // Só "rouba" o Enter se a pessoa escolheu uma sugestão com as setas.
      // Sem isso, o Enter do leitor de código de barras envia normalmente.
      evento.preventDefault();
      escolher(destacada);
    } else if (evento.key === "Escape") {
      evento.stopPropagation(); // o Esc fecha só a lista, não a etapa do rolo
      fechar();
    }
  });

  campo.addEventListener("blur", fechar);

  return { fechar };
}
