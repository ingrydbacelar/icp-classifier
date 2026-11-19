const NIVEL = {
  "Entra no ICP": { rotulo: "Alta", classe: "alta" },
  "Revisar manualmente": { rotulo: "Média", classe: "media" },
  "Não entra no ICP": { rotulo: "Baixa", classe: "baixa" },
  "Site não reconhecido": { rotulo: "Site não reconhecido", classe: "neutro" },
};

const CHAVE_PERFIS = "icp_perfis_v1";
const CHAVE_ATIVO = "icp_perfil_ativo_v1";

const elTextoRefs = document.getElementById("txt-refs");
const elTextoUrls = document.getElementById("txt-urls");
const elBtnIniciar = document.getElementById("btn-iniciar");
const elBtnSalvar = document.getElementById("btn-salvar");
const elStatus = document.getElementById("status");
const elAvisos = document.getElementById("avisos");
const elProgressoBarra = document.getElementById("progresso-barra");
const elCorpoTabela = document.getElementById("corpo-tabela");
const elSelPerfil = document.getElementById("sel-perfil");
const elBtnSalvarPerfil = document.getElementById("btn-salvar-perfil");
const elBtnExcluirPerfil = document.getElementById("btn-excluir-perfil");

let resultados = [];
let rodando = false;

const linhasDe = (el) => el.value.split("\n").map((l) => l.trim()).filter(Boolean);

// ---------------------------------------------------------------------------
// Perfis de ICP (salvos no navegador)
// ---------------------------------------------------------------------------

function lerPerfis() {
  try { return JSON.parse(localStorage.getItem(CHAVE_PERFIS)) || {}; } catch { return {}; }
}

function gravarPerfis(perfis) {
  try {
    localStorage.setItem(CHAVE_PERFIS, JSON.stringify(perfis));
    return true;
  } catch {
    alert("Não foi possível salvar no navegador (armazenamento bloqueado ou cheio).");
    return false;
  }
}

function definirAtivo(nome) {
  try {
    if (nome) localStorage.setItem(CHAVE_ATIVO, nome);
    else localStorage.removeItem(CHAVE_ATIVO);
  } catch { /* ignora */ }
}

function atualizarSelect(selecionado) {
  const perfis = lerPerfis();
  elSelPerfil.innerHTML = '<option value="">Perfis salvos</option>';
  Object.keys(perfis)
    .sort((a, b) => a.localeCompare(b, "pt-BR"))
    .forEach((nome) => {
      const op = document.createElement("option");
      op.value = nome;
      op.textContent = `${nome} (${perfis[nome].referencias.length} sites)`;
      elSelPerfil.appendChild(op);
    });
  elSelPerfil.value = selecionado && perfis[selecionado] ? selecionado : "";
  elBtnExcluirPerfil.disabled = !elSelPerfil.value;
}

elSelPerfil.addEventListener("change", () => {
  const nome = elSelPerfil.value;
  const perfis = lerPerfis();
  if (nome && perfis[nome]) elTextoRefs.value = perfis[nome].referencias.join("\n");
  definirAtivo(nome);
  elBtnExcluirPerfil.disabled = !nome;
});

elBtnSalvarPerfil.addEventListener("click", () => {
  const referencias = linhasDe(elTextoRefs);
  if (referencias.length !== 5) {
    alert(`Cole exatamente 5 sites de referência antes de salvar o perfil (você colou ${referencias.length}).`);
    return;
  }
  const atual = elSelPerfil.value;
  const entrada = prompt("Nome do perfil:", atual);
  if (!entrada || !entrada.trim()) return;
  const nome = entrada.trim();

  const perfis = lerPerfis();
  if (perfis[nome] && nome !== atual && !confirm(`Já existe um perfil "${nome}". Sobrescrever?`)) return;

  perfis[nome] = { referencias, atualizado: new Date().toISOString() };
  if (gravarPerfis(perfis)) {
    atualizarSelect(nome);
    definirAtivo(nome);
  }
});

elBtnExcluirPerfil.addEventListener("click", () => {
  const nome = elSelPerfil.value;
  if (!nome || !confirm(`Excluir o perfil "${nome}"?`)) return;
  const perfis = lerPerfis();
  delete perfis[nome];
  if (gravarPerfis(perfis)) {
    atualizarSelect("");
    definirAtivo("");
  }
});

(function iniciarPerfis() {
  let ativo = "";
  try { ativo = localStorage.getItem(CHAVE_ATIVO) || ""; } catch { /* ignora */ }
  atualizarSelect(ativo);
  const perfis = lerPerfis();
  if (elSelPerfil.value && perfis[elSelPerfil.value]) {
    elTextoRefs.value = perfis[elSelPerfil.value].referencias.join("\n");
  }
})();

// ---------------------------------------------------------------------------
// Lista de URLs
// ---------------------------------------------------------------------------

elBtnIniciar.addEventListener("click", iniciar);
elBtnSalvar.addEventListener("click", salvarCsv);

// ---------------------------------------------------------------------------
// Classificação (resposta em streaming do servidor)
// ---------------------------------------------------------------------------

async function iniciar() {
  if (rodando) return;

  const referencias = linhasDe(elTextoRefs);
  const urls = linhasDe(elTextoUrls);

  if (referencias.length !== 5) {
    alert(`Cole exatamente 5 sites de referência (você colou ${referencias.length}).`);
    return;
  }
  if (urls.length === 0) {
    alert("Cole ao menos uma URL para classificar.");
    return;
  }

  resultados = [];
  elCorpoTabela.innerHTML = "";
  elAvisos.textContent = "";
  rodando = true;
  elBtnIniciar.disabled = true;
  elBtnSalvar.disabled = true;
  elProgressoBarra.style.width = "0%";

  const tratar = (ev) => {
    if (ev.tipo === "status") {
      elStatus.textContent = `${ev.msg} · ${ev.feito}/${ev.total}`;
      elProgressoBarra.style.width = `${(ev.feito / ev.total) * 100}%`;
    } else if (ev.tipo === "aviso") {
      const linha = document.createElement("div");
      linha.textContent = `⚠ ${ev.msg}`;
      elAvisos.appendChild(linha);
    } else if (ev.tipo === "fatal") {
      alert(ev.msg);
      elStatus.textContent = "ERRO · " + ev.msg;
    } else if (ev.tipo === "resultado") {
      resultados.push(ev);
      adicionarLinha(ev);
    } else if (ev.tipo === "fim") {
      elStatus.textContent =
        `CONCLUÍDO · ${resultados.length} URLs · ALTA ≥ ${ev.alto} · BAIXA < ${ev.baixo}`;
      elProgressoBarra.style.width = "100%";
    }
  };

  try {
    const resp = await fetch("/classificar_lote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ referencias, urls }),
    });
    const leitor = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { value, done } = await leitor.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const partes = buffer.split("\n");
      buffer = partes.pop();
      partes.filter(Boolean).forEach((p) => tratar(JSON.parse(p)));
    }
  } catch (e) {
    elStatus.textContent = `ERRO · não foi possível falar com o servidor local (${e})`;
  }

  rodando = false;
  elBtnIniciar.disabled = false;
  elBtnSalvar.disabled = resultados.length === 0;
}

function adicionarLinha(resultado) {
  const info = NIVEL[resultado.classificacao] || { rotulo: resultado.classificacao, classe: "erro" };

  const linha = document.createElement("tr");

  const celUrl = document.createElement("td");
  celUrl.className = "celula-url";
  celUrl.textContent = resultado.url;

  const celClassificacao = document.createElement("td");
  celClassificacao.className = `nivel-${info.classe}`;
  const ponto = document.createElement("span");
  ponto.className = `dot dot-${info.classe}`;
  celClassificacao.appendChild(ponto);
  celClassificacao.appendChild(document.createTextNode(info.rotulo));

  const celEvidencia = document.createElement("td");
  celEvidencia.className = "celula-evidencia";
  celEvidencia.textContent = resultado.evidencia;

  linha.appendChild(celUrl);
  linha.appendChild(celClassificacao);
  linha.appendChild(celEvidencia);

  linha.addEventListener("dblclick", () => {
    const u = /^https?:\/\//i.test(resultado.url) ? resultado.url : "https://" + resultado.url;
    window.open(u, "_blank");
  });

  elCorpoTabela.appendChild(linha);
}

function salvarCsv() {
  if (resultados.length === 0) {
    alert("Não há resultados para salvar.");
    return;
  }

  const cabecalho = ["url", "classificacao", "nota", "paginas", "evidencia", "erro"];
  const linhas = resultados.map((r) =>
    cabecalho.map((campo) => `"${String(r[campo] ?? "").replace(/"/g, '""')}"`).join(",")
  );
  const conteudo = "\uFEFF" + [cabecalho.join(","), ...linhas].join("\r\n");

  const blob = new Blob([conteudo], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "resultado_icp.csv";
  link.click();
  URL.revokeObjectURL(link.href);
}
