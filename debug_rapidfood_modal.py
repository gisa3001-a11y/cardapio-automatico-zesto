"""Diagnóstico somente-leitura dos modais reais do RapidFood.

Não altera parser/XLSX e não envia pedido. Abre alguns produtos que já possuem
handler openProductModal e registra sinais de escolhas/adicionais no DOM e rede.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

URL = "https://rapidfood.com.br/panelamineira"
OUT = Path("artifacts/rapidfood_modal.json")
OPTION_RE = re.compile(r"adicional|complement|op[cç][aã]o|escolh|sabor|tamanho|borda|extra|acompanh", re.I)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def main() -> int:
    report: dict[str, Any] = {"url": URL, "final_url": "", "candidates": 0, "opened": 0, "samples": [], "requests": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(locale="pt-BR", viewport={"width": 1440, "height": 1200})

        def on_response(resp):
            try:
                req = resp.request
                if req.resource_type not in ("xhr", "fetch"):
                    return
                u = resp.url
                if "rapidfood.com.br" not in u:
                    return
                report["requests"].append({
                    "url": u,
                    "method": req.method,
                    "status": resp.status,
                    "resource_type": req.resource_type,
                })
            except Exception:
                pass

        page.on("response", on_response)
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        page.wait_for_timeout(1200)
        report["final_url"] = page.url

        candidates = page.locator("[onclick*='openProductModal']")
        count = candidates.count()
        report["candidates"] = count

        # Amostra distribuída para não concluir pela primeira categoria apenas.
        indexes = []
        for idx in (0, 1, 2, count // 3, count // 2, (2 * count) // 3, count - 2, count - 1):
            if 0 <= idx < count and idx not in indexes:
                indexes.append(idx)

        for idx in indexes[:8]:
            el = candidates.nth(idx)
            onclick = el.get_attribute("onclick") or ""
            text = _clean(el.inner_text(timeout=3000))[:500]
            before_requests = len(report["requests"])
            try:
                el.scroll_into_view_if_needed(timeout=3000)
                el.click(timeout=5000)
                page.wait_for_timeout(700)
            except Exception as exc:
                report["samples"].append({"index": idx, "card_text": text, "onclick": onclick[:1200], "erro": str(exc)})
                continue

            # RapidFood usa modal Bootstrap; preferimos apenas elementos visíveis.
            modal = page.locator(".modal.show, [role='dialog']:visible").last
            if modal.count() == 0:
                modal = page.locator("body")
            try:
                modal_text = _clean(modal.inner_text(timeout=3000))[:5000]
            except Exception:
                modal_text = ""

            controls = []
            try:
                nodes = modal.locator("input, select, textarea")
                for j in range(min(nodes.count(), 80)):
                    node = nodes.nth(j)
                    typ = (node.get_attribute("type") or node.evaluate("e => e.tagName.toLowerCase()") or "").lower()
                    name = node.get_attribute("name") or ""
                    value = node.get_attribute("value") or ""
                    ident = node.get_attribute("id") or ""
                    label = ""
                    if ident:
                        lab = modal.locator(f"label[for='{ident}']")
                        if lab.count():
                            label = _clean(lab.first.inner_text(timeout=1000))
                    if not label:
                        try:
                            label = _clean(node.evaluate("e => e.closest('label')?.innerText || ''"))
                        except Exception:
                            pass
                    controls.append({"type": typ, "name": name, "value": value, "label": label[:300]})
            except Exception:
                pass

            headings = []
            try:
                heading_nodes = modal.locator("h1,h2,h3,h4,h5,h6,label,legend")
                for j in range(min(heading_nodes.count(), 80)):
                    t = _clean(heading_nodes.nth(j).inner_text(timeout=1000))
                    if t and (OPTION_RE.search(t) or len(t) <= 120):
                        headings.append(t)
            except Exception:
                pass

            option_controls = [c for c in controls if c["type"] in ("radio", "checkbox", "select")]
            report["samples"].append({
                "index": idx,
                "card_text": text,
                "onclick": onclick[:1200],
                "modal_text": modal_text,
                "controls": controls,
                "option_controls": option_controls,
                "headings": headings[:50],
                "optionish_text": bool(OPTION_RE.search(modal_text)),
                "new_requests": report["requests"][before_requests:],
            })
            report["opened"] += 1

            try:
                close = page.locator(".modal.show [data-bs-dismiss='modal'], .modal.show [data-dismiss='modal'], .modal.show .btn-close, .modal.show .close").first
                if close.count():
                    close.click(timeout=2000)
                else:
                    page.keyboard.press("Escape")
                page.wait_for_timeout(250)
            except Exception:
                page.keyboard.press("Escape")

        browser.close()

    report["samples_with_option_controls"] = sum(bool(x.get("option_controls")) for x in report["samples"])
    report["samples_with_optionish_text"] = sum(bool(x.get("optionish_text")) for x in report["samples"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "candidates": report["candidates"],
        "opened": report["opened"],
        "samples_with_option_controls": report["samples_with_option_controls"],
        "samples_with_optionish_text": report["samples_with_optionish_text"],
        "xhr_fetch": len(report["requests"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
