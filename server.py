import json
import random
import re
import threading
import time
import unicodedata
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import numpy as np
import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # Playwright é opcional
    sync_playwright = None

BASE_DIR = Path(__file__).resolve().parent
PORTA = 8765

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------------------

MODELO = "paraphrase-multilingual-MiniLM-L12-v2"  # multilíngue, ~470 MB na 1ª execução

TOP_K = 2           # média das K referências mais parecidas
FATOR_ALTO = 0.75   # nota >= base * FATOR_ALTO  -> Entra no ICP
FATOR_BAIXO = 0.35  # nota <  base * FATOR_BAIXO -> Não entra no ICP
# "base" = quão parecidas as referências são entre si (calculado a cada rodada)

MAX_PAGINAS = 5       # páginas internas lidas além da home
MIN_TEXTO_JS = 600    # se a home tiver menos texto que isso, tenta renderizar com Playwright
CHUNKS_HOME = 40
CHUNKS_PAGINA = 25
MIN_CHUNKS = 3
TIMEOUT = 15

REDES_SOCIAIS = {
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "fb.com": "Facebook",
    "fb.me": "Facebook",
    "linkedin.com": "LinkedIn",
    "lnkd.in": "LinkedIn",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# (palavras no caminho/texto do link, peso). Maior peso = página mais útil.
PAGINAS_PESO = [
    (["servico", "solucoe", "atuacao", "area-de", "areas", "especialidade", "expertise"], 10),
    (["produto", "segmento", "setores", "setor", "mercado", "industria"], 8),
    (["cliente", "case", "projeto", "portfolio", "obras"], 6),
    (["sobre", "quem-somos", "quem somos", "empresa", "institucional"], 5),
]
EVITAR = [
    "blog", "noticia", "politica", "privacidade", "termos", "cookie", "login",
    "carrinho", "checkout", "trabalhe", "vagas", "contato", "fale-conosco",
    "lgpd", "sitemap", "tag/", "category", "author", "wp-content", "wp-json", "feed",
]
EXT_IGNORADAS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip",
                 ".rar", ".doc", ".docx", ".xls", ".xlsx", ".mp4", ".mp3")

RUIDO = re.compile(
    r"cookie|pol[ií]tica de privacidade|todos os direitos|©|copyright|lgpd|aceitar|desenvolvido por",
    re.I,
)


# Textos genéricos de vários setores. A média deles representa "um site de empresa qualquer"
# e é subtraída de todos os vetores, para sobrar só o que é específico de cada site.
FUNDO = [
    "Fazemos bolos, doces e salgados artesanais para festas e casamentos.",
    "Escritório de advocacia com atuação em direito civil, trabalhista e empresarial.",
    "Clínica odontológica com tratamentos de ortodontia, implantes e clareamento dental.",
    "Escola de idiomas com aulas de inglês e espanhol para crianças e adultos.",
    "Agência de marketing digital especializada em redes sociais, tráfego pago e branding.",
    "Imobiliária com imóveis para venda e aluguel, apartamentos e casas.",
    "Restaurante com culinária italiana, pratos executivos e delivery.",
    "Academia com musculação, pilates, aulas de dança e personal trainer.",
    "Plataforma de software como serviço para gestão de equipes e projetos.",
    "Escritório de contabilidade com abertura de empresas, impostos e folha de pagamento.",
    "Transportadora com frete rodoviário, logística e entregas para todo o Brasil.",
    "Produtores rurais de soja, milho e gado com tecnologia no campo.",
    "Hotel e pousada com café da manhã, piscina e hospedagem para famílias.",
    "Loja de roupas femininas e acessórios com as últimas tendências da moda.",
    "Construtora de edifícios residenciais e empreendimentos imobiliários de alto padrão.",
    "Consultoria de recursos humanos, recrutamento e seleção de talentos.",
    "Engenharia industrial com projetos, montagem e manutenção de plantas e fábricas.",
    "Loja virtual de eletrônicos, celulares, notebooks e eletrodomésticos com frete grátis.",
    "Hospital e laboratório de análises clínicas com exames e consultas médicas.",
    "Faculdade com cursos de graduação, pós-graduação e extensão universitária.",
    "Organização sem fins lucrativos com projetos sociais, voluntariado e doações.",
    "Energia solar fotovoltaica para residências, comércios e indústrias.",
    "Empresa de tecnologia da informação com suporte, infraestrutura e segurança digital.",
    "Indústria de alimentos com produção de massas, biscoitos e congelados.",
    "Indústria química com fabricação de tintas, solventes e produtos de limpeza.",
    "Banco e cooperativa de crédito com empréstimos, investimentos e seguros.",
    "Concessionária de veículos novos e seminovos, peças e oficina mecânica.",
    "Salão de beleza, estética e barbearia com cortes, coloração e tratamentos.",
    "Somos uma empresa com mais de 20 anos de experiência, qualidade e compromisso com o cliente.",
    "Entre em contato e solicite um orçamento sem compromisso; atendemos todo o Brasil.",
    "Nossa missão, visão e valores: ética, respeito, inovação e foco em resultados.",
    "Conheça nossa equipe de profissionais qualificados e nossa história.",
]

# ---------------------------------------------------------------------------
# UTILITÁRIOS
# ---------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    texto = texto.lower()
    return unicodedata.normalize("NFD", texto).encode("ascii", "ignore").decode()


def garantir_https(url: str) -> str:
    return url if re.match(r"^https?://", url, re.I) else "https://" + url


def host_base(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def rede_social(url: str):
    host = (urlparse(garantir_https(url)).hostname or "").lower()
    for dominio, nome in REDES_SOCIAIS.items():
        if host == dominio or host.endswith("." + dominio):
            return nome
    return None


def normaliza_linhas(x):
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(n, 1e-9)


# ---------------------------------------------------------------------------
# COLETA (requests + Playwright, sitemap, metadados, várias páginas)
# ---------------------------------------------------------------------------

def texto_visivel(html) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return soup.get_text(" ", strip=True)


def renderizar(navegador, url):
    """Abre a página num Chromium headless (executa JavaScript). Retorna (html, url_final)."""
    ctx = navegador.new_context(user_agent=HEADERS["User-Agent"], ignore_https_errors=True, locale="pt-BR")
    try:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        page.wait_for_timeout(800)
        return page.content(), page.url
    finally:
        ctx.close()


def baixar_html(url, navegador=None, forcar_js=False):
    """requests primeiro; se falhar ou vier quase vazio, tenta Playwright. Retorna (html, url_final)."""
    erro = None
    resultado = None
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        resultado = (r.content, r.url)
    except Exception as e:
        erro = e

    if navegador is not None:
        precisa = resultado is None or len(texto_visivel(resultado[0])) < MIN_TEXTO_JS
        if precisa:
            try:
                resultado = renderizar(navegador, url)
            except Exception as e:
                erro = erro or e

    if resultado is None:
        raise erro
    return resultado


def urls_do_sitemap(origem):
    achadas = []
    visitados = {"n": 0}

    def ler(u, nivel=0):
        try:
            r = requests.get(u, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                return
            locs = re.findall(r"<loc>\s*(?:<!\[CDATA\[)?\s*(.*?)\s*(?:\]\]>)?\s*</loc>", r.text, flags=re.S | re.I)
        except Exception:
            return
        for loc in locs:
            if ".xml" in loc.lower().split("?")[0][-8:]:
                if nivel < 1 and visitados["n"] < 3:
                    visitados["n"] += 1
                    ler(loc, nivel + 1)
            else:
                achadas.append(loc)

    ler(origem + "/sitemap.xml")
    if not achadas:
        try:
            r = requests.get(origem + "/robots.txt", headers=HEADERS, timeout=8)
            for m in re.findall(r"(?im)^sitemap:\s*(\S+)", r.text)[:2]:
                ler(m)
        except Exception:
            pass
    return achadas[:3000]


def pontuar(url, texto=""):
    alvo = normalizar(urlparse(url).path + " " + texto)
    if any(e in alvo for e in EVITAR):
        return 0
    melhor = 0
    for chaves, peso in PAGINAS_PESO:
        if any(c in alvo for c in chaves):
            melhor = max(melhor, peso)
    return melhor


def extrair_meta(soup):
    out = []
    if soup.title:
        out.append(soup.title.get_text(" ", strip=True))
    for attrs in ({"name": "description"}, {"property": "og:description"}, {"property": "og:title"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            out.append(tag["content"].strip())
    vistos, limpos = set(), []
    for m in out:
        m = re.sub(r"\s+", " ", m).strip()
        if len(m) >= 15 and m.lower() not in vistos:
            vistos.add(m.lower())
            limpos.append(m)
    return limpos


def extrair_chunks(soup, fonte, limite):
    """Quebra o texto da página em trechos de até ~280 caracteres."""
    for t in soup(["script", "style", "noscript", "nav", "footer", "form", "svg"]):
        t.decompose()

    pedacos = []
    for linha in soup.get_text(separator="\n", strip=True).splitlines():
        linha = re.sub(r"\s+", " ", linha).strip()
        if not linha:
            continue
        for s in re.split(r"(?<=[.!?])\s+", linha):
            while len(s) > 280:
                corte = s.rfind(" ", 0, 280)
                corte = corte if corte > 100 else 280
                pedacos.append(s[:corte])
                s = s[corte:].strip()
            if s:
                pedacos.append(s)

    chunks, atual = [], ""
    for p in pedacos:
        if atual and len(atual) + len(p) + 1 > 280:
            chunks.append(atual)
            atual = p
        else:
            atual = f"{atual} {p}".strip()
        if len(atual) >= 160:
            chunks.append(atual)
            atual = ""
    if atual:
        chunks.append(atual)

    uteis = [(c, fonte) for c in chunks if len(c.split()) >= 5 and not RUIDO.search(c)]
    return uteis[:limite]


def coletar_site(url, navegador):
    """Home + metadados + até MAX_PAGINAS páginas internas (links da home e sitemap)."""
    url = garantir_https(url)
    html, base = baixar_html(url, navegador)
    soup = BeautifulSoup(html, "html.parser")
    host = host_base(base)
    origem = f"{urlparse(base).scheme}://{urlparse(base).netloc}"

    meta = extrair_meta(soup)
    candidatas = {}  # url -> (peso, profundidade)

    def considerar(href, texto=""):
        u = urldefrag(urljoin(base, href))[0]
        p = urlparse(u)
        if p.scheme not in ("http", "https") or host_base(u) != host:
            return
        if p.query or p.path.lower().endswith(EXT_IGNORADAS):
            return
        if p.path in ("", "/") or u.rstrip("/") == base.rstrip("/"):
            return
        peso = pontuar(u, texto)
        if peso:
            prof = len([s for s in p.path.split("/") if s])
            u = u.rstrip("/")
            if u not in candidatas or peso > candidatas[u][0]:
                candidatas[u] = (peso, prof)

    for a in soup.find_all("a", href=True):
        considerar(a["href"], a.get_text(" ", strip=True))
    for u in urls_do_sitemap(origem):
        considerar(u)

    # escolhe as melhores, no máx. 2 por categoria (para variar: serviços, clientes, sobre...)
    ordenadas = sorted(candidatas.items(), key=lambda kv: (-kv[1][0], kv[1][1], len(kv[0])))
    escolhidas, por_peso = [], {}
    for u, (peso, _) in ordenadas:
        if por_peso.get(peso, 0) >= 2:
            continue
        por_peso[peso] = por_peso.get(peso, 0) + 1
        escolhidas.append(u)
        if len(escolhidas) >= MAX_PAGINAS:
            break

    chunks = [(m, "meta") for m in meta[:3]]
    chunks += extrair_chunks(soup, "/", CHUNKS_HOME)
    paginas = 1
    for u in escolhidas:
        try:
            h, _ = baixar_html(u, navegador)
            chunks += extrair_chunks(BeautifulSoup(h, "html.parser"), urlparse(u).path or "/", CHUNKS_PAGINA)
            paginas += 1
        except Exception:
            continue

    vistos, unicos = set(), []
    for c, f in chunks:
        chave = normalizar(c)
        if chave not in vistos:
            vistos.add(chave)
            unicos.append((c, f))

    if len(unicos) < MIN_CHUNKS:
        raise ValueError("pouco texto encontrado; o site pode bloquear o acesso")
    return {"chunks": unicos, "paginas": paginas}


# ---------------------------------------------------------------------------
# EMBEDDINGS E CLASSIFICAÇÃO
# ---------------------------------------------------------------------------

_modelo = None


def obter_modelo():
    global _modelo
    if _modelo is None:
        from sentence_transformers import SentenceTransformer
        _modelo = SentenceTransformer(MODELO)
    return _modelo


_mu_fundo = None


def obter_mu(modelo):
    global _mu_fundo
    if _mu_fundo is None:
        _mu_fundo = modelo.encode(FUNDO, batch_size=32, normalize_embeddings=True,
                                  show_progress_bar=False).mean(axis=0)
    return _mu_fundo


def cortar(texto, limite=220):
    if len(texto) <= limite:
        return texto
    corte = texto.rfind(" ", 0, limite)
    return texto[: corte if corte > 80 else limite].rstrip(" ,;:.") + "…"


def rotulo_fonte(fonte):
    return "descrição do site" if fonte == "meta" else fonte


def evidencia_trechos(d, mu, centroide, nota_baixa):
    chunks = d["chunks"]
    if nota_baixa:
        # site fora do ICP: mostra o que o site diz sobre si mesmo
        metas = [c for c in chunks if c[1] == "meta" and len(c[0].split()) >= 8]
        base = max(metas, key=lambda c: len(c[0])) if metas else next(
            (c for c in chunks if len(c[0].split()) >= 8), chunks[0])
        return f"O site fala de: “{cortar(base[0])}” ({rotulo_fonte(base[1])})"

    scores = normaliza_linhas(d["vecs"] - mu) @ centroide
    escolhidos, usados = [], set()
    for i in np.argsort(scores)[::-1]:
        texto, fonte = chunks[i]
        if len(texto.split()) < 8 or texto[:40] in usados:
            continue
        usados.add(texto[:40])
        escolhidos.append(f"“{cortar(texto)}” ({rotulo_fonte(fonte)})")
        if len(escolhidos) == 2:
            break
    return "\n".join(escolhidos) if escolhidos else "Sem trechos relevantes."


def classificar_lote(refs_urls, urls, emit):
    if len(refs_urls) != 5:
        emit({"tipo": "fatal", "msg": f"São necessários exatamente 5 sites de referência (recebi {len(refs_urls)})."})
        return

    # separa referências e candidatos que são redes sociais
    refs_ok = []
    for u in refs_urls:
        rede = rede_social(u)
        if rede:
            emit({"tipo": "aviso", "msg": f"Referência ignorada (é um perfil de {rede}): {u}"})
        else:
            refs_ok.append(u)

    entradas = []
    for u in urls:
        rede = rede_social(u)
        entradas.append({"url": u, "social": rede, "dados": None, "erro": ""})
    a_baixar = [e for e in entradas if not e["social"]]

    total = len(refs_ok) + len(a_baixar) + 2
    feitos = 0

    # 1) modelo
    emit({"tipo": "status", "msg": "CARREGANDO MODELO DE EMBEDDINGS (1ª vez baixa ~470 MB)", "feito": 0, "total": total})
    try:
        modelo = obter_modelo()
    except Exception as e:
        emit({"tipo": "fatal", "msg": f"Não foi possível carregar o modelo de embeddings ({e}). "
                                       "Confirme que 'sentence-transformers' está instalado e que há internet na primeira execução."})
        return

    # 2) navegador (opcional)
    pw = navegador = None
    if sync_playwright is None:
        emit({"tipo": "aviso", "msg": "Playwright não instalado: sites que dependem de JavaScript podem vir vazios."})
    else:
        try:
            pw = sync_playwright().start()
            navegador = pw.chromium.launch(headless=True)
        except Exception as e:
            emit({"tipo": "aviso", "msg": f"Playwright indisponível (rode 'playwright install chromium'): {e}"})
            if pw:
                pw.stop()
            pw = navegador = None

    try:
        # 3) referências
        refs = []
        for u in refs_ok:
            feitos += 1
            emit({"tipo": "status", "msg": f"LENDO REFERÊNCIA {u}", "feito": feitos, "total": total})
            try:
                refs.append(coletar_site(u, navegador))
            except Exception as e:
                emit({"tipo": "aviso", "msg": f"Referência ignorada: {u} ({e})"})
            time.sleep(random.uniform(0.3, 0.8))

        if len(refs) < 2:
            emit({"tipo": "fatal", "msg": "Preciso de pelo menos 2 referências que carreguem corretamente."})
            return

        # 4) candidatos
        for e in a_baixar:
            feitos += 1
            emit({"tipo": "status", "msg": f"LENDO {e['url']}", "feito": feitos, "total": total})
            try:
                e["dados"] = coletar_site(e["url"], navegador)
            except Exception as ex:
                e["erro"] = str(ex)
            time.sleep(random.uniform(0.3, 0.8))
    finally:
        if navegador:
            navegador.close()
        if pw:
            pw.stop()

    # 5) embeddings
    emit({"tipo": "status", "msg": "CALCULANDO EMBEDDINGS E SIMILARIDADE...", "feito": total - 1, "total": total})
    todos = refs + [e["dados"] for e in entradas if e["dados"]]
    textos = [c for d in todos for c, _ in d["chunks"]]
    emb = modelo.encode(textos, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    pos = 0
    for d in todos:
        n = len(d["chunks"])
        d["vecs"] = emb[pos:pos + n]
        d["doc"] = d["vecs"].mean(axis=0)
        pos += n

    # centraliza: subtrai o vetor médio de "um site de empresa qualquer" (ver FUNDO)
    mu = obter_mu(modelo)
    for d in todos:
        d["doc_c"] = normaliza_linhas(d["doc"] - mu)

    R = np.array([r["doc_c"] for r in refs])
    centroide = normaliza_linhas(R.mean(axis=0))

    # limites calibrados pelas próprias referências (quão parecidas elas são entre si)
    sim_refs = R @ R.T
    k_ref = min(TOP_K, len(refs) - 1)
    loo = [np.sort(np.delete(sim_refs[i], i))[::-1][:k_ref].mean() for i in range(len(refs))]
    base = float(np.mean(loo))
    if base < 0.10:
        emit({"tipo": "aviso", "msg": "Os exemplos de referência têm pouco em comum entre si; "
                                       "os resultados podem ser pouco confiáveis."})
        base = 0.10
    alto, baixo = base * FATOR_ALTO, base * FATOR_BAIXO

    # 6) classifica
    k = min(TOP_K, len(refs))
    for e in entradas:
        url = e["url"]
        if e["social"]:
            emit({"tipo": "resultado", "url": url, "classificacao": "Site não reconhecido", "nota": "",
                  "paginas": 0, "erro": "",
                  "evidencia": f"Link de {e['social']}, não é o site da empresa."})
            continue
        d = e["dados"]
        if d is None:
            emit({"tipo": "resultado", "url": url, "classificacao": "Erro", "nota": "", "paginas": 0,
                  "evidencia": f"Não foi possível ler o site ({e['erro']}).", "erro": e["erro"]})
            continue

        sims = R @ d["doc_c"]
        nota = float(np.sort(sims)[::-1][:k].mean())
        if nota >= alto:
            categoria = "Entra no ICP"
        elif nota < baixo:
            categoria = "Não entra no ICP"
        else:
            categoria = "Revisar manualmente"

        emit({"tipo": "resultado", "url": url, "classificacao": categoria, "nota": f"{nota:.2f}",
              "paginas": d["paginas"], "erro": "",
              "evidencia": evidencia_trechos(d, mu, centroide, categoria == "Não entra no ICP")})

    emit({"tipo": "fim", "alto": round(alto, 2), "baixo": round(baixo, 2)})


# ---------------------------------------------------------------------------
# SERVIDOR HTTP
# ---------------------------------------------------------------------------

ARQUIVOS_ESTATICOS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        entrada = ARQUIVOS_ESTATICOS.get(self.path)
        if not entrada:
            self.send_error(404, "Não encontrado")
            return
        nome, content_type = entrada
        try:
            conteudo = (BASE_DIR / nome).read_bytes()
        except FileNotFoundError:
            self.send_error(404, "Arquivo não encontrado no servidor")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(conteudo)))
        self.end_headers()
        self.wfile.write(conteudo)

    def do_POST(self):
        if self.path != "/classificar_lote":
            self.send_error(404, "Não encontrado")
            return

        tamanho = int(self.headers.get("Content-Length", 0))
        try:
            dados = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            refs = [u.strip() for u in dados.get("referencias", []) if u.strip()]
            urls = [u.strip() for u in dados.get("urls", []) if u.strip()]
        except Exception:
            self.send_error(400, "Requisição inválida")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def emit(obj):
            self.wfile.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self.wfile.flush()

        try:
            classificar_lote(refs, urls, emit)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                emit({"tipo": "fatal", "msg": f"Erro inesperado: {e}"})
            except Exception:
                pass


def main():
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    url = f"http://127.0.0.1:{PORTA}/"
    print(f"Classificador de ICP rodando em {url}")
    print("Feche esta janela (ou Ctrl+C) para encerrar o servidor.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
