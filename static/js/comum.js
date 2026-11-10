// comum.js — funções usadas em mais de uma página.
// (A constante MOTIVOS vem do base.html, que a recebe do Python.)

// Se o servidor não responder em 10 segundos, desistimos do pedido
// (senão a tela ficaria esperando para sempre).
const TEMPO_LIMITE_MS = 10000;

/**
 * Faz um fetch() com tempo limite.
 * "...opcoes" copia tudo que veio em opcoes (method, headers, body) e
 * acrescenta o "signal", que cancela o pedido quando o tempo acaba.
 */
function buscarComTempoLimite(url, opcoes = {}) {
  return fetch(url, { ...opcoes, signal: AbortSignal.timeout(TEMPO_LIMITE_MS) });
}

/**
 * Chama uma rota da API e devolve o JSON da resposta.
 * Nunca "quebra" a página: em caso de problema devolve { ok: false, erro: "..." }
 * com uma mensagem que diz O QUE deu errado (rede ou servidor).
 */
async function chamarApi(url, opcoes) {
  let resposta;
  try {
    resposta = await buscarComTempoLimite(url, opcoes);
  } catch {
    return { ok: false, erro: "Sem conexão com o servidor. Verifique a rede e tente de novo." };
  }
  try {
    return await resposta.json();
  } catch {
    // Chegou resposta, mas não é JSON: o servidor teve um erro interno
    return { ok: false, erro: `Erro no servidor (código ${resposta.status}). Avise o responsável pelo sistema.` };
  }
}

/**
 * Cria uma célula <td> com um texto.
 * Usamos textContent (e não innerHTML) para que nada que foi digitado no
 * cadastro seja interpretado como HTML — é mais seguro.
 */
function criarCelula(texto, classe) {
  const td = document.createElement("td");
  td.textContent = texto;
  if (classe) td.className = classe;
  return td;
}

/** Linha "vazia" para quando a tabela não tem nada. */
function linhaVazia(colunas, texto) {
  const tr = document.createElement("tr");
  tr.className = "vazio";
  const td = criarCelula(texto);
  td.colSpan = colunas;
  tr.append(td);
  return tr;
}

/** 1234.5 -> "1.234,50" (padrão brasileiro). */
function formatarNumero(numero, casas = 0) {
  return Number(numero).toLocaleString("pt-BR", {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  });
}

/** Pijama em unidades, rolo em metros. */
function formatarQuantidade(quantidade, tipoItem) {
  return tipoItem === "rolo"
    ? `${formatarNumero(quantidade, 2)} m`
    : `${formatarNumero(quantidade)} un.`;
}

/** "2026-11-09 14:30:05" -> "09/11 14:30" */
function formatarDataHora(texto) {
  const [data, hora] = texto.split(" ");
  const [ano, mes, dia] = data.split("-");
  return `${dia}/${mes} ${hora.slice(0, 5)}`;
}

/** Selo colorido "Entrada" (verde) ou "Saída" (laranja). */
function criarSeloTipo(tipo) {
  const td = document.createElement("td");
  const selo = document.createElement("span");
  selo.className = `selo selo-${tipo}`;
  selo.textContent = tipo === "entrada" ? "Entrada" : "Saída";
  td.append(selo);
  return td;
}
