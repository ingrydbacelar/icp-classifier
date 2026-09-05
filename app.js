const NIVEL = {
  "Entra no ICP": { rotulo: "Alta", classe: "alta" },
  "Revisar manualmente": { rotulo: "Média", classe: "media" },
  "Não entra no ICP": { rotulo: "Baixa", classe: "baixa" },
};

const elTextoUrls = document.getElementById("txt-urls");
const elInputArquivo = document.getElementById("input-arquivo");
const elBtnCarregar = document.getElementById("btn-carregar");
const elBtnIniciar = document.getElementById("btn-iniciar");
const elBtnSalvar = document.getElementById("btn-salvar");
const elStatus = document.getElementById("status");
const elProgressoBarra = document.getElementById("progresso-barra");
const elCorpoTabela = document.getElementById("corpo-tabela");

let resultados = [];
let rodando = false;

elBtnCarregar.addEventListener("click", () => elInputArquivo.click());

elInputArquivo.addEventListener("change", () => {
  const arquivo = elInputArquivo.files[0];
  if (!arquivo) return;
  const leitor = new FileReader();
  leitor.onload = () => { elTextoUrls.value = leitor.result; };
  leitor.readAsText(arquivo, "utf-8");
});

elBtnIniciar.addEventListener("click", iniciar);
elBtnSalvar.addEventListener("click", salvarCsv);

function aguardar(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function iniciar() {
  if (rodando) return;

  const urls = elTextoUrls.value
    .split("\n")
    .map((linha) => linha.trim())
    .filter((linha) => linha.length > 0);

  if (urls.length === 0) {
    alert("Cole ao menos uma URL antes de iniciar.");
    return;
  }

  resultados = [];
  elCorpoTabela.innerHTML = "";
  rodando = true;
  elBtnIniciar.disabled = true;
  elBtnSalvar.disabled = true;
  elProgressoBarra.style.width = "0%";

  const total = urls.length;

  for (let i = 0; i < total; i++) {
    const url = urls[i];
    elStatus.textContent = `PROCESSANDO ${i + 1}/${total} · ${url}`;

    const resultado = await classificarUrl(url);
    resultados.push(resultado);
    adicionarLinha(resultado);

    elProgressoBarra.style.width = `${((i + 1) / total) * 100}%`;

    if (i < total - 1) {
      await aguardar(1000 + Math.random() * 1500);
    }
  }

  elStatus.textContent = `CONCLUÍDO · ${total} URLs PROCESSADAS`;
  rodando = false;
  elBtnIniciar.disabled = false;
  elBtnSalvar.disabled = false;
}

async function classificarUrl(url) {
  try {
    const resp = await fetch("/classificar_url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const dados = await resp.json();
    return {
      url: dados.url || url,
      classificacao: dados.classificacao || "Erro",
      evidencia: dados.evidencia || "",
      erro: dados.erro || "",
    };
  } catch (e) {
    return {
      url,
      classificacao: "Erro",
      evidencia: `Não foi possível acessar o servidor local (${e}).`,
      erro: String(e),
    };
  }
}

function adicionarLinha(resultado) {
  const info = NIVEL[resultado.classificacao] || { rotulo: resultado.classificacao, classe: "erro" };

  const linha = document.createElement("tr");

  const celUrl = document.createElement("td");
  celUrl.className = "celula-url";
  celUrl.textContent = resultado.url;

  const celClassificacao = document.createElement("td");
  celClassificacao.className = `nivel-${info.classe}`;
  celClassificacao.innerHTML = `<span class="dot dot-${info.classe}"></span>${info.rotulo}`;

  const celEvidencia = document.createElement("td");
  celEvidencia.textContent = resultado.evidencia;

  linha.appendChild(celUrl);
  linha.appendChild(celClassificacao);
  linha.appendChild(celEvidencia);

  linha.addEventListener("dblclick", () => {
    window.open(resultado.url, "_blank");
  });

  elCorpoTabela.appendChild(linha);
}

function salvarCsv() {
  if (resultados.length === 0) {
    alert("Não há resultados para salvar.");
    return;
  }

  const cabecalho = ["url", "classificacao", "evidencia", "erro"];
  const linhas = resultados.map((r) =>
    cabecalho.map((campo) => `"${String(r[campo] || "").replace(/"/g, '""')}"`).join(",")
  );
  const conteudo = "\uFEFF" + [cabecalho.join(","), ...linhas].join("\r\n");

  const blob = new Blob([conteudo], { type: "text/csv;charset=utf-8;" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "resultado_icp.csv";
  link.click();
  URL.revokeObjectURL(link.href);
}
