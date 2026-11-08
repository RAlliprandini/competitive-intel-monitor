# REVERSE.md — Mapa técnico para agentes de IA

> Leia ESTE arquivo antes de abrir o código. Ele descreve a arquitetura, os contratos e as regras do projeto
> para que alterações futuras possam ser feitas lendo apenas o(s) arquivo(s) necessário(s).
> **Mantenha-o atualizado** ao mudar contratos, arquivos ou fluxo.

## 1. Resumo (1 linha)
CLI Python que raspa páginas de concorrentes **configuráveis pelo usuário**, extrai sinais estratégicos por categoria de PM, calcula o diff contra o snapshot anterior e gera um **painel HTML interno navegável** (e/ou Markdown) com análise de IA local (Gemma via Ollama) ou motor heurístico estruturado.

## 2. Mapa de arquivos
| Arquivo | Responsabilidade | Depende de |
|---|---|---|
| `app.py` | Interface Web Local (`http://127.0.0.1:8765`, `http.server` da stdlib) para cadastrar URLs (individual/lote), ativar/pausar/excluir concorrentes, disparar o scraping e abrir qualquer versão HTML de `relatorios_html/` | `config_manager`, `monitor`, `ai_analyzer`, `reporting` |
| `config.json` | Concorrentes + parâmetros de IA, scraping e saída | — |
| `config_manager.py` | Defaults, load/merge/save do config, validação de URL, CRUD de concorrentes, wizard `--setup`, `--url` avulso | stdlib |
| `monitor.py` | CLI (argparse), scraping, snapshots (com histórico do último diff/análise), diff, orquestração | `requests`, `bs4`, `config_manager`, `ai_analyzer`, `reporting` |
| `ai_analyzer.py` | Taxonomia `STRATEGIC_CATEGORIES`, `classify_line`, `extract_strategic_signals` + backends `OllamaAnalyzer` e `HeuristicAnalyzer` | `requests` |
| `reporting.py` | `build_html` (dashboard interno single-file: sidebar, abas por concorrente, radar estratégico, diff viewer e explorador de linhas raspadas), `build_markdown` | `ai_analyzer` (`STRATEGIC_CATEGORIES`, `classify_line`) |
| `requirements.txt` | `requests`, `beautifulsoup4` (NÃO adicionar libs pesadas) | — |
| `snapshots/<slug>.json` | Estado entre execuções + última análise e último diff (gerado, gitignored) | — |
| `relatorios_html/<nome>_YYYY-MM-DD_HH-MM-SS.html` | Histórico de versões HTML geradas a cada execução (configurável em `output.reports_dir`, gitignored) | — |
| `relatorio_competitivo.html/.md` | Última versão gerada na raiz do projeto | — |

## 3. Fluxo de execução (`monitor.main`)
```
parse_args → cm.load_config (defaults mesclados; arquivo ausente = defaults)
  → manage(): se --setup/--add/--remove/--enable/--disable/--list → salva config, imprime lista, SAI (return 0)
  → select_competitors(): --url (avulso, não salva) | config ativo (enabled != false) | --only filtra
  → build_analyzer(cfg.ai, --no-ai)
  → para cada competitor: process_competitor()
       fetch_text(url, selector) → html_to_text()
       extract_strategic_signals(lines) → classifica linhas em STRATEGIC_CATEGORIES
       load_snapshot (se snapshot.url != url → trata como novo) → status:
         sem snapshot      → "Novo"         → analyzer.summarize()
         sha256 igual      → "Sem mudanças" → reaproveita last_analysis (ou gera summarize) + preserva last_added/last_removed
         sha256 diferente  → "Alterado"     → diff_lines() → analyzer.analyze_changes()
       save_snapshot (salva text, sha256, last_analysis, last_change_at, last_added, last_removed)
  → analyzer.executive_summary(results)
  → resolve_outputs() → build_html / build_markdown → --open abre o HTML
```

## 4. Contratos (não quebrar sem atualizar todos os consumidores)

**result dict** (produzido por `process_competitor`, consumido por `reporting.*` e `executive_summary`)
```python
{
  "name": str, "url": str, "selector": str|None,
  "status": "Novo"|"Alterado"|"Sem mudanças"|"Erro",
  "added": int, "removed": int,
  "added_lines": list[str], "removed_lines": list[str],
  "last_change_at": str|None, "last_added_lines": list[str], "last_removed_lines": list[str],
  "analysis": str (markdown), "previous_check": str|None, "fetched_at": str,
  "total_lines": int, "scraped_lines": list[str],
  "signals": {cat_key: {"label": str, "icon": str, "color": str, "count": int, "highlights": list[str]}}
}
```

**Taxonomia estratégica (`ai_analyzer.STRATEGIC_CATEGORIES`)**
Chaves: `ai`, `pricing`, `launch`, `ecosystem`, `enterprise`, `ux_mobile`. Usada tanto pelo `HeuristicAnalyzer` quanto pelas abas do `reporting.py`.

**Acoplamento prompt/heurístico ↔ HTML:** o selo de ameaça é extraído por regex (`reporting.THREAT_RE`) do trecho `"Nível de ameaça: Alto/Médio/Baixo"` gerado tanto por `OllamaAnalyzer` quanto por `HeuristicAnalyzer`.

## 5. Receitas de alteração (onde mexer)
| Quero… | Arquivo / símbolo |
|---|---|
| Nova categoria estratégica de scraping | `ai_analyzer.STRATEGIC_CATEGORIES` (propaga automaticamente para o HTML e Markdown) |
| Mudar prompts / formato da análise | `ai_analyzer.py` → `OllamaAnalyzer.*` / `HeuristicAnalyzer.*` |
| Layout, cores ou abas do painel HTML | `reporting.CSS`, `reporting.JS`, `reporting.PAGE`, `_build_competitor_view` |
| Adicionar/remover concorrente | CLI: `--add/--remove/--setup` ou `config.json` |
