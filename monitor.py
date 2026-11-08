#!/usr/bin/env python3
"""
monitor.py — Monitor de Inteligência Competitiva com IA local.

Pipeline:
  1. Carrega os concorrentes (config.json, gerenciável via CLI, ou URLs avulsas via --url)
  2. Baixa e limpa o conteúdo textual de cada página (requests + BeautifulSoup)
  3. Extrai sinais estratégicos do conteúdo raspado (IA, Preço, Lançamentos, API, Enterprise, Mobile)
  4. Compara com o snapshot anterior (diff por linhas) e preserva o histórico da última mudança
  5. Envia novidades/diferenças para a IA local (Gemma via Ollama) ou motor heurístico estruturado
  6. Gera o painel HTML navegável (padrão) e/ou Markdown

Uso rápido:
  python monitor.py                                   # roda e gera relatorio_competitivo.html
  python monitor.py --open                            # ...e abre o painel no navegador
  python monitor.py --setup                           # assistente para cadastrar concorrentes
  python monitor.py --add https://site.com/changelog --name Site --selector main
  python monitor.py --list | --remove Site | --disable Site | --enable Site
  python monitor.py --url https://a.com/blog --url b.com/pricing   # avulso, sem salvar
  python monitor.py --format both --no-ai
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import unicodedata
import webbrowser
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import config_manager as cm
from ai_analyzer import build_analyzer, extract_strategic_signals
from reporting import build_html, build_markdown

# Funciona tanto como script quanto como executável PyInstaller (--onefile)
BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

log = logging.getLogger("monitor")

NOISE_TAGS = ["script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe", "aside"]
FORMAT_EXT = {"html": ".html", "md": ".md"}


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "competitor"


# --------------------------------------------------------------------------------------
# Coleta (scraping)
# --------------------------------------------------------------------------------------
def html_to_text(html: str, selector: str | None, min_len: int = 25) -> str:
    """Extrai apenas o texto relevante do HTML, uma ideia por linha, sem duplicatas."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()

    root = (soup.select_one(selector) if selector else None) or soup.body or soup
    raw = root.get_text(separator="\n")

    seen, lines = set(), []
    for line in raw.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if len(clean) >= min_len and clean not in seen:
            seen.add(clean)
            lines.append(clean)
    return "\n".join(lines)


def fetch_text(url: str, selector: str | None, scraping_cfg: dict) -> str:
    """Baixa a página e devolve o texto limpo."""
    headers = {"User-Agent": scraping_cfg.get("user_agent", "Mozilla/5.0"),
               "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}
    resp = requests.get(url, headers=headers, timeout=scraping_cfg.get("timeout_seconds", 20))
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return html_to_text(resp.text, selector, scraping_cfg.get("min_line_length", 25))


# --------------------------------------------------------------------------------------
# Snapshots & diff
# --------------------------------------------------------------------------------------
def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_snapshot(path: Path) -> dict | None:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("Snapshot corrompido ignorado: %s", path)
    return None


def save_snapshot(
    path: Path,
    url: str,
    text: str,
    *,
    last_analysis: str = "",
    last_change_at: str | None = None,
    last_added: list[str] | None = None,
    last_removed: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "url": url,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "sha256": sha256(text),
        "text": text,
        "last_analysis": last_analysis,
        "last_change_at": last_change_at,
        "last_added": (last_added or [])[:150],
        "last_removed": (last_removed or [])[:150],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def diff_lines(old: str, new: str) -> tuple[list[str], list[str]]:
    """Diff por conjunto de linhas (robusto a reordenação de blocos na página)."""
    old_lines, new_lines = old.splitlines(), new.splitlines()
    old_set, new_set = set(old_lines), set(new_lines)
    added = [l for l in new_lines if l not in old_set]
    removed = [l for l in old_lines if l not in new_set]
    return added, removed


# --------------------------------------------------------------------------------------
# Processamento por concorrente
# --------------------------------------------------------------------------------------
def process_competitor(comp: dict, cfg: dict, analyzer, snapshots_dir: Path) -> dict:
    name, url = comp["name"], comp["url"]
    now_iso = datetime.now().isoformat(timespec="seconds")
    result = {
        "name": name,
        "url": url,
        "selector": comp.get("selector"),
        "status": "",
        "added": 0,
        "removed": 0,
        "added_lines": [],
        "removed_lines": [],
        "last_change_at": None,
        "last_added_lines": [],
        "last_removed_lines": [],
        "analysis": "",
        "previous_check": None,
        "fetched_at": now_iso,
        "total_lines": 0,
        "scraped_lines": [],
        "signals": {},
    }
    snap_path = snapshots_dir / f"{slugify(name)}.json"

    log.info("→ %s (%s)", name, url)
    try:
        text = fetch_text(url, comp.get("selector"), cfg.get("scraping", {}))
    except requests.RequestException as exc:
        log.error("   Falha ao coletar: %s", exc)
        result.update(status="Erro", analysis=f"⚠️ Não foi possível coletar a página: `{exc}`")
        return result

    if not text:
        result.update(status="Erro", analysis="⚠️ Página sem conteúdo textual (pode exigir JavaScript).")
        return result

    lines = text.splitlines()
    result["total_lines"] = len(lines)
    result["scraped_lines"] = lines
    result["signals"] = extract_strategic_signals(lines)

    previous = load_snapshot(snap_path)
    if previous and previous.get("url") != url:
        log.info("   URL mudou desde o último snapshot — reiniciando linha de base.")
        previous = None

    last_change_at = previous.get("last_change_at") if previous else None
    last_added = previous.get("last_added", []) if previous else []
    last_removed = previous.get("last_removed", []) if previous else []

    try:
        if previous is None:
            result["status"] = "Novo"
            log.info("   Primeira coleta (%d linhas) — gerando análise estratégica de linha de base…", len(lines))
            result["analysis"] = analyzer.summarize(name, url, text)
            last_change_at = now_iso
        elif previous.get("sha256") == sha256(text):
            prev_analysis = previous.get("last_analysis") or analyzer.summarize(name, url, text)
            result.update(
                status="Sem mudanças",
                previous_check=previous.get("fetched_at"),
                analysis=prev_analysis,
                last_change_at=last_change_at,
                last_added_lines=last_added,
                last_removed_lines=last_removed,
            )
            log.info("   Sem mudanças desde %s (%d linhas monitoradas)", previous.get("fetched_at"), len(lines))
        else:
            added, removed = diff_lines(previous.get("text", ""), text)
            last_change_at = now_iso
            last_added, last_removed = added, removed
            result.update(
                status="Alterado",
                added=len(added),
                removed=len(removed),
                added_lines=added,
                removed_lines=removed,
                last_change_at=last_change_at,
                last_added_lines=added,
                last_removed_lines=removed,
                previous_check=previous.get("fetched_at"),
            )
            log.info("   Mudanças: +%d / -%d linhas — analisando impacto estratégico…", len(added), len(removed))
            result["analysis"] = analyzer.analyze_changes(name, url, added, removed)
    except requests.RequestException as exc:
        log.error("   Falha na IA local: %s", exc)
        result["analysis"] = f"⚠️ Erro ao consultar a IA local: `{exc}`"
        return result  # não salva snapshot: a mudança será reanalisada na próxima execução

    save_snapshot(
        snap_path,
        url,
        text,
        last_analysis=result["analysis"],
        last_change_at=last_change_at,
        last_added=last_added,
        last_removed=last_removed,
    )
    return result


# --------------------------------------------------------------------------------------
# Saída
# --------------------------------------------------------------------------------------
def resolve_outputs(args: argparse.Namespace, out_cfg: dict) -> list[tuple[str, Path]]:
    """Define [(formato, caminho)] a partir de --output/--format/config."""
    fmt = args.format or out_cfg.get("format", "html")
    base = Path(args.output) if args.output else BASE_DIR / out_cfg.get("report_file", "relatorio_competitivo")
    if base.suffix.lower() in (".html", ".htm", ".md"):
        if not args.format:  # extensão em --output define o formato
            fmt = "md" if base.suffix.lower() == ".md" else "html"
        base = base.with_suffix("")
    formats = ["html", "md"] if fmt == "both" else [fmt]
    return [(f, base.with_suffix(FORMAT_EXT[f])) for f in formats]


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Monitor de Inteligência Competitiva com IA local.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exemplos:\n"
               "  python monitor.py --add https://linear.app/changelog --selector main\n"
               "  python monitor.py --url https://site.com/blog --open\n"
               "  python monitor.py --setup")
    run = p.add_argument_group("execução")
    run.add_argument("--config", default=str(BASE_DIR / "config.json"), help="Caminho do config.json")
    run.add_argument("--url", action="append", metavar="URL",
                     help="Monitora esta URL (repetível) em vez da lista do config, sem salvar")
    run.add_argument("--only", action="append", metavar="NOME", help="Roda apenas estes concorrentes (repetível)")
    run.add_argument("--format", choices=["html", "md", "both"], help="Formato do relatório (padrão: html)")
    run.add_argument("--output", help="Caminho do relatório (a extensão define o formato)")
    run.add_argument("--open", action="store_true", help="Abre o relatório HTML no navegador ao final")
    run.add_argument("--ui", action="store_true", help="Abre a interface web local para gerenciar URLs e rodar o scraping")
    run.add_argument("--no-ai", action="store_true", help="Força o modo heurístico (sem LLM)")
    run.add_argument("-v", "--verbose", action="store_true", help="Logs detalhados")

    mg = p.add_argument_group("gestão de concorrentes (salva no config.json e sai)")
    mg.add_argument("--list", action="store_true", help="Lista os concorrentes configurados")
    mg.add_argument("--add", metavar="URL", help="Adiciona um concorrente")
    mg.add_argument("--name", help="Nome para --add (padrão: derivado do domínio)")
    mg.add_argument("--selector", help="Seletor CSS para --add (ex.: main, article, #changelog)")
    mg.add_argument("--remove", metavar="NOME", help="Remove um concorrente")
    mg.add_argument("--enable", metavar="NOME", help="Reativa um concorrente")
    mg.add_argument("--disable", metavar="NOME", help="Pausa um concorrente sem removê-lo")
    mg.add_argument("--setup", action="store_true", help="Assistente interativo de cadastro")
    return p.parse_args()


def manage(args: argparse.Namespace, cfg: dict, config_path: Path) -> bool:
    """Executa comandos de gestão. Retorna True se algum foi executado (e o programa deve sair)."""
    changed, handled = False, False
    if args.setup:
        cm.interactive_setup(cfg)
        changed = handled = True
    if args.add:
        comp = cm.add_competitor(cfg, args.add, args.name, args.selector)
        print(f"✅ Adicionado: {comp['name']} → {comp['url']}")
        changed = handled = True
    if args.remove:
        print(f"🗑️  Removido: {cm.remove_competitor(cfg, args.remove)['name']}")
        changed = handled = True
    if args.enable:
        print(f"▶️  Ativado: {cm.set_enabled(cfg, args.enable, True)['name']}")
        changed = handled = True
    if args.disable:
        print(f"⏸️  Pausado: {cm.set_enabled(cfg, args.disable, False)['name']}")
        changed = handled = True
    if changed:
        cm.save_config(config_path, cfg)
        print(f"💾 Config salvo em {config_path}\n")
    if args.list or changed:
        print(cm.format_list(cfg))
        handled = True
    return handled


def select_competitors(args: argparse.Namespace, cfg: dict, config_path: Path) -> list[dict]:
    if args.url:
        return cm.adhoc_competitors(args.url)

    if not cfg["competitors"]:
        if cm.can_prompt():
            print("Nenhum concorrente configurado ainda.")
            cm.interactive_setup(cfg)
            cm.save_config(config_path, cfg)
        if not cfg["competitors"]:
            raise cm.ConfigError("Nenhum concorrente configurado. Use --setup, --add <url> ou --url <url>.")

    comps = cm.active_competitors(cfg)
    if args.only:
        wanted = {n.lower() for n in args.only}
        comps = [c for c in cfg["competitors"] if c["name"].lower() in wanted]
        missing = wanted - {c["name"].lower() for c in comps}
        if missing:
            raise cm.ConfigError(f"Concorrente(s) não encontrado(s): {', '.join(sorted(missing))}")
    if not comps:
        raise cm.ConfigError("Todos os concorrentes estão pausados. Use --enable <nome>.")
    return comps


def main() -> int:
    # Garante emojis/acentos no console do Windows
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s")
    if args.ui:
        import app as web_ui
        web_ui.start_ui(open_browser=True)
        return 0
    config_path = Path(args.config)

    try:
        cfg = cm.load_config(config_path)
        if manage(args, cfg, config_path):
            return 0
        competitors = select_competitors(args, cfg, config_path)
    except cm.ConfigError as exc:
        log.error("[ERRO] %s", exc)
        return 2

    snapshots_dir = BASE_DIR / cfg["output"].get("snapshots_dir", "snapshots")
    analyzer = build_analyzer(cfg.get("ai", {}), force_heuristic=args.no_ai)
    log.info("🤖 Motor de análise: %s\n", analyzer.label)

    results = [process_competitor(c, cfg, analyzer, snapshots_dir) for c in competitors]

    log.info("\n🧭 Gerando resumo executivo…")
    try:
        executive = analyzer.executive_summary(results)
    except requests.RequestException as exc:
        executive = f"⚠️ Não foi possível gerar o resumo executivo: `{exc}`"

    builders = {"html": build_html, "md": build_markdown}
    reports_dir = BASE_DIR / cfg["output"].get("reports_dir", "relatorios_html")
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    for fmt, path in resolve_outputs(args, cfg["output"]):
        content = builders[fmt](results, executive, analyzer.label)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log.info("✅ Relatório %s atual salvo em: %s", fmt.upper(), path)

        if fmt == "html":
            reports_dir.mkdir(parents=True, exist_ok=True)
            version_filename = f"{path.stem}_{stamp}.html"
            versioned_path = reports_dir / version_filename
            versioned_path.write_text(content, encoding="utf-8")
            meta = {
                "filename": version_filename,
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "engine": analyzer.label,
                "total": len(results),
                "changed": sum(1 for r in results if r["status"] == "Alterado"),
                "new": sum(1 for r in results if r["status"] == "Novo"),
                "same": sum(1 for r in results if r["status"] == "Sem mudanças"),
                "errors": sum(1 for r in results if r["status"] == "Erro"),
                "competitors": [r["name"] for r in results],
            }
            (reports_dir / f"{path.stem}_{stamp}.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log.info("🗂️  Versão histórica salva em: %s", versioned_path)
            if args.open:
                webbrowser.open(versioned_path.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
