# 📊 Competitive Intel Monitor

Monitor de **inteligência competitiva** com **IA 100% local**. Ele coleta as páginas dos concorrentes que **você escolhe** (changelogs, preços, blogs), identifica exatamente o que mudou entre execuções e gera um **painel HTML interno e navegável** com os sinais estratégicos extraídos do web scraping.

> Projeto de portfólio · **AI & Data Product Management**

## ✨ O que o painel HTML entrega para o PM

O arquivo `relatorio_competitivo.html` é uma aplicação single-file (100% offline, para uso interno) com:

- **Sidebar de navegação:** alterne entre a **Visão Executiva & Radar** e o painel individual de cada concorrente.
- **Status claro de mudança:** banner em cada concorrente indicando **se teve mudança ou não**, quando foi a verificação anterior e quantas linhas foram adicionadas (`+`) ou removidas (`−`).
- **3 abas navegáveis por concorrente:**
  1. **🎯 Inteligência Estratégica:** leitura estratégica + cards temáticos com os trechos reais extraídos do scraping (*IA & Agentes*, *Preço & Monetização*, *Lançamentos & Produto*, *Ecossistema & API*, *Enterprise & Segurança* e *Mobile & Performance*).
  2. **🔄 Mudanças / Diff:** lista exata das linhas adicionadas (`+`) e removidas (`−`) na página (ou o histórico da última alteração registrada), com filtro rápido.
  3. **📄 Conteúdo Coletado:** todas as frases raspadas da página com busca instantânea em tempo real e filtro por categoria estratégica.
- **Radar competitivo cruzado:** compara os movimentos de todos os concorrentes lado a lado por tema estratégico.

## 🚀 Como rodar

```bash
pip install -r requirements.txt
python app.py
```
Isso sobe a **Central Web de Inteligência Competitiva** (`http://127.0.0.1:8765`) e abre no seu navegador:
- Adicione URLs individualmente ou cole uma lista inteira de URLs de uma vez (lote).
- Ative, pause ou exclua concorrentes com 1 clique.
- Clique em **🚀 Rodar Web Scraping Agora** (ou **▶ Raspar só este**) para disparar a coleta e abrir automaticamente o novo painel HTML.
- Veja e abra qualquer versão anterior salva em `relatorios_html/`.

Se preferir rodar direto via terminal sem a central:
```bash
python monitor.py --open
```

**(Opcional) Ative o LLM local (Google Gemma 3 via Ollama):**
1. Instale o [Ollama](https://ollama.com/download)
2. Baixe o modelo: `ollama pull gemma3:4b`

> Sem o Ollama o projeto **funciona integralmente**: o motor heurístico classifica todas as linhas raspadas nas 6 categorias estratégicas de PM, calcula o nível de ameaça e monta o painel completo.

## 🏢 Escolha seus concorrentes (100% configurável)

Os concorrentes **não são fixos no código**. Gerencie a lista pelo terminal ou editando o `config.json`:

```bash
python monitor.py --setup                                   # assistente interativo
python monitor.py --add https://site.com/changelog          # nome derivado do domínio
python monitor.py --add https://x.com/pricing --name "X" --selector main
python monitor.py --list                                    # ✔ ativos / ✖ pausados
python monitor.py --disable X    |  --enable X  |  --remove X
python monitor.py --only Linear --only Notion               # roda só alguns
python monitor.py --url https://a.com/blog --url b.com      # avulso, sem salvar no config
```

## ⚙️ Outras opções

```bash
python monitor.py --format md|html|both     # padrão: html
python monitor.py --output relatorios/painel.html
python monitor.py --no-ai -v                # força motor heurístico, logs detalhados
```

## 🏗️ Arquitetura

```
config.json ◄─► config_manager.py   (CLI: --add/--remove/--setup/--url)
                      │
                 monitor.py ──► scraping (requests + BeautifulSoup) ──► snapshots/*.json (diff + histórico)
                      │
                      ├──► ai_analyzer.py ──► Sinais Estratégicos + Gemma 3 local (Ollama) / Heurístico
                      │
                      └──► reporting.py   ──► relatorio_competitivo.html (Painel navegável) + .md opcional
```

## 📦 Executável standalone (opcional)

```bash
pip install pyinstaller
pyinstaller --onefile --name competitive-monitor monitor.py
```

## 🤖 Para agentes de IA
Antes de alterar o código, leia o [REVERSE.md](REVERSE.md): arquitetura, contratos e receitas de alteração.
