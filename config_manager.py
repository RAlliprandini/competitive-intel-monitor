"""
config_manager.py — Leitura, escrita e gestão da lista de concorrentes.

A lista de concorrentes NÃO é fixa no código: fica em `config.json` e pode ser gerenciada por
CLI (--add/--remove/--enable/--disable/--list), por assistente interativo (--setup) ou
sobrescrita em tempo de execução com URLs avulsas (--url).
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_CONFIG: dict = {
    "competitors": [],
    "ai": {
        "backend": "ollama",
        "model": "gemma3:4b",
        "host": "http://localhost:11434",
        "temperature": 0.2,
        "timeout_seconds": 180,
        "max_input_chars": 12000,
    },
    "scraping": {
        "timeout_seconds": 20,
        "min_line_length": 8,
        "user_agent": "Mozilla/5.0 (compatible; CompetitiveIntelMonitor/1.0; +https://github.com/)",
    },
    "output": {
        "format": "html",
        "report_file": "relatorio_competitivo",
        "reports_dir": "relatorios_html",
        "snapshots_dir": "snapshots",
    },
}


class ConfigError(Exception):
    pass


# --------------------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------------------
def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: Path) -> dict:
    """Carrega o config mesclado com os defaults. Se não existir, retorna os defaults."""
    if not path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        user_cfg = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config.json inválido ({path}): {exc}") from exc
    cfg = _deep_merge(DEFAULT_CONFIG, user_cfg)
    for c in cfg["competitors"]:
        if not c.get("name") or not c.get("url"):
            raise ConfigError(f"Concorrente sem 'name' ou 'url' em {path}: {c}")
    return cfg


def save_config(path: Path, cfg: dict) -> None:
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def normalize_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc or "." not in parsed.netloc:
        raise ConfigError(f"URL inválida: {url}")
    return url


def name_from_url(url: str) -> str:
    """'https://www.notion.com/releases' -> 'Notion'"""
    host = urlparse(url).netloc.lower().split(":")[0]
    parts = [p for p in host.split(".") if p not in ("www", "app", "blog", "docs")]
    core = parts[-2] if len(parts) >= 2 else (parts[0] if parts else host)
    return core.capitalize()


def find(cfg: dict, name: str) -> dict | None:
    return next((c for c in cfg["competitors"] if c["name"].lower() == name.lower()), None)


def active_competitors(cfg: dict) -> list[dict]:
    return [c for c in cfg["competitors"] if c.get("enabled", True)]


def adhoc_competitors(urls: list[str]) -> list[dict]:
    """Concorrentes passados via --url (não são salvos no config)."""
    out = []
    for u in urls:
        url = normalize_url(u)
        out.append({"name": name_from_url(url), "url": url, "selector": None, "enabled": True})
    return out


# --------------------------------------------------------------------------------------
# Operações de gestão (CLI)
# --------------------------------------------------------------------------------------
def add_competitor(cfg: dict, url: str, name: str | None = None, selector: str | None = None) -> dict:
    url = normalize_url(url)
    name = (name or name_from_url(url)).strip()
    if find(cfg, name):
        raise ConfigError(f"Já existe um concorrente chamado '{name}'. Use outro --name.")
    comp = {"name": name, "url": url, "selector": selector or None, "enabled": True}
    cfg["competitors"].append(comp)
    return comp


def remove_competitor(cfg: dict, name: str) -> dict:
    comp = find(cfg, name)
    if not comp:
        raise ConfigError(f"Concorrente '{name}' não encontrado. Veja: --list")
    cfg["competitors"].remove(comp)
    return comp


def set_enabled(cfg: dict, name: str, enabled: bool) -> dict:
    comp = find(cfg, name)
    if not comp:
        raise ConfigError(f"Concorrente '{name}' não encontrado. Veja: --list")
    comp["enabled"] = enabled
    return comp


def format_list(cfg: dict) -> str:
    comps = cfg["competitors"]
    if not comps:
        return "Nenhum concorrente configurado. Use --add <url> ou --setup."
    w = max(len(c["name"]) for c in comps)
    lines = [f"{'':2} {'NOME':<{w}}  URL"]
    for c in comps:
        mark = "✔" if c.get("enabled", True) else "✖"
        sel = f"  [selector: {c['selector']}]" if c.get("selector") else ""
        lines.append(f"{mark:2} {c['name']:<{w}}  {c['url']}{sel}")
    lines.append(f"\n{len(active_competitors(cfg))} ativo(s) de {len(comps)}.")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Assistente interativo
# --------------------------------------------------------------------------------------
def interactive_setup(cfg: dict) -> dict:
    """Wizard no terminal para cadastrar concorrentes. Retorna o cfg modificado."""
    print("\n🛠️  Configuração de concorrentes (Enter vazio na URL para finalizar)\n")
    if cfg["competitors"]:
        print(format_list(cfg), "\n")
        if input("Manter os concorrentes atuais? [S/n] ").strip().lower() in ("n", "nao", "não"):
            cfg["competitors"] = []
    while True:
        url = input("URL do concorrente: ").strip()
        if not url:
            break
        try:
            suggested = name_from_url(normalize_url(url))
            name = input(f"  Nome [{suggested}]: ").strip() or suggested
            selector = input("  Seletor CSS opcional (ex.: main) [vazio = página inteira]: ").strip() or None
            comp = add_competitor(cfg, url, name, selector)
            print(f"  ✅ {comp['name']} adicionado.\n")
        except ConfigError as exc:
            print(f"  ❌ {exc}\n")
    return cfg


def can_prompt() -> bool:
    return sys.stdin is not None and sys.stdin.isatty()

