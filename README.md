# ICP Classifier

<p align="center">
  <img src="https://github.com/user-attachments/assets/3eb887e5-3d83-4e0d-9844-f2b169d81d14" alt="Classificador de ICP" />
</p>

Ferramenta para classificar listas de sites de empresas de
acordo com o seu **ICP (Perfil de Cliente Ideal)**: você informa 5 sites
que representam o cliente ideal, cola uma lista de sites candidatos e a
ferramenta compara o conteúdo de cada um com os seus exemplos por
**similaridade**.

---

## O que a ferramenta faz

Para cada site a classificar, na ordem:

1. **Redes sociais** : links de Instagram, Facebook e LinkedIn são
   identificados e marcados como *Site não reconhecido*.
2. **Coleta da home** : baixa a página inicial com `requests`; se o
   texto vier quase vazio (site feito em JavaScript), renderiza com
   Chromium headless via Playwright.
3. **Páginas internas** : encontra até 5 páginas relevantes (serviços,
   soluções, segmentos, clientes, sobre...) a partir dos links da home e
   do `sitemap.xml`, evitando blog, política de privacidade, contato,
   login, etc.
4. **Limpeza do texto** : remove menus, rodapés, formulários, avisos de
   cookies e textos jurídicos; quebra o conteúdo em trechos de até ~280
   caracteres e descarta duplicados.
5. **Embeddings** : transforma cada trecho em vetor com um modelo
   multilíngue (`paraphrase-multilingual-MiniLM-L12-v2`).
6. **Centralização** : subtrai o vetor médio de "um site de empresa
   qualquer" (textos genéricos de vários setores), para que sobre só o
   que é específico de cada site.
7. **Similaridade** : compara o site com cada uma das 5 referências e
   calcula a nota pela média das 2 referências mais parecidas.
8. **Evidência** : mostra os trechos do site que mais se parecem com o
   seu ICP.

## Como os resultados são classificados

| Resultado | Significado |
|---|---|
| 🟢 **Alta** (Entra no ICP) | O conteúdo do site é muito parecido com o das suas referências. |
| 🟡 **Média** (Revisar manualmente) | Similaridade intermediária; vale uma olhada humana. |
| 🔴 **Baixa** (Não entra no ICP) | O conteúdo do site tem pouco ou nada em comum com o ICP. |
| ⚪ **Site não reconhecido** | O link é de rede social (Instagram, Facebook, LinkedIn), não do site da empresa. |

> Em caso de falha, o site aparece como **Erro** com o motivo.

---

## Pré-requisitos

- **Python 3.10+** instalado.
- **Internet na primeira execução**: o modelo de embeddings (~470 MB) é
  baixado uma única vez e depois fica em cache no computador.
- **Chromium do Playwright** (opcional, mas recomendado): permite ler
  sites que dependem de JavaScript. Sem ele, esses sites podem vir
  vazios.
- Sem necessidade de banco de dados, servidor externo ou conta em
  serviço de terceiros.

## Instalação

Abra a pasta do projeto no VS Code, abra o terminal integrado
(`` Ctrl+` ``) e rode:

```bash
# 1. Criar e ativar um ambiente virtual
python -m venv venv

# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# 2. Instalar as dependências
pip install -r requirements.txt

# 3. (Recomendado) Instalar o navegador usado para sites com JavaScript
playwright install chromium
```

## Como usar

1. Inicie o servidor:

   ```bash
   python server.py
   ```

   O navegador abre sozinho em **http://127.0.0.1:8765**.

2. Em **1) Sites de referência**, cole **exatamente 5 sites** que
   representam o seu ICP, um por linha.

3. (Opcional) Clique em **SALVAR PERFIL** para guardar essas 5
   referências com um nome e reutilizar depois pelo menu **Perfis
   salvos**.

4. Em **2) Sites a classificar**, cole as URLs que você quer analisar,
   uma por linha.

5. Clique em **INICIAR CLASSIFICAÇÃO**.

6. Acompanhe a barra de progresso e a tabela sendo preenchida em tempo
   real, com a classificação e a evidência de cada site. Dê **duplo
   clique** em uma linha para abrir o site em outra aba.

7. Clique em **SALVAR CSV** para baixar o resultado
   (`resultado_icp.csv`, com URL, classificação, nota, páginas lidas,
   evidência e erro).

Para parar o servidor, volte ao terminal e pressione `Ctrl+C`.

## Perfis de ICP

Os perfis ficam salvos **no próprio navegador** (`localStorage`), não em
arquivos nem em servidores. Isso significa que:

- cada perfil guarda as 5 referências e é listado com o nome e a
  quantidade de sites;
- o último perfil usado é carregado automaticamente ao abrir a
  ferramenta;
- trocar de navegador ou limpar os dados do site apaga os perfis.

## Volume e desempenho

- A leitura é **sequencial**, com pequena pausa aleatória (0,3 a 0,8 s)
  entre os sites, para não sobrecarregar os servidores.
- Por site: a home + até **5 páginas internas**, com no máximo 2 páginas
  por categoria (serviços, clientes, sobre...).
- **Timeout** de 15 segundos por requisição.
- A primeira execução é mais lenta por causa do download do modelo; nas
  seguintes ele já está em cache.

Os valores abaixo ficam centralizados na seção `CONFIGURAÇÃO` do topo de
`server.py`, caso queira ajustar:

| Constante | O que controla |
|---|---|
| `MODELO` | Modelo de embeddings usado. |
| `TOP_K` | Quantas referências mais parecidas entram na média da nota. |
| `FATOR_ALTO` / `FATOR_BAIXO` | Sensibilidade dos limites de Alta e Baixa. |
| `MAX_PAGINAS` | Páginas internas lidas além da home. |
| `MIN_TEXTO_JS` | Texto mínimo da home antes de recorrer ao Playwright. |
| `CHUNKS_HOME` / `CHUNKS_PAGINA` | Máximo de trechos por página. |
| `TIMEOUT` | Tempo limite das requisições (segundos). |
| `PAGINAS_PESO` / `EVITAR` | Quais páginas internas são priorizadas ou ignoradas. |
| `PORTA` | Porta do servidor local. |

## Limitações importantes

- A classificação é por **similaridade de conteúdo**, não por regras de
  negócio: ela mostra o quanto o site *se parece* com as suas
  referências. A qualidade do resultado depende da qualidade das 5
  referências, então escolha exemplos que realmente representem o seu
  cliente ideal.
- Sem o Playwright instalado, sites feitos com JavaScript podem vir
  vazios e ser mal classificados.
- Links de redes sociais não são analisados, pois não representam o
  site da empresa.
- Exige **exatamente 5 referências** e pelo menos 2 delas precisam
  carregar corretamente para a rodada acontecer.
- A categoria **Revisar manualmente** existe de propósito: nela, a
  decisão final deve ser humana.

## Demonstração
<p align="center">
  <a href="https://github.com/ingrydbacelar/icp-classifier">
    <img src="https://img.shields.io/badge/Acessar%20ICP%20Classifier-14532D?style=for-the-badge&logoColor=white" alt="Acessar ICP Classifier">
  </a>
</p>

## Autora
Ingryd Bacelar

> © 2026 Ingryd Bacelar. Todos os direitos reservados.

> Este projeto é disponibilizado exclusivamente para fins de demonstração e portfólio. É proibida a reprodução, cópia, modificação, distribuição ou utilização comercial do código sem autorização prévia da autora.
