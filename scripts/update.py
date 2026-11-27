"""Vai buscar os dados ao INE, ao BPstat e ao Eurostat e escreve site/data.json e site/status.json.

Se uma fonte falhar, mantém os valores anteriores dessa fonte (marcados como desatualizados)
e a página continua a funcionar. Só sai com erro se NENHUMA fonte responder.
"""
import datetime as dt
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import barometro as b  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(RAIZ, "config", "series.json")
DATA = os.path.join(RAIZ, "site", "data.json")
STATUS = os.path.join(RAIZ, "site", "status.json")


def agora():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ler_json(caminho):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def escrever_data(caminho, doc):
    """Uma série por linha, para o histórico do Git ser legível."""
    with open(caminho, "w", encoding="utf-8", newline="\n") as f:
        f.write('{"versao": 1, "atualizado": %s,\n"grupos": %s,\n"series": [\n' % (json.dumps(doc["atualizado"]), json.dumps(doc["grupos"], ensure_ascii=False)))
        f.write(",\n".join(json.dumps(s, ensure_ascii=False, separators=(",", ":")) for s in doc["series"]))
        f.write("\n]}\n")


def recolher_bpstat(series):
    ids = sorted({s["codigo"] for s in series})
    texto = b.obter(b.BPSTAT_URL, {"series_ids": ",".join(ids), "language": "EN"}, codificacao="cp1252")
    dados = b.parse_bpstat(texto)
    out = {}
    for s in series:
        pts = dados.get(s["codigo"])
        if not pts:
            raise RuntimeError("BPstat não devolveu a série %s" % s["codigo"])
        out[s["id"]] = b.construir_serie(s, pts)
    return out


def recolher_eurostat(series):
    geos = []
    for s in series:
        geos.append(s["codigo"])
        if "comparar" in s:
            geos.append(s["comparar"]["codigo"])
    texto = b.obter(b.EUROSTAT_URL + "+".join(geos), {"format": "SDMX-CSV", "startPeriod": "2005-Q1"})
    dados = b.parse_eurostat(texto)
    out = {}
    for s in series:
        pts = dados.get(s["codigo"])
        if not pts:
            raise RuntimeError("Eurostat não devolveu %s" % s["codigo"])
        serie = b.construir_serie(s, pts)
        if "comparar" in s:
            b.anexar_comparacao(serie, s["comparar"], dados.get(s["comparar"]["codigo"], []))
        out[s["id"]] = serie
    return out


def recolher_ine_uma(s):
    texto = b.obter(b.INE_URL, {"op": "2", "varcd": s["codigo"], "Dim1": "T", "Dim2": "PT", "lang": "PT"})
    pts = b.parse_ine(json.loads(texto), s.get("ine_rotulo", ["total"]))
    if not pts:
        raise RuntimeError("INE sem dados para %s" % s["codigo"])
    return s["id"], b.construir_serie(s, pts)


def recolher_ine(series):
    # a API do INE é lenta: 4 pedidos de cada vez, sem exagerar
    erros, out = [], {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futuros = [(s, ex.submit(recolher_ine_uma, s)) for s in series]
    for s, f in futuros:
        try:
            k, v = f.result()
            out[k] = v
        except Exception as e:  # noqa: BLE001
            erros.append("%s: %s" % (s["id"], e))
    if erros:
        # devolve o que conseguiu; o chamador completa o resto com os valores anteriores
        out["__erros__"] = erros
    return out


FONTES = {"BPstat": recolher_bpstat, "Eurostat": recolher_eurostat, "INE": recolher_ine}


def main():
    cfg = ler_json(CONFIG)
    anterior = ler_json(DATA) or {"series": []}
    ant_por_id = {s["id"]: s for s in anterior["series"]}
    novas, estado = {}, {}

    for fonte, fn in FONTES.items():
        series = [s for s in cfg["series"] if s["fonte"] == fonte]
        try:
            res = fn(series)
            erros = res.pop("__erros__", [])
            novas.update(res)
            estado[fonte] = {"ok": not erros, "erros": erros}
        except Exception as e:  # noqa: BLE001
            estado[fonte] = {"ok": False, "erros": [str(e)]}
        if estado[fonte]["erros"]:
            for e in estado[fonte]["erros"]:
                print("::warning::%s – %s" % (fonte, e))

    if not novas:
        print("::error::nenhuma fonte respondeu")
        sys.exit(1)

    finais = []
    for s in cfg["series"]:
        nova = novas.get(s["id"])
        if nova is None and s["id"] in ant_por_id:
            nova = dict(ant_por_id[s["id"]], desatualizado=True)
        if nova is not None:
            finais.append(nova)

    mudou = json.dumps(finais, sort_keys=True) != json.dumps(anterior["series"], sort_keys=True)
    doc = {"atualizado": agora() if mudou else anterior.get("atualizado", agora()), "grupos": cfg["grupos"], "series": finais}
    if mudou:
        escrever_data(DATA, doc)

    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump({"verificado": agora(), "fontes": estado}, f, ensure_ascii=False)
    print("séries: %d | alterado: %s | fontes: %s" % (len(finais), mudou,
          {k: ("ok" if v["ok"] else "erro") for k, v in estado.items()}))


if __name__ == "__main__":
    main()
