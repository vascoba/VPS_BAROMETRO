"""Gera um site/data.json inicial a partir do Excel (folhas JCOVAS_MENSAL e MACRO TRIMESTRAL).

Uso único, no computador de quem tem o Excel:
    pip install openpyxl
    python scripts/seed_from_excel.py "caminho/Portugal RE Report Data Model.xlsx"

Serve para a página nascer com dados reais antes da primeira execução do robô, que depois
substitui tudo pelos dados diretos das fontes (com a frequência original de cada série).
"""
import calendar
import datetime as dt
import json
import os
import sys

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import barometro as b  # noqa: E402
from update import CONFIG, DATA, escrever_data, agora, ler_json  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ler_folha(ws, linha_chave, linha_cab, col0):
    """{chave: [(data, valor), ...]} para as colunas a partir de col0."""
    out = {}
    for c in range(col0, ws.max_column + 1):
        chave = ws.cell(linha_chave, c).value
        if chave in (None, ""):
            continue
        pts = []
        for r in range(linha_cab + 1, ws.max_row + 1):
            d, v = ws.cell(r, 2).value, ws.cell(r, c).value
            if isinstance(d, dt.datetime) and isinstance(v, (int, float)):
                pts.append((d.date(), float(v)))
        out[str(chave)] = pts
    return out


def fim_mes(ano, mes):
    return dt.date(ano, mes, calendar.monthrange(ano, mes)[1])


def main(caminho):
    cfg = ler_json(CONFIG)
    wb = openpyxl.load_workbook(caminho, data_only=True)
    jc = ler_folha(wb["JCOVAS_MENSAL"], 4, 5, 4)
    mac = ler_folha(wb["MACRO TRIMESTRAL"], 4, 5, 4)
    extra = ler_json(os.path.join(RAIZ, "scripts", "seed_bpstat_mensal.json"))

    series = []
    for s in cfg["series"]:
        if s["fonte"] in ("INE", "Eurostat") or s["id"] == "BPSTAT_12748362":
            pts = jc[s["id"]]
            serie = b.construir_serie(s, pts)
            if "comparar" in s:
                b.anexar_comparacao(serie, s["comparar"], jc[s["comparar"]["id"]])
        else:
            cod = s["codigo"]
            if cod in extra["mensais"]:
                m = extra["mensais"][cod]
                u = dt.date.fromisoformat(m["ultima"])
                n = len(m["valores"])
                pts = []
                for i, v in enumerate(m["valores"]):
                    k = u.year * 12 + (u.month - 1) - (n - 1 - i)
                    pts.append((fim_mes(k // 12, k % 12 + 1), v))
                serie = b.construir_serie(s, pts, freq="M")
            elif cod == "12504591":
                pts = []
                for linha in extra["bce"]["alteracoes"] + [extra["bce"]["ultima_observacao"]]:
                    d, v = linha.split(":")
                    pts.append((dt.date.fromisoformat(d), float(v)))
                serie = b.construir_serie(s, pts, freq="E")
            else:
                pts = [(d, v * 100 if s["var"] == "pp" else v) for d, v in mac[cod]]  # Excel guarda % em fração
                serie = b.construir_serie(s, pts, freq="T")
        serie["seed"] = True
        series.append(serie)
    escrever_data(DATA, {"atualizado": agora(), "grupos": cfg["grupos"], "series": series})
    print("escrito", DATA, len(series), "séries")


if __name__ == "__main__":
    main(sys.argv[1])
