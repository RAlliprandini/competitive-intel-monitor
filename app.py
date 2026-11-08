#!/usr/bin/env python3
"""
app.py — Interface Web Local para gerenciar URLs de concorrentes, disparar o Web Scraping
e navegar pelas versões de relatórios HTML geradas em `relatorios_html/`.

100% Python puro (usa `http.server` da stdlib — nenhuma dependência extra além de requests e bs4).

Uso:
  python app.py                  # sobe em http://127.0.0.1:8765 e abre no navegador
  python monitor.py --ui         # atalho pelo script principal
"""

from __future__ import annotations

import html
import json
import socket
import sys
import threading
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config_manager as cm
import monitor
from ai_analyzer import build_analyzer
from reporting import build_html, build_markdown

BASE_DIR = monitor.BASE_DIR
CONFIG_PATH = BASE_DIR / "config.json"


# --------------------------------------------------------------------------------------
# Execução do scraping acionada pela interface
# --------------------------------------------------------------------------------------
def run_scraping_job(only_names: list[str] | None = None, force_heuristic: bool = False) -> dict:
    """Executa o pipeline completo de scraping + análise e salva na pasta de versões HTML."""
    cfg = cm.load_config(CONFIG_PATH)
    competitors = cm.active_competitors(cfg)
    if only_names:
        wanted = {n.lower() for n in only_names}
        competitors = [c for c in cfg["competitors"] if c["name"].lower() in wanted]

    if not competitors:
        return {"ok": False, "error": "Nenhuma URL ativa para monitorar. Adicione ou ative ao menos um concorrente."}

    snapshots_dir = BASE_DIR / cfg["output"].get("snapshots_dir", "snapshots")
    reports_dir = BASE_DIR / cfg["output"].get("reports_dir", "relatorios_html")
    reports_dir.mkdir(parents=True, exist_ok=True)

    analyzer = build_analyzer(cfg.get("ai", {}), force_heuristic=force_heuristic)
    results = [monitor.process_competitor(c, cfg, analyzer, snapshots_dir) for c in competitors]

    try:
        executive = analyzer.executive_summary(results)
    except Exception as exc:
        executive = f"⚠️ Não foi possível gerar o resumo executivo: `{exc}`"

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    base_name = cfg["output"].get("report_file", "relatorio_competitivo")
    version_filename = f"{base_name}_{stamp}.html"
    version_path = reports_dir / version_filename
    latest_html_path = BASE_DIR / f"{base_name}.html"
    latest_md_path = BASE_DIR / f"{base_name}.md"

    html_content = build_html(results, executive, analyzer.label, history_href="http://127.0.0.1:8765/")
    version_path.write_text(html_content, encoding="utf-8")
    latest_html_path.write_text(html_content, encoding="utf-8")
    latest_md_path.write_text(build_markdown(results, executive, analyzer.label), encoding="utf-8")

    # Salva metadados da versão para exibir no histórico da UI
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
    meta_path = reports_dir / f"{base_name}_{stamp}.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "report_url": f"/reports/{version_filename}",
        "filename": version_filename,
        "summary": meta,
    }


def list_report_versions() -> list[dict]:
    cfg = cm.load_config(CONFIG_PATH)
    reports_dir = BASE_DIR / cfg["output"].get("reports_dir", "relatorios_html")
    if not reports_dir.exists():
        return []
    versions = []
    for html_file in sorted(reports_dir.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
        meta_file = html_file.with_suffix(".json")
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                meta["size_kb"] = round(html_file.stat().st_size / 1024, 1)
                versions.append(meta)
                continue
            except Exception:
                pass
        dt = datetime.fromtimestamp(html_file.stat().st_mtime).strftime("%d/%m/%Y %H:%M:%S")
        versions.append({
            "filename": html_file.name,
            "created_at": dt,
            "engine": "—",
            "total": "—",
            "changed": 0,
            "new": 0,
            "same": 0,
            "errors": 0,
            "size_kb": round(html_file.stat().st_size / 1024, 1),
            "competitors": [],
        })
    return versions


# --------------------------------------------------------------------------------------
# HTML da Interface de Controle (Frontend Single-Page)
# --------------------------------------------------------------------------------------
UI_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Competitive Intel · Central de Web Scraping</title>
<style>
:root{
  --bg:#0f172a;--panel:#1e293b;--card:#ffffff;--surface:#f8fafc;--ink:#0f172a;--ink-2:#334155;
  --muted:#64748b;--line:#e2e8f0;--brand:#4f46e5;--brand-hover:#4338ca;--green:#16a34a;
  --amber:#d97706;--red:#dc2626;--radius:14px;
  --shadow:0 1px 3px rgba(15,23,42,.06),0 8px 24px rgba(15,23,42,.06);
}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,"Segoe UI",system-ui,-apple-system,sans-serif;background:#f1f5f9;color:var(--ink);line-height:1.5}
.hero{background:linear-gradient(135deg,#0f172a 0%,#1e1b4b 60%,#312e81 100%);color:#fff;padding:28px 32px;
display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap}
.hero-left{display:flex;align-items:center;gap:14px}
.logo{width:44px;height:44px;border-radius:12px;background:linear-gradient(135deg,#6366f1,#0ea5e9);
display:grid;place-items:center;font-weight:800;font-size:20px;color:#fff}
.hero h1{margin:0;font-size:21px;letter-spacing:-.01em}
.hero p{margin:3px 0 0;font-size:13px;color:#cbd5e1}
.hero-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}

.wrap{max-width:1280px;margin:0 auto;padding:24px 28px 56px;display:grid;grid-template-columns:1.15fr .85fr;gap:22px}
@media(max-width:980px){.wrap{grid-template-columns:1fr}}

.card{background:var(--card);border-radius:var(--radius);padding:22px 24px;box-shadow:var(--shadow);margin-bottom:20px}
.card-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px;flex-wrap:wrap}
.card-head h2{margin:0;font-size:16.5px;display:flex;align-items:center;gap:8px}
.card-head p{margin:2px 0 0;font-size:12.5px;color:var(--muted)}

label{display:block;font-size:12.5px;font-weight:600;color:var(--ink-2);margin-bottom:5px}
input[type="text"],input[type="url"],textarea{
  width:100%;padding:10px 12px;border:1px solid var(--line);border-radius:10px;font-size:13.5px;
  font-family:inherit;background:var(--surface);color:var(--ink);transition:border .15s
}
input:focus,textarea:focus{outline:none;border-color:var(--brand);background:#fff}
textarea{resize:vertical;min-height:92px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13px}

.form-grid{display:grid;grid-template-columns:1.4fr .9fr .7fr auto;gap:10px;align-items:end}
@media(max-width:720px){.form-grid{grid-template-columns:1fr}}

.btn{border:0;border-radius:10px;padding:10px 16px;font-size:13.5px;font-weight:600;cursor:pointer;
font-family:inherit;display:inline-flex;align-items:center;justify-content:center;gap:8px;transition:all .15s;text-decoration:none}
.btn-primary{background:var(--brand);color:#fff;box-shadow:0 4px 12px rgba(79,70,229,.25)}
.btn-primary:hover{background:var(--brand-hover)}
.btn-run{background:linear-gradient(135deg,#10b981,#059669);color:#fff;padding:12px 20px;font-size:14px;
box-shadow:0 4px 14px rgba(16,185,129,.35)}
.btn-run:hover{filter:brightness(1.06)}
.btn-run:disabled{opacity:.6;cursor:wait}
.btn-ghost{background:rgba(255,255,255,.12);color:#fff;border:1px solid rgba(255,255,255,.2)}
.btn-ghost:hover{background:rgba(255,255,255,.2)}
.btn-soft{background:var(--surface);color:var(--ink-2);border:1px solid var(--line);padding:7px 12px;font-size:12.5px}
.btn-soft:hover{border-color:var(--ink)}
.btn-danger{background:#fef2f2;color:var(--red);border:1px solid #fecaca;padding:6px 10px;font-size:12px}
.btn-danger:hover{background:#fee2e2}

/* Lista de URLs */
.url-list{display:flex;flex-direction:column;gap:8px;margin-top:8px}
.url-item{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 14px;
border:1px solid var(--line);border-radius:11px;background:var(--surface);transition:background .12s}
.url-item.disabled{opacity:.55;background:#f1f5f9}
.url-main{display:flex;align-items:center;gap:12px;min-width:0;flex:1}
.url-info{min-width:0;flex:1}
.url-name{font-weight:700;font-size:14px;display:flex;align-items:center;gap:8px}
.url-link{font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}
.sel-badge{font-size:11px;background:#e0e7ff;color:#3730a3;padding:1px 7px;border-radius:5px;font-family:monospace}
.url-actions{display:flex;align-items:center;gap:6px;flex-shrink:0}

/* Toggle switch */
.switch{position:relative;display:inline-block;width:38px;height:22px;flex-shrink:0}
.switch input{opacity:0;width:0;height:0}
.slider{position:absolute;cursor:pointer;inset:0;background:#cbd5e1;transition:.2s;border-radius:999px}
.slider:before{position:absolute;content:"";height:16px;width:16px;left:3px;bottom:3px;background:#fff;transition:.2s;border-radius:50%}
input:checked + .slider{background:var(--green)}
input:checked + .slider:before{transform:translateX(16px)}

/* Lista de versões HTML */
.ver-list{display:flex;flex-direction:column;gap:10px}
.ver-item{border:1px solid var(--line);border-radius:11px;padding:13px 15px;background:var(--surface);
display:flex;align-items:center;justify-content:space-between;gap:12px;transition:border .12s}
.ver-item:hover{border-color:var(--brand);background:#fff}
.ver-title{font-weight:700;font-size:13.5px;color:var(--ink);display:flex;align-items:center;gap:7px}
.ver-meta{font-size:12px;color:var(--muted);margin-top:3px;display:flex;gap:8px;flex-wrap:wrap}
.pill{font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px}
.pill-chg{background:#fef3c7;color:#92400e}
.pill-new{background:#dbeafe;color:#1e40af}
.pill-same{background:#dcfce7;color:#166534}
.pill-err{background:#fee2e2;color:#991b1b}

/* Status Toast / Banner de execução */
#status-box{display:none;border-radius:12px;padding:14px 18px;margin-bottom:18px;font-size:13.5px;
align-items:center;justify-content:space-between;gap:12px}
.st-running{background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af}
.st-done{background:#f0fdf4;border:1px solid #bbf7d0;color:#166534}
.st-err{background:#fef2f2;border:1px solid #fecaca;color:#991b1b}
.spinner{width:18px;height:18px;border:3px solid currentColor;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;display:inline-block}
@keyframes spin{to{transform:rotate(360deg)}}
.empty{text-align:center;color:var(--muted);padding:24px;font-size:13.5px}
</style>
</head>
<body>

<header class="hero">
  <div class="hero-left">
    <div class="logo">CI</div>
    <div>
      <h1>Central de Inteligência Competitiva · Web Scraping</h1>
      <p>Adicione as URLs que deseja monitorar, execute a coleta e abra qualquer versão do painel estratégico HTML.</p>
    </div>
  </div>
  <div class="hero-actions">
    <a href="/latest" target="_blank" class="btn btn-ghost">📊 Abrir Último Relatório HTML ↗</a>
    <button id="btn-run-all" class="btn btn-run" onclick="runScraping()">
      🚀 Rodar Web Scraping Agora
    </button>
  </div>
</header>

<div class="wrap">
  <!-- COLUNA ESQUERDA: GESTÃO DE URLs -->
  <div>
    <div id="status-box"></div>

    <div class="card">
      <div class="card-head">
        <div>
          <h2>➕ Adicionar URL de Concorrente</h2>
          <p>Informe o endereço da página (changelog, releases, pricing, blog) e, se quiser, o nome e o seletor CSS.</p>
        </div>
      </div>
      <form id="form-single" onsubmit="addSingle(event)">
        <div class="form-grid">
          <div>
            <label>URL da página *</label>
            <input id="inp-url" type="text" placeholder="https://concorrente.com/changelog" required>
          </div>
          <div>
            <label>Nome (opcional)</label>
            <input id="inp-name" type="text" placeholder="Automático pelo domínio">
          </div>
          <div>
            <label>Seletor CSS (opcional)</label>
            <input id="inp-sel" type="text" placeholder="main, article…">
          </div>
          <button type="submit" class="btn btn-primary">+ Adicionar</button>
        </div>
      </form>

      <hr style="border:0;border-top:1px solid var(--line);margin:18px 0">

      <details>
        <summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--brand)">
          📋 Colar várias URLs de uma vez (lote)
        </summary>
        <div style="margin-top:12px">
          <label>Cole uma URL por linha (opcionalmente: <code>URL | Nome | Seletor</code>)</label>
          <textarea id="inp-bulk" placeholder="https://linear.app/changelog | Linear | main&#10;https://www.notion.com/releases&#10;https://www.figma.com/release-notes/"></textarea>
          <div style="margin-top:10px;display:flex;justify-content:flex-end">
            <button type="button" class="btn btn-primary" onclick="addBulk()">Adicionar todas as URLs</button>
          </div>
        </div>
      </details>
    </div>

    <div class="card">
      <div class="card-head">
        <div>
          <h2>🌐 URLs Configuradas para Web Scraping (<span id="comp-count">0</span>)</h2>
          <p>Ative/pause com a chave seletora ou clique em "Raspar só este" para testar uma URL específica.</p>
        </div>
      </div>
      <div id="url-list" class="url-list"></div>
    </div>
  </div>

  <!-- COLUNA DIREITA: VERSÕES DO HTML GERADAS -->
  <div>
    <div class="card">
      <div class="card-head">
        <div>
          <h2>🗂️ Versões do Relatório HTML (<code>relatorios_html/</code>)</h2>
          <p>Cada execução gera e preserva um arquivo HTML navegável separado com data e hora.</p>
        </div>
      </div>
      <div id="ver-list" class="ver-list"></div>
    </div>
  </div>
</div>

<script>
function esc(s) {
  var d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

async function api(path, body) {
  var opts = body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {};
  var r = await fetch(path, opts);
  return await r.json();
}

function showStatus(kind, htmlMsg) {
  var box = document.getElementById('status-box');
  box.className = kind === 'running' ? 'st-running' : (kind === 'done' ? 'st-done' : 'st-err');
  box.style.display = 'flex';
  box.innerHTML = htmlMsg;
}

async function loadState() {
  var data = await api('/api/state');
  renderCompetitors(data.competitors || []);
  renderVersions(data.versions || []);
}

function renderCompetitors(list) {
  var activeCount = list.filter(function(c){ return c.enabled !== false; }).length;
  document.getElementById('comp-count').textContent = activeCount + ' ativas de ' + list.length;
  var root = document.getElementById('url-list');
  if (!list.length) {
    root.innerHTML = '<div class="empty">Nenhuma URL cadastrada ainda. Adicione suas URLs no formulário acima.</div>';
    return;
  }
  root.innerHTML = list.map(function(c){
    var enabled = c.enabled !== false;
    var sel = c.selector ? '<span class="sel-badge">' + esc(c.selector) + '</span>' : '';
    return (
      '<div class="url-item ' + (enabled ? '' : 'disabled') + '">' +
        '<div class="url-main">' +
          '<label class="switch" title="Ativar/Pausar monitoramento">' +
            '<input type="checkbox" ' + (enabled ? 'checked' : '') +
            ' onchange="toggleComp(' + JSON.stringify(c.name).replace(/"/g, '&quot;') + ', this.checked)">' +
            '<span class="slider"></span>' +
          '</label>' +
          '<div class="url-info">' +
            '<div class="url-name">' + esc(c.name) + ' ' + sel + '</div>' +
            '<a class="url-link" href="' + esc(c.url) + '" target="_blank" rel="noopener">' + esc(c.url) + ' ↗</a>' +
          '</div>' +
        '</div>' +
        '<div class="url-actions">' +
          '<button class="btn btn-soft" onclick="runScraping([' + JSON.stringify(c.name).replace(/"/g, '&quot;') + '])">▶ Raspar só este</button>' +
          '<button class="btn btn-danger" onclick="removeComp(' + JSON.stringify(c.name).replace(/"/g, '&quot;') + ')">Excluir</button>' +
        '</div>' +
      '</div>'
    );
  }).join('');
}

function renderVersions(versions) {
  var root = document.getElementById('ver-list');
  if (!versions.length) {
    root.innerHTML = '<div class="empty">Nenhuma versão gerada ainda. Clique em "Rodar Web Scraping Agora".</div>';
    return;
  }
  root.innerHTML = versions.map(function(v, idx){
    var badges = [];
    if (v.changed) badges.push('<span class="pill pill-chg">🔄 ' + v.changed + ' alterado(s)</span>');
    if (v.new)     badges.push('<span class="pill pill-new">🆕 ' + v.new + ' novo(s)</span>');
    if (v.same)    badges.push('<span class="pill pill-same">✅ ' + v.same + ' estável(is)</span>');
    if (v.errors)  badges.push('<span class="pill pill-err">⚠️ ' + v.errors + ' erro(s)</span>');
    var comps = (v.competitors && v.competitors.length) ? ' · ' + esc(v.competitors.join(', ')) : '';
    return (
      '<div class="ver-item">' +
        '<div>' +
          '<div class="ver-title">' +
            (idx === 0 ? '🟢 ' : '📄 ') + esc(v.created_at) +
            (idx === 0 ? ' <span class="sel-badge">Mais recente</span>' : '') +
          '</div>' +
          '<div class="ver-meta">' +
            '<span><code>' + esc(v.filename) + '</code> (' + esc(v.size_kb) + ' KB)</span>' +
            '<span>' + comps + '</span>' +
          '</div>' +
          '<div class="ver-meta" style="margin-top:6px">' + badges.join(' ') + '</div>' +
        '</div>' +
        '<a class="btn btn-primary" href="/reports/' + encodeURIComponent(v.filename) + '" target="_blank">Abrir HTML ↗</a>' +
      '</div>'
    );
  }).join('');
}

async function addSingle(e) {
  e.preventDefault();
  var url = document.getElementById('inp-url').value.trim();
  var name = document.getElementById('inp-name').value.trim();
  var sel = document.getElementById('inp-sel').value.trim();
  var res = await api('/api/add', {url: url, name: name || null, selector: sel || null});
  if (!res.ok) { showStatus('err', '❌ ' + esc(res.error)); return; }
  document.getElementById('form-single').reset();
  showStatus('done', '✅ Concorrente <strong>' + esc(res.added.name) + '</strong> adicionado.');
  loadState();
}

async function addBulk() {
  var raw = document.getElementById('inp-bulk').value.trim();
  if (!raw) return;
  var res = await api('/api/add_bulk', {lines: raw});
  if (!res.ok) { showStatus('err', '❌ ' + esc(res.error)); return; }
  document.getElementById('inp-bulk').value = '';
  showStatus('done', '✅ ' + res.added_count + ' URL(s) adicionada(s).' + (res.skipped.length ? ' Ignoradas: ' + esc(res.skipped.join(', ')) : ''));
  loadState();
}

async function toggleComp(name, enabled) {
  await api('/api/toggle', {name: name, enabled: enabled});
  loadState();
}

async function removeComp(name) {
  await api('/api/remove', {name: name});
  loadState();
}

async function runScraping(onlyNames) {
  var btn = document.getElementById('btn-run-all');
  btn.disabled = true;
  var targetTxt = onlyNames ? ' (' + esc(onlyNames.join(', ')) + ')' : ' de todas as URLs ativas';
  showStatus('running', '<span><span class="spinner"></span> Fazendo Web Scraping e gerando análise estratégica' + targetTxt + '…</span>');
  try {
    var res = await api('/api/run', {only: onlyNames || null});
    if (!res.ok) {
      showStatus('err', '❌ ' + esc(res.error));
    } else {
      showStatus(
        'done',
        '<span>✅ Web Scraping concluído! Versão salva: <code>' + esc(res.filename) + '</code></span>' +
        '<a class="btn btn-primary" href="' + esc(res.report_url) + '" target="_blank">Abrir Relatório Gerado ↗</a>'
      );
      window.open(res.report_url, '_blank');
      loadState();
    }
  } catch (err) {
    showStatus('err', '❌ Erro ao executar scraping: ' + esc(err));
  } finally {
    btn.disabled = false;
  }
}

loadState();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------------------
# Servidor HTTP Local
# --------------------------------------------------------------------------------------
class AppHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        pass  # silencia log por request no console

    def _send_json(self, data: dict, status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_html(self, content: str, status: int = 200) -> None:
        raw = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._send_html(UI_HTML)
            return

        if path == "/api/state":
            cfg = cm.load_config(CONFIG_PATH)
            self._send_json({
                "competitors": cfg["competitors"],
                "versions": list_report_versions(),
            })
            return

        if path == "/latest":
            cfg = cm.load_config(CONFIG_PATH)
            latest = BASE_DIR / f"{cfg['output'].get('report_file', 'relatorio_competitivo')}.html"
            if latest.exists():
                self._send_html(latest.read_text(encoding="utf-8"))
            else:
                self._send_html("<h3>Nenhum relatório gerado ainda. Volte à <a href='/'>central</a> e clique em Rodar Web Scraping.</h3>", 404)
            return

        if path.startswith("/reports/"):
            cfg = cm.load_config(CONFIG_PATH)
            reports_dir = (BASE_DIR / cfg["output"].get("reports_dir", "relatorios_html")).resolve()
            fname = Path(path.replace("/reports/", "", 1)).name
            target = (reports_dir / fname).resolve()
            if target.parent == reports_dir and target.exists() and target.suffix.lower() == ".html":
                self._send_html(target.read_text(encoding="utf-8"))
                return
            self._send_html("<h3>Versão de relatório não encontrada.</h3>", 404)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_body()
            cfg = cm.load_config(CONFIG_PATH)

            if path == "/api/add":
                comp = cm.add_competitor(cfg, body.get("url", ""), body.get("name"), body.get("selector"))
                cm.save_config(CONFIG_PATH, cfg)
                self._send_json({"ok": True, "added": comp})
                return

            if path == "/api/add_bulk":
                raw_lines = (body.get("lines") or "").splitlines()
                added, skipped = 0, []
                for line in raw_lines:
                    line = line.strip()
                    if not line:
                        continue
                    parts = [p.strip() for p in line.split("|")]
                    url = parts[0]
                    name = parts[1] if len(parts) > 1 and parts[1] else None
                    sel = parts[2] if len(parts) > 2 and parts[2] else None
                    try:
                        cm.add_competitor(cfg, url, name, sel)
                        added += 1
                    except cm.ConfigError as exc:
                        skipped.append(f"{url} ({exc})")
                cm.save_config(CONFIG_PATH, cfg)
                self._send_json({"ok": True, "added_count": added, "skipped": skipped})
                return

            if path == "/api/toggle":
                cm.set_enabled(cfg, body.get("name", ""), bool(body.get("enabled", True)))
                cm.save_config(CONFIG_PATH, cfg)
                self._send_json({"ok": True})
                return

            if path == "/api/remove":
                cm.remove_competitor(cfg, body.get("name", ""))
                cm.save_config(CONFIG_PATH, cfg)
                self._send_json({"ok": True})
                return

            if path == "/api/run":
                only = body.get("only")
                res = run_scraping_job(only_names=only)
                self._send_json(res)
                return

            self.send_error(HTTPStatus.NOT_FOUND)
        except cm.ConfigError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"ok": False, "error": f"Erro interno: {exc}"}, status=500)


def _find_port(preferred: int = 8765) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_ui(port: int = 8765, open_browser: bool = True) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    actual_port = _find_port(port)
    url = f"http://127.0.0.1:{actual_port}/"
    server = ThreadingHTTPServer(("127.0.0.1", actual_port), AppHandler)
    print(f"🌐 Central de Web Scraping ativa em: {url}")
    print("   (Pressione Ctrl+C no terminal para encerrar)")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrando servidor local…")
        server.server_close()


if __name__ == "__main__":
    start_ui()

