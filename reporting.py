"""
reporting.py — Painel HTML navegável de Inteligência Competitiva (uso interno, 100% offline)
e exportação opcional em Markdown.

  * build_html(...)     -> Dashboard interativo single-file (sidebar, abas por concorrente,
                           status de mudança, diff de linhas, sinais estratégicos do scraping
                           e explorador pesquisável de todo o conteúdo coletado)
  * build_markdown(...) -> Relatório em Markdown limpo
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime
from string import Template
from urllib.parse import urlparse

from ai_analyzer import STRATEGIC_CATEGORIES, classify_line

STATUS_META = {
    "Alterado":     {"icon": "🔄", "css": "changed", "desc": "Mudança detectada nesta coleta"},
    "Novo":         {"icon": "🆕", "css": "new",     "desc": "Primeira coleta (linha de base criada)"},
    "Sem mudanças": {"icon": "✅", "css": "same",    "desc": "Sem alterações desde a última verificação"},
    "Erro":         {"icon": "⚠️", "css": "error",   "desc": "Falha ao coletar a página"},
}
STATUS_ORDER = ["Alterado", "Novo", "Sem mudanças", "Erro"]
THREAT_RE = re.compile(r"n[íi]vel de amea[çc]a\W*(alto|m[ée]dio|baixo)", re.IGNORECASE)
THREAT_RANK = {"Alto": 0, "Médio": 1, "Baixo": 2, None: 3}
AVATAR_COLORS = ["#4f46e5", "#0ea5e9", "#db2777", "#059669", "#d97706", "#7c3aed", "#dc2626", "#0d9488"]


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def extract_threat(text: str) -> str | None:
    """Lê o 'Nível de ameaça' presente na análise (Alto/Médio/Baixo)."""
    m = THREAT_RE.search(text or "")
    if not m:
        return None
    v = m.group(1).lower()
    return "Alto" if v == "alto" else "Baixo" if v == "baixo" else "Médio"


def fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def _slug_id(name: str, idx: int) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"comp-{s or idx}"


def _inline(text: str) -> str:
    """Escapa HTML e aplica formatação inline: `code`, **negrito**, *itálico*, links."""
    t = html.escape(text, quote=False)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)
    t = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    t = re.sub(r"&lt;(https?://[^&\s]+)&gt;", r'<a href="\1" target="_blank" rel="noopener">\1</a>', t)
    return t


def md_to_html(md: str) -> str:
    """Conversor Markdown→HTML mínimo com suporte a sub-bullets aninhados em listas numeradas."""
    out: list[str] = []
    stack: list[str] = []

    def close_all() -> None:
        while stack:
            out.append(f"</li></{stack.pop()}>")

    for raw in (md or "").strip().splitlines():
        line = raw.rstrip()
        m_ul = re.match(r"^\s*[-*+]\s+(.*)", line)
        m_ol = re.match(r"^\s*\d+[.)]\s+(.*)", line)
        if m_ol:
            if stack[-1:] == ["ul"]:
                out.append("</li></ul>")
                stack.pop()
            if stack == ["ol"]:
                out.append("</li>")
            else:
                close_all()
                out.append("<ol>")
                stack.append("ol")
            out.append(f"<li>{_inline(m_ol.group(1))}")
            continue
        if m_ul:
            if stack[-1:] == ["ul"]:
                out.append("</li>")
            else:
                out.append("<ul>")
                stack.append("ul")
            out.append(f"<li>{_inline(m_ul.group(1))}")
            continue
        if not line.strip():
            continue
        close_all()
        m_h = re.match(r"^(#{1,6})\s+(.*)", line)
        if m_h:
            out.append(f"<h4>{_inline(m_h.group(2))}</h4>")
        elif re.fullmatch(r"\s*[-*_]{3,}\s*", line):
            out.append("<hr>")
        else:
            out.append(f"<p>{_inline(line)}</p>")
    close_all()
    return "\n".join(out)


def _avatar(name: str) -> tuple[str, str]:
    initials = "".join(w[0] for w in re.findall(r"[A-Za-zÀ-ÿ0-9]+", name)[:2]).upper() or "?"
    color = AVATAR_COLORS[int(hashlib.md5(name.encode()).hexdigest(), 16) % len(AVATAR_COLORS)]
    return initials, color


def _badge(status: str) -> str:
    meta = STATUS_META.get(status, {"icon": "", "css": "same"})
    return f'<span class="badge {meta["css"]}">{meta["icon"]} {html.escape(status)}</span>'


def _threat_badge(threat: str | None) -> str:
    if not threat:
        return '<span class="badge t-none">—</span>'
    css, label = {"Alto": ("t-alto", "Ameaça alta"),
                  "Médio": ("t-medio", "Ameaça média"),
                  "Baixo": ("t-baixo", "Ameaça baixa")}[threat]
    return f'<span class="badge {css}">{label}</span>'


# --------------------------------------------------------------------------------------
# Estilos e Scripts do Painel Interativo (100% inline / offline)
# --------------------------------------------------------------------------------------
CSS = """
:root{
  --bg:#f1f5f9;--surface:#ffffff;--surface-2:#f8fafc;--sidebar:#0f172a;--sidebar-hover:#1e293b;
  --ink:#0f172a;--ink-2:#334155;--muted:#64748b;--line:#e2e8f0;--brand:#4f46e5;--brand-soft:#eef2ff;
  --new:#2563eb;--changed:#d97706;--same:#16a34a;--error:#dc2626;--radius:14px;
  --shadow:0 1px 3px rgba(15,23,42,.06),0 6px 20px rgba(15,23,42,.05);
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;font-family:Inter,"Segoe UI",system-ui,-apple-system,Roboto,sans-serif;
background:var(--bg);color:var(--ink);line-height:1.5;-webkit-font-smoothing:antialiased}
a{color:var(--brand);text-decoration:none}a:hover{text-decoration:underline}

/* Layout App */
.app{display:grid;grid-template-columns:280px 1fr;min-height:100vh}
.sidebar{background:var(--sidebar);color:#e2e8f0;padding:22px 16px;display:flex;flex-direction:column;
gap:18px;position:sticky;top:0;height:100vh;overflow-y:auto;border-right:1px solid #1e293b}
.brand{display:flex;align-items:center;gap:12px;padding:4px 8px}
.brand-logo{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,#6366f1,#0ea5e9);
display:grid;place-items:center;font-size:19px;font-weight:800;color:#fff;flex-shrink:0}
.brand-txt strong{display:block;font-size:15px;color:#fff;letter-spacing:-.01em}
.brand-txt span{font-size:11.5px;color:#94a3b8}

.side-group-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:#64748b;
font-weight:700;padding:4px 10px;margin-top:4px}
.nav-list{display:flex;flex-direction:column;gap:4px}
.nav-btn{width:100%;border:0;background:transparent;color:#cbd5e1;padding:10px 12px;border-radius:10px;
display:flex;align-items:center;gap:10px;font-family:inherit;font-size:13.5px;font-weight:500;
cursor:pointer;text-align:left;transition:background .15s,color .15s}
.nav-btn:hover{background:var(--sidebar-hover);color:#fff}
.nav-btn.active{background:var(--brand);color:#fff;font-weight:600;box-shadow:0 4px 12px rgba(79,70,229,.35)}
.nav-btn .nav-name{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.nav-dot{width:8px;height:8px;border-radius:999px;flex-shrink:0}
.dot-changed{background:#f59e0b;box-shadow:0 0 0 3px rgba(245,158,11,.25)}
.dot-new{background:#3b82f6}
.dot-same{background:#22c55e}
.dot-error{background:#ef4444}
.nav-pill{font-size:11px;padding:1px 7px;border-radius:999px;background:rgba(255,255,255,.12);color:#e2e8f0}

.side-meta{margin-top:auto;padding:12px;border-radius:10px;background:#1e293b;font-size:12px;color:#94a3b8;line-height:1.45}
.side-meta div{margin:3px 0}
.side-meta strong{color:#e2e8f0}

/* Topbar & Main */
.content{display:flex;flex-direction:column;min-width:0}
.topbar{background:var(--surface);border-bottom:1px solid var(--line);padding:14px 28px;
display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;position:sticky;top:0;z-index:10}
.topbar-title{display:flex;align-items:center;gap:12px}
.topbar-title h1{font-size:18px;margin:0;letter-spacing:-.01em}
.internal-tag{background:#0f172a;color:#e2e8f0;font-size:11px;font-weight:600;padding:3px 9px;
border-radius:6px;letter-spacing:.04em;text-transform:uppercase}
.top-search{display:flex;align-items:center;gap:8px;background:var(--surface-2);border:1px solid var(--line);
padding:7px 12px;border-radius:10px;min-width:280px}
.top-search input{border:0;background:transparent;outline:none;font-size:13.5px;width:100%;color:var(--ink);font-family:inherit}

.main-inner{padding:26px 28px 48px;max-width:1380px;width:100%}
.view-panel{display:none}
.view-panel.active{display:block}

/* KPIs */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:14px;margin-bottom:22px}
.kpi{background:var(--surface);border-radius:var(--radius);padding:16px 18px;box-shadow:var(--shadow);
border-top:4px solid var(--c,var(--brand))}
.kpi .v{font-size:28px;font-weight:800;letter-spacing:-.02em;line-height:1.15}
.kpi .l{color:var(--muted);font-size:12.5px;font-weight:600;margin-top:4px}
.kpi .sub{color:var(--muted);font-size:11.5px;margin-top:2px}

/* Cards */
.card{background:var(--surface);border-radius:var(--radius);padding:22px 24px;box-shadow:var(--shadow);margin-bottom:20px}
.card-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.card-head h2{font-size:16.5px;margin:0;letter-spacing:-.01em}
.card-head p{margin:2px 0 0;color:var(--muted);font-size:13px}
.exec-card{border-left:5px solid var(--brand)}

/* Banners de Status de Mudança */
.change-banner{border-radius:12px;padding:15px 18px;margin-bottom:18px;display:flex;align-items:center;
justify-content:space-between;gap:14px;flex-wrap:wrap;border:1px solid transparent}
.cb-changed{background:#fffbeb;border-color:#fde68a;color:#92400e}
.cb-new{background:#eff6ff;border-color:#bfdbfe;color:#1e40af}
.cb-same{background:#f0fdf4;border-color:#bbf7d0;color:#166534}
.cb-error{background:#fef2f2;border-color:#fecaca;color:#991b1b}
.cb-main{display:flex;align-items:center;gap:12px}
.cb-icon{font-size:24px;line-height:1}
.cb-title{font-weight:700;font-size:14.5px}
.cb-sub{font-size:12.5px;opacity:.9;margin-top:2px}
.cb-cta{border:1px solid currentColor;background:rgba(255,255,255,.7);color:inherit;padding:6px 12px;
border-radius:8px;font-size:12.5px;font-weight:600;cursor:pointer;font-family:inherit}
.cb-cta:hover{background:#fff}

/* Tabela / Matriz */
.table-scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{text-align:left;color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;
letter-spacing:.05em;border-bottom:1px solid var(--line);padding:10px 10px}
td{padding:12px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
tr:last-child td{border-bottom:0}
tbody tr.row-link{cursor:pointer;transition:background .12s}
tbody tr.row-link:hover{background:var(--surface-2)}
td.num{text-align:center;font-variant-numeric:tabular-nums}
.add{color:var(--same);font-weight:700}.del{color:var(--error);font-weight:700}

/* Badges & Chips */
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.badge.new{background:#dbeafe;color:#1e40af}
.badge.changed{background:#fef3c7;color:#92400e}
.badge.same{background:#dcfce7;color:#166534}
.badge.error{background:#fee2e2;color:#991b1b}
.badge.t-alto{background:#dc2626;color:#fff}
.badge.t-medio{background:#f59e0b;color:#fff}
.badge.t-baixo{background:#64748b;color:#fff}
.badge.t-none{background:#f1f5f9;color:#64748b}

.cat-tag{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:6px;
font-size:11.5px;font-weight:600;background:var(--surface-2);border:1px solid var(--line);color:var(--ink-2);margin:2px}
.filters{display:flex;gap:6px;flex-wrap:wrap}
.chip{border:1px solid var(--line);background:var(--surface);padding:5px 12px;border-radius:999px;
font-size:12.5px;font-weight:500;cursor:pointer;color:var(--ink-2);font-family:inherit;transition:all .12s}
.chip:hover{border-color:var(--ink)}
.chip.active{background:var(--ink);color:#fff;border-color:var(--ink)}

/* Abas internas do concorrente */
.comp-hero{background:var(--surface);border-radius:var(--radius);padding:20px 24px;box-shadow:var(--shadow);
margin-bottom:18px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.comp-id{display:flex;align-items:center;gap:14px}
.avatar{width:48px;height:48px;border-radius:12px;display:grid;place-items:center;color:#fff;font-weight:800;font-size:17px;flex-shrink:0}
.comp-id h2{margin:0;font-size:20px}
.comp-meta{font-size:12.5px;color:var(--muted);display:flex;gap:12px;flex-wrap:wrap;margin-top:3px}
.comp-badges{display:flex;gap:8px;align-items:center;flex-wrap:wrap}

.tabs{display:flex;gap:6px;border-bottom:1px solid var(--line);margin-bottom:18px;flex-wrap:wrap}
.tab-btn{border:0;background:transparent;padding:10px 16px;font-size:13.5px;font-weight:600;color:var(--muted);
border-bottom:3px solid transparent;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:7px}
.tab-btn:hover{color:var(--ink)}
.tab-btn.active{color:var(--brand);border-bottom-color:var(--brand)}
.tab-count{background:var(--surface-2);border:1px solid var(--line);padding:1px 7px;border-radius:999px;font-size:11.5px;color:var(--ink-2)}
.tab-pane{display:none}
.tab-pane.active{display:block}

/* Grid de Sinais Estratégicos */
.sig-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,410px),1fr));gap:16px}
.sig-card{background:var(--surface);border-radius:12px;border:1px solid var(--line);border-top:4px solid var(--sc,var(--brand));
padding:16px 18px;display:flex;flex-direction:column;gap:10px}
.sig-head{display:flex;align-items:center;justify-content:space-between;gap:8px}
.sig-title{font-weight:700;font-size:14px;display:flex;align-items:center;gap:7px}
.sig-count{font-size:11.5px;font-weight:700;padding:2px 8px;border-radius:999px;background:var(--surface-2);color:var(--muted)}
.sig-list{margin:0;padding-left:18px;font-size:13.2px;color:var(--ink-2);display:flex;flex-direction:column;gap:6px}
.sig-list li{line-height:1.45}
.sig-comp-tag{font-weight:700;color:var(--ink);background:#e2e8f0;padding:1px 6px;border-radius:4px;font-size:11.5px;margin-right:5px}

/* Diff viewer */
.diff-box{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--surface-2)}
.diff-toolbar{padding:10px 14px;background:var(--surface);border-bottom:1px solid var(--line);
display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.diff-list{max-height:540px;overflow-y:auto;divide-y:1px solid var(--line)}
.diff-row{padding:9px 14px;font-size:13.2px;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:flex-start;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.diff-row:last-child{border-bottom:0}
.diff-row.d-add{background:#f0fdf4;color:#14532d}
.diff-row.d-del{background:#fef2f2;color:#7f1d1d}
.diff-sign{font-weight:800;user-select:none;width:16px;flex-shrink:0}
.diff-empty{padding:28px;text-align:center;color:var(--muted);font-size:13.5px}

/* Explorador de linhas raspadas */
.scrape-toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:space-between;margin-bottom:12px}
.scrape-search{flex:1;min-width:220px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;font-size:13.5px;font-family:inherit}
.scrape-list{border:1px solid var(--line);border-radius:12px;max-height:560px;overflow-y:auto;background:var(--surface)}
.scrape-row{padding:10px 14px;border-bottom:1px solid var(--line);display:flex;align-items:flex-start;justify-content:space-between;gap:12px;font-size:13.3px}
.scrape-row:last-child{border-bottom:0}
.scrape-row:hover{background:var(--surface-2)}
.scrape-idx{color:var(--muted);font-size:11.5px;font-variant-numeric:tabular-nums;min-width:32px;padding-top:2px}
.scrape-txt{flex:1;color:var(--ink-2)}
.scrape-tags{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end;flex-shrink:0}

/* Markdown renderizado */
.md{font-size:14px;color:var(--ink-2)}
.md p{margin:6px 0}.md ul,.md ol{margin:6px 0;padding-left:20px}.md li{margin:5px 0}
.md h4{margin:14px 0 6px;font-size:14px;color:var(--ink)}
.md code{background:#f1f5f9;padding:1px 6px;border-radius:6px;font-size:12.5px}
.md strong{color:var(--ink)}
.md em{color:var(--muted)}

@media (max-width:900px){
  .app{grid-template-columns:1fr}
  .sidebar{position:static;height:auto}
}
@media print{
  .sidebar,.topbar,.tabs,.filters,.scrape-toolbar{display:none!important}
  .app{display:block}.view-panel,.tab-pane{display:block!important;margin-bottom:24px}
}
"""

JS = """
function showView(viewId) {
  document.querySelectorAll('.view-panel').forEach(function(p){ p.classList.remove('active'); });
  document.querySelectorAll('.nav-btn').forEach(function(b){ b.classList.remove('active'); });
  var panel = document.getElementById('view-' + viewId);
  if (panel) panel.classList.add('active');
  var btn = document.querySelector('.nav-btn[data-view="' + viewId + '"]');
  if (btn) btn.classList.add('active');
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function showTab(compId, tabName) {
  var root = document.getElementById('view-' + compId);
  if (!root) return;
  root.querySelectorAll('.tab-btn').forEach(function(b){
    b.classList.toggle('active', b.dataset.tab === tabName);
  });
  root.querySelectorAll('.tab-pane').forEach(function(p){
    p.classList.toggle('active', p.dataset.pane === tabName);
  });
}

function jumpToCompTab(compId, tabName) {
  showView(compId);
  showTab(compId, tabName);
}

// Navegação da sidebar
document.querySelectorAll('.nav-btn').forEach(function(btn){
  btn.addEventListener('click', function(){ showView(btn.dataset.view); });
});

// Abas internas de cada concorrente
document.querySelectorAll('.tab-btn').forEach(function(btn){
  btn.addEventListener('click', function(){ showTab(btn.dataset.comp, btn.dataset.tab); });
});

// Filtro do Radar Estratégico na Visão Executiva
document.querySelectorAll('.radar-chip').forEach(function(chip){
  chip.addEventListener('click', function(){
    document.querySelectorAll('.radar-chip').forEach(function(c){ c.classList.remove('active'); });
    chip.classList.add('active');
    var cat = chip.dataset.cat;
    document.querySelectorAll('.radar-card').forEach(function(card){
      card.style.display = (cat === 'all' || card.dataset.cat === cat) ? '' : 'none';
    });
  });
});

// Filtro de diff (+/-) por concorrente
document.querySelectorAll('.diff-chip').forEach(function(chip){
  chip.addEventListener('click', function(){
    var box = chip.closest('.diff-box');
    box.querySelectorAll('.diff-chip').forEach(function(c){ c.classList.remove('active'); });
    chip.classList.add('active');
    var kind = chip.dataset.kind;
    box.querySelectorAll('.diff-row').forEach(function(row){
      row.style.display = (kind === 'all' || row.dataset.kind === kind) ? '' : 'none';
    });
  });
});

// Filtro do explorador de scraping (busca + categoria) por concorrente
function filterScrape(compId) {
  var root = document.getElementById('view-' + compId);
  if (!root) return;
  var q = (root.querySelector('.scrape-search').value || '').toLowerCase();
  var activeChip = root.querySelector('.scrape-chip.active');
  var cat = activeChip ? activeChip.dataset.cat : 'all';
  var visible = 0;
  root.querySelectorAll('.scrape-row').forEach(function(row){
    var txt = row.dataset.text || '';
    var cats = row.dataset.cats || '';
    var okQ = !q || txt.indexOf(q) !== -1;
    var okC = (cat === 'all') || (cats.split(',').indexOf(cat) !== -1);
    var show = okQ && okC;
    row.style.display = show ? '' : 'none';
    if (show) visible++;
  });
  var counter = root.querySelector('.scrape-count');
  if (counter) counter.textContent = visible + ' linha(s) exibida(s)';
}

document.querySelectorAll('.scrape-search').forEach(function(inp){
  inp.addEventListener('input', function(){ filterScrape(inp.dataset.comp); });
});

document.querySelectorAll('.scrape-chip').forEach(function(chip){
  chip.addEventListener('click', function(){
    var compId = chip.dataset.comp;
    var root = document.getElementById('view-' + compId);
    root.querySelectorAll('.scrape-chip').forEach(function(c){ c.classList.remove('active'); });
    chip.classList.add('active');
    filterScrape(compId);
  });
});

// Busca global na topbar: filtra cards e linhas na view ativa
var globalSearch = document.getElementById('global-search');
if (globalSearch) {
  globalSearch.addEventListener('input', function(){
    var q = (globalSearch.value || '').toLowerCase().trim();
    var activeView = document.querySelector('.view-panel.active');
    if (!activeView) return;
    if (activeView.id === 'view-overview') {
      activeView.querySelectorAll('.radar-item, tbody tr.row-link').forEach(function(el){
        el.style.display = (!q || el.textContent.toLowerCase().indexOf(q) !== -1) ? '' : 'none';
      });
    } else {
      var compId = activeView.id.replace('view-', '');
      var sInp = activeView.querySelector('.scrape-search');
      if (sInp) {
        sInp.value = globalSearch.value;
        showTab(compId, 'scraped');
        filterScrape(compId);
      }
    }
  });
}
"""

PAGE = Template("""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inteligência Competitiva · Painel Interno ($date)</title>
<style>$css</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-logo">CI</div>
      <div class="brand-txt">
        <strong>Competitive Intel</strong>
        <span>Painel Interno · AI &amp; Data PM</span>
      </div>
    </div>

    <div class="nav-list">
      <button class="nav-btn active" data-view="overview">
        <span>🧭</span>
        <span class="nav-name">Visão Executiva &amp; Radar</span>
      </button>
    </div>

    <div class="side-group-label">Concorrentes ($total)</div>
    <div class="nav-list">
      $sidebar_items
    </div>

    <div class="side-meta">
      <div><strong>Última coleta:</strong> $date</div>
      <div><strong>Motor:</strong> $engine</div>
      <div><strong>Modo:</strong> Uso interno · 100% local</div>
    </div>
  </aside>

  <div class="content">
    <header class="topbar">
      <div class="topbar-title">
        <span class="internal-tag">Uso Interno</span>
        <h1>Monitoramento Estratégico de Concorrentes</h1>
      </div>
      <div class="top-search">
        <span>🔎</span>
        <input id="global-search" type="search" placeholder="Buscar feature, preço, IA, termo no painel…">
      </div>
      $history_link
    </header>

    <main class="main-inner">
      <!-- ==================== VISÃO EXECUTIVA ==================== -->
      <div id="view-overview" class="view-panel active">
        <section class="kpis">$kpis</section>

        <section class="card exec-card">
          <div class="card-head">
            <div>
              <h2>🧭 Síntese Executiva do Ciclo</h2>
              <p>Resumo consolidado do status de mudanças e dos temas dominantes coletados nas páginas.</p>
            </div>
          </div>
          <div class="md">$executive</div>
        </section>

        <section class="card">
          <div class="card-head">
            <div>
              <h2>📋 Status de Mudanças &amp; Matriz Competitiva</h2>
              <p>Clique em qualquer concorrente para abrir a análise detalhada, o diff de linhas e os dados raspados.</p>
            </div>
          </div>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Concorrente</th>
                  <th>Teve mudança?</th>
                  <th>Delta (Linhas)</th>
                  <th>Ameaça</th>
                  <th>Temas Estratégicos Detectados no Scraping</th>
                  <th>Volume Coletado</th>
                  <th>Verificação Anterior</th>
                </tr>
              </thead>
              <tbody>$matrix_rows</tbody>
            </table>
          </div>
        </section>

        <section class="card">
          <div class="card-head">
            <div>
              <h2>📡 Radar de Inteligência Estratégica (Extraído do Web Scraping)</h2>
              <p>Sinais reais coletados das páginas dos concorrentes, classificados automaticamente por tema estratégico de PM.</p>
            </div>
            <div class="filters">$radar_filters</div>
          </div>
          <div class="sig-grid">$radar_cards</div>
        </section>
      </div>

      <!-- ==================== PAINÉIS POR CONCORRENTE ==================== -->
      $competitor_views
    </main>
  </div>
</div>
<script>$js</script>
</body>
</html>
""")


# --------------------------------------------------------------------------------------
# Construção dos blocos HTML
# --------------------------------------------------------------------------------------
def _build_change_banner(r: dict, comp_id: str) -> str:
    status = r["status"]
    prev = fmt_dt(r.get("previous_check"))
    last_chg = fmt_dt(r.get("last_change_at"))
    if status == "Alterado":
        return (
            f'<div class="change-banner cb-changed"><div class="cb-main"><span class="cb-icon">🔄</span><div>'
            f'<div class="cb-title">MUDANÇA DETECTADA NESTA EXECUÇÃO: +{r["added"]} linha(s) adicionada(s) e −{r["removed"]} removida(s)</div>'
            f'<div class="cb-sub">Comparado com a coleta anterior de {prev}. Verifique exatamente o que entrou e saiu na aba de Diff.</div>'
            f'</div></div><button class="cb-cta" onclick="showTab(\'{comp_id}\',\'diff\')">Ver quais foram as mudanças →</button></div>'
        )
    if status == "Novo":
        return (
            f'<div class="change-banner cb-new"><div class="cb-main"><span class="cb-icon">🆕</span><div>'
            f'<div class="cb-title">PRIMEIRA COLETA (LINHA DE BASE): {r.get("total_lines", 0)} linhas estratégicas capturadas</div>'
            f'<div class="cb-sub">Snapshot inicial salvo em {fmt_dt(r.get("fetched_at"))}. As próximas execuções mostrarão o diff exato do que mudar.</div>'
            f'</div></div><button class="cb-cta" onclick="showTab(\'{comp_id}\',\'scraped\')">Explorar conteúdo coletado →</button></div>'
        )
    if status == "Sem mudanças":
        has_hist = len(r.get("last_added_lines") or []) + len(r.get("last_removed_lines") or []) > 0
        hist_txt = (f"Última alteração registrada em {last_chg}." if last_chg != "—"
                    else "Nenhuma alteração desde o início do monitoramento.")
        btn = (f'<button class="cb-cta" onclick="showTab(\'{comp_id}\',\'diff\')">Ver último diff registrado →</button>'
               if has_hist else
               f'<button class="cb-cta" onclick="showTab(\'{comp_id}\',\'scraped\')">Ver {r.get("total_lines", 0)} linhas monitoradas →</button>')
        return (
            f'<div class="change-banner cb-same"><div class="cb-main"><span class="cb-icon">✅</span><div>'
            f'<div class="cb-title">NÃO HOUVE MUDANÇA NESTA EXECUÇÃO (página idêntica à coleta de {prev})</div>'
            f'<div class="cb-sub">{hist_txt} Abaixo estão todos os sinais estratégicos extraídos do conteúdo atual da página.</div>'
            f'</div></div>{btn}</div>'
        )
    return (
        f'<div class="change-banner cb-error"><div class="cb-main"><span class="cb-icon">⚠️</span><div>'
        f'<div class="cb-title">FALHA NA COLETA DESTE CONCORRENTE</div>'
        f'<div class="cb-sub">Não foi possível acessar ou extrair texto da URL configurada.</div>'
        f'</div></div></div>'
    )


def _build_signals_grid_for_competitor(r: dict) -> str:
    signals = r.get("signals") or {}
    cards = []
    for cat_key, meta in signals.items():
        if not meta.get("highlights"):
            continue
        items = "".join(f"<li>{html.escape(line)}</li>" for line in meta["highlights"])
        cards.append(
            f'<div class="sig-card" style="--sc:{meta["color"]}">'
            f'<div class="sig-head"><div class="sig-title"><span>{meta["icon"]}</span>{html.escape(meta["label"])}</div>'
            f'<span class="sig-count">{meta["count"]} menção(ões)</span></div>'
            f'<ul class="sig-list">{items}</ul></div>'
        )
    if not cards:
        return '<div class="card"><p style="color:var(--muted);margin:0">Nenhum sinal temático específico detectado nas linhas coletadas.</p></div>'
    return f'<div class="sig-grid">{"".join(cards)}</div>'


def _build_diff_pane(r: dict) -> str:
    status = r["status"]
    if status == "Alterado":
        added = r.get("added_lines") or []
        removed = r.get("removed_lines") or []
        header_note = (f"Exibindo as mudanças detectadas nesta execução "
                       f"(comparado com {fmt_dt(r.get('previous_check'))}).")
    else:
        added = r.get("last_added_lines") or []
        removed = r.get("last_removed_lines") or []
        if added or removed:
            header_note = (f"Não houve mudança nesta coleta. Exibindo o histórico da última alteração "
                           f"registrada em {fmt_dt(r.get('last_change_at'))}.")
        elif status == "Novo":
            header_note = ("Esta é a primeira coleta (linha de base). Quando a página do concorrente mudar "
                           "nas próximas execuções, as linhas adicionadas (+) e removidas (−) aparecerão aqui.")
        else:
            header_note = "Nenhuma diferença registrada entre as coletas até o momento."

    rows = []
    for line in added:
        rows.append(
            f'<div class="diff-row d-add" data-kind="add"><span class="diff-sign">+</span>'
            f'<span>{html.escape(line)}</span></div>'
        )
    for line in removed:
        rows.append(
            f'<div class="diff-row d-del" data-kind="del"><span class="diff-sign">−</span>'
            f'<span>{html.escape(line)}</span></div>'
        )

    body = "".join(rows) if rows else f'<div class="diff-empty">{html.escape(header_note)}</div>'
    return (
        f'<div class="card"><div class="card-head"><div>'
        f'<h2>🔄 O que mudou na página (Diff de Linhas)</h2><p>{html.escape(header_note)}</p>'
        f'</div></div>'
        f'<div class="diff-box"><div class="diff-toolbar">'
        f'<div class="filters">'
        f'<button class="chip diff-chip active" data-kind="all">Todas ({len(added) + len(removed)})</button>'
        f'<button class="chip diff-chip" data-kind="add">+ Adicionadas ({len(added)})</button>'
        f'<button class="chip diff-chip" data-kind="del">− Removidas ({len(removed)})</button>'
        f'</div></div><div class="diff-list">{body}</div></div></div>'
    )


def _build_scraped_pane(r: dict, comp_id: str) -> str:
    lines = r.get("scraped_lines") or []
    signals = r.get("signals") or {}

    filter_btns = [f'<button class="chip scrape-chip active" data-comp="{comp_id}" data-cat="all">Todas ({len(lines)})</button>']
    for cat_key, meta in STRATEGIC_CATEGORIES.items():
        c = signals.get(cat_key, {}).get("count", 0)
        if c > 0:
            filter_btns.append(
                f'<button class="chip scrape-chip" data-comp="{comp_id}" data-cat="{cat_key}">'
                f'{meta["icon"]} {html.escape(meta["label"])} ({c})</button>'
            )

    rows = []
    for i, line in enumerate(lines, start=1):
        cats = [k for k, _ in classify_line(line)]
        tags_html = "".join(
            f'<span class="cat-tag">{STRATEGIC_CATEGORIES[k]["icon"]} {html.escape(STRATEGIC_CATEGORIES[k]["label"])}</span>'
            for k in cats[:3]
        )
        rows.append(
            f'<div class="scrape-row" data-text="{html.escape(line.lower(), quote=True)}" '
            f'data-cats="{",".join(cats)}">'
            f'<span class="scrape-idx">#{i}</span>'
            f'<span class="scrape-txt">{html.escape(line)}</span>'
            f'<span class="scrape-tags">{tags_html}</span></div>'
        )

    body = "".join(rows) if rows else '<div class="diff-empty">Nenhuma linha coletada.</div>'
    return (
        f'<div class="card"><div class="card-head"><div>'
        f'<h2>📄 Conteúdo Raspado da Página ({len(lines)} blocos de texto)</h2>'
        f'<p>Texto limpo extraído de <a href="{html.escape(r["url"], quote=True)}" target="_blank" rel="noopener">{html.escape(r["url"])}</a>. '
        f'Filtre por categoria estratégica ou pesquise qualquer termo.</p>'
        f'</div><span class="scrape-count" style="font-size:12.5px;color:var(--muted)">{len(lines)} linha(s) exibida(s)</span></div>'
        f'<div class="scrape-toolbar">'
        f'<input class="scrape-search" data-comp="{comp_id}" type="search" placeholder="Filtrar frases coletadas deste concorrente…">'
        f'<div class="filters">{"".join(filter_btns)}</div>'
        f'</div><div class="scrape-list">{body}</div></div>'
    )


def _build_competitor_view(r: dict, comp_id: str) -> str:
    name, url = html.escape(r["name"]), html.escape(r["url"], quote=True)
    initials, color = _avatar(r["name"])
    selector_info = f"Seletor CSS: <code>{html.escape(str(r.get('selector')))}</code>" if r.get("selector") else "Página completa"
    signals = r.get("signals") or {}
    sig_total = sum(v.get("count", 0) for v in signals.values())
    diff_total = (r["added"] + r["removed"]) if r["status"] == "Alterado" else (
        len(r.get("last_added_lines") or []) + len(r.get("last_removed_lines") or [])
    )

    analysis_html = md_to_html(r.get("analysis") or "_Sem análise disponível._")
    return (
        f'<div id="view-{comp_id}" class="view-panel">'
        f'<div class="comp-hero">'
        f'  <div class="comp-id">'
        f'    <div class="avatar" style="background:{color}">{html.escape(initials)}</div>'
        f'    <div><h2>{name}</h2>'
        f'      <div class="comp-meta">'
        f'        <span>🔗 <a href="{url}" target="_blank" rel="noopener">{html.escape(r["url"])} ↗</a></span>'
        f'        <span>🎯 {selector_info}</span>'
        f'        <span>🕒 Verificação anterior: {fmt_dt(r.get("previous_check"))}</span>'
        f'      </div>'
        f'    </div>'
        f'  </div>'
        f'  <div class="comp-badges">{_badge(r["status"])}{_threat_badge(r.get("threat"))}</div>'
        f'</div>'
        f'{_build_change_banner(r, comp_id)}'
        f'<div class="tabs">'
        f'  <button class="tab-btn active" data-comp="{comp_id}" data-tab="intel">'
        f'    🎯 Inteligência Estratégica <span class="tab-count">{sig_total} sinais</span></button>'
        f'  <button class="tab-btn" data-comp="{comp_id}" data-tab="diff">'
        f'    🔄 Mudanças / Diff <span class="tab-count">{diff_total}</span></button>'
        f'  <button class="tab-btn" data-comp="{comp_id}" data-tab="scraped">'
        f'    📄 Conteúdo Coletado <span class="tab-count">{r.get("total_lines", 0)} linhas</span></button>'
        f'</div>'
        f'<div class="tab-pane active" data-pane="intel">'
        f'  <div class="card"><div class="card-head"><div>'
        f'    <h2>🧠 Leitura Estratégica &amp; Implicações para Produto</h2>'
        f'    <p>Síntese gerada a partir do conteúdo coletado desta página.</p>'
        f'  </div></div><div class="md">{analysis_html}</div></div>'
        f'  <div class="card"><div class="card-head"><div>'
        f'    <h2>📡 Evidências Extraídas do Scraping por Categoria</h2>'
        f'    <p>Trechos reais da página de {name} agrupados por tema competitivo.</p>'
        f'  </div></div>{_build_signals_grid_for_competitor(r)}</div>'
        f'</div>'
        f'<div class="tab-pane" data-pane="diff">{_build_diff_pane(r)}</div>'
        f'<div class="tab-pane" data-pane="scraped">{_build_scraped_pane(r, comp_id)}</div>'
        f'</div>'
    )


def _build_global_radar(ordered: list[dict]) -> tuple[str, str]:
    """Constrói os filtros e os cards do Radar Estratégico cruzando todos os concorrentes."""
    cat_items: dict[str, list[tuple[str, str, str]]] = {k: [] for k in STRATEGIC_CATEGORIES}
    cat_counts: dict[str, int] = {k: 0 for k in STRATEGIC_CATEGORIES}

    for r in ordered:
        comp_id = r["_id"]
        sigs = r.get("signals") or {}
        for k, meta in sigs.items():
            cat_counts[k] += meta.get("count", 0)
            for line in meta.get("highlights", [])[:4]:
                cat_items[k].append((r["name"], comp_id, line))

    total_signals = sum(cat_counts.values())
    filters = [f'<button class="chip radar-chip active" data-cat="all">Todos os temas ({total_signals})</button>']
    cards = []

    for k, meta in STRATEGIC_CATEGORIES.items():
        if not cat_items[k]:
            continue
        filters.append(
            f'<button class="chip radar-chip" data-cat="{k}">{meta["icon"]} {html.escape(meta["label"])} ({cat_counts[k]})</button>'
        )
        lis = "".join(
            f'<li class="radar-item"><a href="javascript:void(0)" onclick="showView(\'{cid}\')" '
            f'class="sig-comp-tag">{html.escape(cname)}</a>{html.escape(line)}</li>'
            for cname, cid, line in cat_items[k][:8]
        )
        cards.append(
            f'<div class="sig-card radar-card" data-cat="{k}" style="--sc:{meta["color"]}">'
            f'<div class="sig-head"><div class="sig-title"><span>{meta["icon"]}</span>{html.escape(meta["label"])}</div>'
            f'<span class="sig-count">{cat_counts[k]} sinais no total</span></div>'
            f'<ul class="sig-list">{lis}</ul></div>'
        )

    if not cards:
        cards.append('<p style="color:var(--muted)">Nenhum sinal estratégico coletado neste ciclo.</p>')
    return "".join(filters), "".join(cards)


def build_html(results: list[dict], executive: str, engine: str, *, history_href: str | None = None) -> str:
    for idx, r in enumerate(results):
        r["threat"] = extract_threat(r.get("analysis", ""))
        r["_id"] = _slug_id(r["name"], idx)
        r.setdefault("total_lines", len(r.get("scraped_lines") or []))
        r.setdefault("signals", {})

    ordered = sorted(
        results,
        key=lambda r: (
            STATUS_ORDER.index(r["status"]) if r["status"] in STATUS_ORDER else 9,
            THREAT_RANK.get(r["threat"], 3),
        ),
    )

    count = lambda s: sum(1 for r in results if r["status"] == s)  # noqa: E731
    total_lines = sum(r.get("total_lines", 0) for r in results)
    total_signals = sum(
        sum(m.get("count", 0) for m in (r.get("signals") or {}).values())
        for r in results
    )
    high = sum(1 for r in results if r["threat"] == "Alto")
    changed_c = count("Alterado")

    kpi_data = [
        ("Concorrentes", len(results), f"{count('Sem mudanças')} estável(is) · {count('Novo')} novo(s)", "var(--brand)"),
        ("Teve mudança?", "Sim (" + str(changed_c) + ")" if changed_c else "Não (0)",
         "Nesta execução vs. snapshot anterior", "var(--changed)" if changed_c else "var(--same)"),
        ("Sinais Estratégicos", total_signals, "Extraídos de IA, Preço, Produto, API…", "#7c3aed"),
        ("Volume Raspado", total_lines, "Blocos de texto limpos monitorados", "#0284c7"),
        ("Ameaças Altas", high, "Concorrentes com alerta máximo", "#dc2626"),
    ]
    kpis = "".join(
        f'<div class="kpi" style="--c:{c}"><div class="v">{v}</div><div class="l">{l}</div><div class="sub">{s}</div></div>'
        for l, v, s, c in kpi_data
    )

    sidebar_items, matrix_rows, comp_views = [], [], []
    for r in ordered:
        cid = r["_id"]
        name = html.escape(r["name"])
        css = STATUS_META.get(r["status"], {"css": "same"})["css"]
        pill = f"+{r['added']}/−{r['removed']}" if r["status"] == "Alterado" else f"{r.get('total_lines', 0)}L"
        sidebar_items.append(
            f'<button class="nav-btn" data-view="{cid}">'
            f'<span class="nav-dot dot-{css}"></span>'
            f'<span class="nav-name">{name}</span>'
            f'<span class="nav-pill">{pill}</span></button>'
        )

        # Tags resumidas das categorias estratégicas para a matriz
        sigs = r.get("signals") or {}
        top_cats = sorted(
            ((k, m) for k, m in sigs.items() if m.get("count", 0) > 0),
            key=lambda x: -x[1]["count"],
        )[:4]
        cat_tags = "".join(
            f'<span class="cat-tag">{m["icon"]} {html.escape(m["label"])}: <strong>{m["count"]}</strong></span>'
            for _, m in top_cats
        ) or '<span style="color:var(--muted)">—</span>'

        if r["status"] == "Alterado":
            delta_html = f'<span class="add">+{r["added"]}</span> / <span class="del">−{r["removed"]}</span>'
        else:
            delta_html = '<span style="color:var(--muted)">0 / 0</span>'

        matrix_rows.append(
            f'<tr class="row-link" onclick="showView(\'{cid}\')">'
            f'<td><strong>{name}</strong><div style="font-size:11.5px;color:var(--muted)">{html.escape(urlparse(r["url"]).netloc)}</div></td>'
            f'<td>{_badge(r["status"])}</td>'
            f'<td class="num">{delta_html}</td>'
            f'<td>{_threat_badge(r["threat"])}</td>'
            f'<td>{cat_tags}</td>'
            f'<td class="num">{r.get("total_lines", 0)} linhas</td>'
            f'<td>{fmt_dt(r.get("previous_check"))}</td></tr>'
        )

        comp_views.append(_build_competitor_view(r, cid))

    radar_filters, radar_cards = _build_global_radar(ordered)
    history_link = (
        f'<a href="{html.escape(history_href, quote=True)}" class="chip" style="text-decoration:none;font-weight:600">'
        f'🗂️ Histórico de Versões</a>'
        if history_href else ""
    )

    return PAGE.substitute(
        css=CSS,
        js=JS,
        date=datetime.now().strftime("%d/%m/%Y %H:%M"),
        engine=html.escape(engine),
        total=len(results),
        sidebar_items="".join(sidebar_items),
        kpis=kpis,
        executive=md_to_html(executive),
        matrix_rows="".join(matrix_rows),
        radar_filters=radar_filters,
        radar_cards=radar_cards,
        competitor_views="".join(comp_views),
        history_link=history_link,
    )


# --------------------------------------------------------------------------------------
# Markdown (opcional)
# --------------------------------------------------------------------------------------
def build_markdown(results: list[dict], executive: str, engine: str) -> str:
    icon = lambda s: STATUS_META.get(s, {}).get("icon", "")  # noqa: E731
    md = [
        "# 📊 Relatório de Inteligência Competitiva",
        "",
        f"> **Gerado em:** {datetime.now().strftime('%d/%m/%Y %H:%M')}  ",
        f"> **Motor de análise:** {engine}  ",
        f"> **Concorrentes monitorados:** {len(results)}",
        "",
        "## 🧭 Resumo Executivo",
        "",
        executive.strip(),
        "",
        "## 📋 Visão Geral",
        "",
        "| Concorrente | Status | Linhas + | Linhas − | Linhas Coletadas | Verificação anterior |",
        "|---|---|:-:|:-:|:-:|---|",
    ]
    for r in results:
        md.append(
            f"| [{r['name']}]({r['url']}) | {icon(r['status'])} {r['status']} | {r['added']} | "
            f"{r['removed']} | {r.get('total_lines', 0)} | {fmt_dt(r.get('previous_check'))} |"
        )
    md += ["", "## 🔍 Análise por Concorrente", ""]
    for r in results:
        md += [
            f"### {icon(r['status'])} {r['name']}",
            "",
            f"**Fonte:** <{r['url']}>",
            "",
            r["analysis"].strip() if r.get("analysis") else "_Sem análise disponível._",
            "",
        ]
        sigs = r.get("signals") or {}
        active = [(k, m) for k, m in sigs.items() if m.get("highlights")]
        if active:
            md.append("#### 📡 Sinais Estratégicos Extraídos do Scraping")
            for _, m in active:
                md.append(f"- **{m['icon']} {m['label']} ({m['count']}):** " + " | ".join(m["highlights"][:3]))
            md.append("")
        if r.get("added_lines") or r.get("removed_lines"):
            md.append("#### 🔄 Mudanças Detectadas (Diff)")
            for l in (r.get("added_lines") or [])[:15]:
                md.append(f"- `+` {l}")
            for l in (r.get("removed_lines") or [])[:10]:
                md.append(f"- `-` {l}")
            md.append("")
        md += ["---", ""]
    md.append("_Relatório gerado automaticamente por **Competitive Intel Monitor** — IA 100% local e privada._")
    return "\n".join(md) + "\n"
