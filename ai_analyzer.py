"""
ai_analyzer.py — Camada de IA local e extração de sinais estratégicos para análise competitiva.

Backends disponíveis:
  * OllamaAnalyzer    -> LLM local (Google Gemma 3 via Ollama). 100% offline, privado, sem custo.
  * HeuristicAnalyzer -> Fallback sem LLM (extração estruturada por categorias estratégicas).
                         Garante que o projeto rode em qualquer máquina, mesmo sem modelo instalado.

Funções de inteligência competitiva (sempre executadas sobre o texto raspado):
  * extract_strategic_signals(lines) -> agrupa frases coletadas por tema estratégico de PM
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

import requests

log = logging.getLogger(__name__)

SYSTEM_ROLE = (
    "Você é um analista sênior de Inteligência Competitiva apoiando um Product Manager. "
    "Responda SEMPRE em português do Brasil, em Markdown conciso (bullets), sem inventar "
    "fatos que não estejam no texto fornecido."
)

# --------------------------------------------------------------------------------------
# Taxonomia de Inteligência Competitiva (extraída diretamente do web scraping)
# --------------------------------------------------------------------------------------
STRATEGIC_CATEGORIES: dict[str, dict] = {
    "ai": {
        "label": "IA & Agentes",
        "icon": "🤖",
        "color": "#7c3aed",
        "keywords": {
            "ai": 3, "ia": 3, "agent": 3, "agents": 3, "agente": 3, "agentes": 3,
            "gpt": 3, "llm": 3, "copilot": 3, "model": 2, "models": 2, "modelo": 2,
            "prompt": 2, "generative": 3, "autonom": 2, "chat": 1, "claude": 3,
            "openai": 3, "gemini": 3, "gemma": 3, "mcp": 3, "byok": 3, "automation": 2,
            "automação": 2,
        },
    },
    "pricing": {
        "label": "Preço & Monetização",
        "icon": "💰",
        "color": "#059669",
        "keywords": {
            "pricing": 4, "price": 3, "preço": 4, "preços": 4, "plan": 2, "plans": 3,
            "plano": 2, "planos": 3, "free": 2, "grátis": 2, "gratuito": 2,
            "pro": 2, "plus": 2, "tier": 3, "credit": 3, "credits": 3, "crédito": 3,
            "billing": 3, "subscription": 3, "assinatura": 3, "cost": 2, "custo": 2,
            "cheaper": 3, "discount": 2, "trial": 2, "markup": 3,
        },
    },
    "launch": {
        "label": "Lançamentos & Produto",
        "icon": "🚀",
        "color": "#2563eb",
        "keywords": {
            "launch": 3, "launched": 3, "launches": 3, "lançamento": 3, "lança": 3,
            "introducing": 4, "introduce": 3, "announcing": 3, "new": 2, "novo": 2,
            "nova": 2, "novos": 2, "release": 2, "releases": 2, "beta": 3,
            "preview": 2, "redesign": 3, "rebuilt": 3, "upgrade": 2, "upgrades": 2,
            "feature": 2, "funcionalidade": 2, "composer": 2, "workflow": 2,
        },
    },
    "ecosystem": {
        "label": "Ecossistema & API",
        "icon": "🔌",
        "color": "#0284c7",
        "keywords": {
            "integration": 3, "integrations": 3, "integração": 3, "integrações": 3,
            "api": 3, "sdk": 3, "webhook": 3, "webhooks": 3, "connector": 3,
            "connectors": 3, "conector": 3, "plugin": 3, "plugins": 3,
            "extension": 2, "github": 2, "slack": 2, "drive": 2, "jira": 2,
            "figma": 1, "notion": 1, "linear": 1, "import": 2, "export": 2,
            "sync": 2, "partner": 3, "partnership": 3, "parceria": 3,
        },
    },
    "enterprise": {
        "label": "Enterprise & Segurança",
        "icon": "🛡️",
        "color": "#d97706",
        "keywords": {
            "enterprise": 4, "security": 3, "segurança": 3, "sso": 4, "saml": 4,
            "scim": 4, "audit": 3, "auditoria": 3, "compliance": 3, "soc2": 4,
            "gdpr": 3, "lgpd": 3, "permission": 3, "permissions": 3, "permissão": 3,
            "admin": 2, "governance": 3, "governança": 3, "privacy": 2,
            "privacidade": 2, "role": 2, "workspace": 1, "controls": 2,
        },
    },
    "ux_mobile": {
        "label": "Mobile & Performance",
        "icon": "📱",
        "color": "#db2777",
        "keywords": {
            "mobile": 3, "ios": 3, "android": 3, "desktop": 2, "macos": 2,
            "windows": 2, "app": 1, "faster": 3, "rápido": 3, "speed": 2,
            "performance": 3, "desempenho": 3, "latency": 3, "offline": 3,
        },
    },
}


def classify_line(line: str) -> list[tuple[str, int]]:
    """Retorna [(cat_key, score), ...] ordenado por score decrescente para uma linha."""
    tokens = re.findall(r"[a-zA-ZÀ-ÿ0-9]+", line.lower())
    if not tokens:
        return []
    matches: list[tuple[str, int]] = []
    for cat_key, meta in STRATEGIC_CATEGORIES.items():
        kw = meta["keywords"]
        score = sum(kw.get(t, 0) for t in tokens)
        if score >= 2:
            matches.append((cat_key, score))
    matches.sort(key=lambda x: -x[1])
    return matches


def extract_strategic_signals(lines: Iterable[str], max_per_category: int = 8) -> dict[str, dict]:
    """
    Analisa as linhas coletadas no scraping e estrutura os sinais estratégicos por categoria.
    Retorna:
      {
        cat_key: {
          "label": str, "icon": str, "color": str,
          "count": int,            # total de linhas que bateram na categoria
          "highlights": list[str]  # principais linhas ordenadas por relevância
        }
      }
    """
    buckets: dict[str, list[tuple[int, int, str]]] = {k: [] for k in STRATEGIC_CATEGORIES}
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        for cat_key, score in classify_line(line):
            buckets[cat_key].append((score, idx, line))

    signals: dict[str, dict] = {}
    for cat_key, meta in STRATEGIC_CATEGORIES.items():
        items = buckets[cat_key]
        # Ordena por score desc, depois pela ordem original na página (mais recente no topo)
        top = sorted(items, key=lambda x: (-x[0], x[1]))[:max_per_category]
        top_ordered = [line for _, _, line in sorted(top, key=lambda x: x[1])]
        signals[cat_key] = {
            "label": meta["label"],
            "icon": meta["icon"],
            "color": meta["color"],
            "count": len(items),
            "highlights": top_ordered,
        }
    return signals


# --------------------------------------------------------------------------------------
# Backend 1: LLM local (Gemma via Ollama)
# --------------------------------------------------------------------------------------
class OllamaAnalyzer:
    """Usa a API REST local do Ollama (http://localhost:11434) para rodar o Gemma offline."""

    def __init__(self, model: str, host: str, temperature: float = 0.2,
                 timeout: int = 180, max_input_chars: int = 12000):
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout
        self.max_input_chars = max_input_chars

    @property
    def label(self) -> str:
        return f"LLM local · {self.model} (Ollama)"

    def is_available(self) -> bool:
        """Verifica se o servidor Ollama está ativo e se o modelo já foi baixado."""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=3)
            resp.raise_for_status()
            models = {m.get("name", "") for m in resp.json().get("models", [])}
            if self.model in models or f"{self.model}:latest" in models:
                return True
            log.warning("Ollama ativo, mas o modelo '%s' não foi encontrado. "
                        "Rode: ollama pull %s", self.model, self.model)
        except (requests.RequestException, ValueError, AttributeError):
            log.warning("Servidor Ollama não encontrado em %s.", self.host)
        return False

    def _generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "system": SYSTEM_ROLE,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        resp = requests.post(f"{self.host}/api/generate", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()

    def _clip(self, text: str) -> str:
        return text if len(text) <= self.max_input_chars else text[: self.max_input_chars] + "\n[...]"

    def summarize(self, name: str, url: str, text: str) -> str:
        prompt = (
            f"Concorrente: {name}\nFonte: {url}\n\n"
            "Analise o conteúdo coletado desta página e estruture o relatório de inteligência competitiva:\n"
            "1. **Principais entregas e novidades** (até 5 bullets objetivos)\n"
            "2. **Posicionamento e sinais estratégicos** (foco em IA, preço/monetização, enterprise, ecossistema)\n"
            "3. **Nível de ameaça**: Baixo / Médio / Alto — com 1 frase de justificativa\n"
            "4. **Recomendações para o PM** (2 ações práticas para o nosso roadmap)\n\n"
            f"Conteúdo da página:\n\"\"\"\n{self._clip(text)}\n\"\"\""
        )
        return self._generate(prompt)

    def analyze_changes(self, name: str, url: str, added: list[str], removed: list[str]) -> str:
        added_txt = "\n".join(f"+ {l}" for l in added) or "(nenhum)"
        removed_txt = "\n".join(f"- {l}" for l in removed) or "(nenhum)"
        prompt = (
            f"Concorrente: {name}\nFonte: {url}\n\n"
            "Abaixo está o DIFF entre a versão anterior e a atual da página.\n"
            "Analise e responda em Markdown:\n"
            "1. **O que mudou** (bullets objetivos)\n"
            "2. **Leitura estratégica** (por que isso importa? qual movimento de mercado?)\n"
            "3. **Nível de ameaça**: Baixo / Médio / Alto — com 1 frase de justificativa\n"
            "4. **Ação recomendada para o PM** (1-2 bullets)\n"
            "Ignore mudanças triviais (datas, contadores, rodapés).\n\n"
            f"CONTEÚDO ADICIONADO:\n{self._clip(added_txt)}\n\n"
            f"CONTEÚDO REMOVIDO:\n{self._clip(removed_txt)}"
        )
        return self._generate(prompt)

    def executive_summary(self, results: list[dict]) -> str:
        blocks = [
            f"### {r['name']} ({r['status']})\n{r.get('analysis', '')}"
            for r in results if r.get("analysis") and r["status"] != "Erro"
        ]
        if not blocks:
            return "_Nenhum dado estratégico disponível neste ciclo._"
        prompt = (
            "Com base nas análises individuais abaixo, escreva um **Resumo Executivo** "
            "para a liderança de produto com no máximo 6 bullets: principais movimentos "
            "do mercado, tendências comuns entre concorrentes e as 2 prioridades de ação.\n\n"
            + self._clip("\n\n".join(blocks))
        )
        return self._generate(prompt)


# --------------------------------------------------------------------------------------
# Backend 2: Analisador Heurístico Estruturado (sem LLM)
# --------------------------------------------------------------------------------------
class HeuristicAnalyzer:
    """Análise extrativa estruturada por temas de PM. Zero dependências, roda em qualquer lugar."""

    label = "Motor Heurístico de Sinais Estratégicos (offline)"

    def __init__(self, top_n: int = 6):
        self.top_n = top_n

    @staticmethod
    def _score(line: str) -> int:
        return sum(s for _, s in classify_line(line))

    def _top_lines(self, lines: Iterable[str], limit: int | None = None) -> list[str]:
        n = limit or self.top_n
        scored = [(self._score(l), i, l) for i, l in enumerate(lines)]
        best = sorted((s for s in scored if s[0] > 0), key=lambda x: (-x[0], x[1]))[:n]
        return [l[:260] for _, _, l in sorted(best, key=lambda x: x[1])]

    @staticmethod
    def _estimate_threat(signals: dict[str, dict], is_change: bool = False, added_count: int = 0) -> tuple[str, str]:
        ai_c = signals.get("ai", {}).get("count", 0)
        pr_c = signals.get("pricing", {}).get("count", 0)
        en_c = signals.get("enterprise", {}).get("count", 0)
        la_c = signals.get("launch", {}).get("count", 0)
        total_hot = ai_c + pr_c * 2 + en_c * 2 + la_c
        if pr_c >= 3 or (ai_c >= 6 and la_c >= 4) or (is_change and added_count >= 10 and total_hot >= 8):
            return "Alto", "Forte movimentação em precificação/planos ou múltiplos lançamentos de IA e produto."
        if total_hot >= 6 or (is_change and added_count >= 3):
            return "Médio", "Entregas ativas em funcionalidades de produto, integrações ou recursos de IA."
        return "Baixo", "Atualizações incrementais ou de manutenção sem mudança brusca de posicionamento."

    def summarize(self, name: str, url: str, text: str) -> str:
        lines = text.splitlines()
        signals = extract_strategic_signals(lines, max_per_category=3)
        active_cats = [(k, v) for k, v in signals.items() if v["count"] > 0]
        active_cats.sort(key=lambda x: -x[1]["count"])

        threat, reason = self._estimate_threat(signals)
        top = self._top_lines(lines, limit=5)

        out = ["1. **Principais entregas e destaques detectados no scraping**"]
        if top:
            out.extend(f"- {l}" for l in top)
        else:
            sample_lines = [l[:220] for l in lines[:8] if len(l.strip()) >= 8]
            out.extend(f"- {l}" for l in sample_lines) if sample_lines else out.append("- Nenhum destaque textual encontrado.")

        out.append("2. **Foco estratégico e estrutura identificada na página**")
        if active_cats:
            for _, meta in active_cats[:4]:
                sample = meta["highlights"][0][:160] if meta["highlights"] else ""
                out.append(f"- **{meta['icon']} {meta['label']}** ({meta['count']} menções) — ex.: _{sample}_")
        else:
            out.append(f"- Página monitorada com **{len(lines)} itens/linhas capturadas** (consulte a aba **Conteúdo Coletado** para ver todos os itens).")

        out.append(f"3. **Nível de ameaça**: {threat} — {reason}")
        out.append("4. **Pontos de atenção para o PM**")
        if signals["pricing"]["count"] > 0:
            out.append("- Revisar posicionamento de preço/planos frente às condições citadas pelo concorrente.")
        if signals["ai"]["count"] > 0:
            out.append("- Avaliar paridade das funcionalidades de IA/Agentes anunciadas.")
        if signals["ecosystem"]["count"] > 0:
            out.append("- Mapear conectores e integrações estratégicas mencionadas na página.")
        if len(out) == 4 + (1 if top else 1) + len(active_cats[:4]):
            out.append("- Manter monitoramento periódico para capturar próximos lançamentos.")
        return "\n".join(out)

    def analyze_changes(self, name: str, url: str, added: list[str], removed: list[str]) -> str:
        signals = extract_strategic_signals(added, max_per_category=3)
        threat, reason = self._estimate_threat(signals, is_change=True, added_count=len(added))
        top_added = self._top_lines(added, limit=6)
        top_removed = self._top_lines(removed, limit=3)

        out = [f"1. **O que mudou** (+{len(added)} linhas adicionadas / −{len(removed)} removidas)"]
        if top_added:
            out.extend(f"- {l}" for l in top_added)
        elif added:
            out.extend(f"- {l[:220]}" for l in added[:4])
        else:
            out.append("- Apenas remoção de conteúdo na página.")

        out.append("2. **Leitura estratégica das mudanças**")
        active_cats = [v for v in signals.values() if v["count"] > 0]
        active_cats.sort(key=lambda v: -v["count"])
        if active_cats:
            for meta in active_cats[:3]:
                out.append(f"- Movimento em **{meta['icon']} {meta['label']}** ({meta['count']} novas menções no diff).")
        else:
            out.append("- Alterações textuais sem sinais fortes de mudança de produto ou preço.")
        if top_removed:
            out.append(f"- Conteúdo relevante removido: _{top_removed[0][:160]}_")

        out.append(f"3. **Nível de ameaça**: {threat} — {reason}")
        out.append("4. **Ação recomendada para o PM**")
        out.append("- Inspecionar a aba **Mudanças (Diff)** deste concorrente para validar o impacto no nosso backlog.")
        return "\n".join(out)

    def executive_summary(self, results: list[dict]) -> str:
        valid = [r for r in results if r["status"] != "Erro"]
        changed = [r for r in results if r["status"] == "Alterado"]
        new = [r for r in results if r["status"] == "Novo"]
        same = [r for r in results if r["status"] == "Sem mudanças"]
        errors = [r for r in results if r["status"] == "Erro"]

        lines = []
        if changed:
            names = ", ".join(f"**{r['name']}** (+{r['added']}/−{r['removed']})" for r in changed)
            lines.append(f"- 🔄 **Mudanças detectadas nesta execução:** {names}.")
        else:
            lines.append(
                f"- ✅ **Estabilidade no ciclo atual:** nenhuma alteração textual desde a última coleta "
                f"({len(same)} concorrente(s) estável(is){', ' + str(len(new)) + ' novo(s)' if new else ''})."
            )

        # Agrega sinais estratégicos de todos os concorrentes válidos
        cat_totals: dict[str, list[tuple[str, int]]] = {k: [] for k in STRATEGIC_CATEGORIES}
        for r in valid:
            sigs = r.get("signals") or {}
            for k, meta in sigs.items():
                if meta.get("count", 0) > 0:
                    cat_totals[k].append((r["name"], meta["count"]))

        ranked = sorted(
            ((k, sum(c for _, c in lst), lst) for k, lst in cat_totals.items() if lst),
            key=lambda x: -x[1],
        )
        for k, total, lst in ranked[:3]:
            meta = STRATEGIC_CATEGORIES[k]
            breakdown = ", ".join(f"{n}: {c}" for n, c in sorted(lst, key=lambda x: -x[1]))
            lines.append(f"- {meta['icon']} **Tema dominante — {meta['label']}:** {total} sinais mapeados ({breakdown}).")

        high_threat = [r["name"] for r in valid if "Alto" in (r.get("analysis") or "")]
        if high_threat:
            lines.append(f"- 🚨 **Atenção prioritária (Ameaça Alta):** {', '.join(high_threat)}.")
        if errors:
            lines.append(f"- ⚠️ **Falha de coleta:** {', '.join(r['name'] for r in errors)}.")
        return "\n".join(lines)


# --------------------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------------------
def build_analyzer(ai_cfg: dict, force_heuristic: bool = False):
    """Escolhe o backend: tenta o LLM local e cai para o heurístico se não estiver disponível."""
    if force_heuristic or ai_cfg.get("backend", "ollama") == "heuristic":
        return HeuristicAnalyzer()

    analyzer = OllamaAnalyzer(
        model=ai_cfg.get("model", "gemma3:4b"),
        host=ai_cfg.get("host", "http://localhost:11434"),
        temperature=ai_cfg.get("temperature", 0.2),
        timeout=ai_cfg.get("timeout_seconds", 180),
        max_input_chars=ai_cfg.get("max_input_chars", 12000),
    )
    if analyzer.is_available():
        return analyzer

    log.warning("Usando motor heurístico estruturado (fallback sem LLM).")
    return HeuristicAnalyzer()
