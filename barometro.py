"""Núcleo do barómetro: leitura das APIs (INE, BPstat, Eurostat) e cálculo dos indicadores.

Só usa a biblioteca padrão do Python. Cada função de leitura (`parse_*`) recebe o texto
devolvido pela API e devolve listas de pares (data, valor); `construir_serie` transforma
esses pares na estrutura que a página mostra.
"""
import csv
import datetime as dt
import io
import json
import re
import time
import urllib.parse
import urllib.request

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

BPSTAT_URL = "https://bpstat.bportugal.pt/api/observations/csv/"
INE_URL = "https://www.ine.pt/ine/json_indicador/pindica.jsp"
EUROSTAT_URL = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data/prc_hpi_q/Q.TOTAL.RCH_A."


# ---------------------------------------------------------------- leitura das APIs
def parse_bpstat(texto):
    """CSV do BPstat (separador ';'). Devolve {codigo_serie: [(data, valor), ...]}.

    As linhas vêm fora de ordem e a taxa BCE vem diária; a ordenação e a redução
    fazem-se em `normalizar`.
    """
    out = {}
    for linha in csv.reader(io.StringIO(texto), delimiter=";"):
        if len(linha) < 6 or not linha[0] or linha[0].startswith("#"):
            continue
        try:
            data = dt.date.fromisoformat(linha[4].strip())
            valor = float(linha[5].strip())
        except ValueError:
            continue
        out.setdefault(linha[0].strip(), []).append((data, valor))
    return out


def parse_eurostat(texto):
    """SDMX-CSV do Eurostat (prc_hpi_q). Devolve {geo: [(data, valor), ...]}."""
    out = {}
    for r in csv.DictReader(io.StringIO(texto)):
        try:
            ano, trim = r["TIME_PERIOD"].split("-Q")
            data = dt.date(int(ano), int(trim) * 3 - 2, 1)
            valor = float(r["OBS_VALUE"])
        except (KeyError, ValueError):
            continue
        out.setdefault(r["geo"].split(":")[0], []).append((data, valor))
    return out


def data_ine(periodo):
    """'Outubro de 2026' -> 2026-10-01; '2.º Trimestre de 2026' -> 2026-04-01; '2026' -> 2026-01-01."""
    p = periodo.lower()
    ano = int(re.sub(r"\D", "", p)[-4:])
    if "trimestre" in p:
        q = int(re.search(r"[1-4]", p).group())
        return dt.date(ano, q * 3 - 2, 1)
    for i, m in enumerate(MESES):
        if m in p:
            return dt.date(ano, i + 1, 1)
    return dt.date(ano, 1, 1)


def parse_ine(obj, palavras, geo="PT"):
    """JSON do INE. Em cada período há várias linhas (por tipo, local...); escolhe a que
    tem mais palavras de `palavras` no rótulo, como faz a query do Excel."""
    ind = obj[0]
    if "Dados" not in ind:
        raise ValueError("resposta do INE sem dados: %s" % json.dumps(ind.get("Sucesso", ind))[:200])
    out = []
    for periodo, linhas in ind["Dados"].items():
        melhor, melhor_score = None, -1
        for r in linhas:
            if r.get("geocod") != geo or r.get("valor") in (None, ""):
                continue
            rotulo = " / ".join(str(v) for k, v in r.items() if k.startswith("dim_") and k.endswith("_t")).lower()
            score = sum(1 for p in palavras if p in rotulo)
            if score > melhor_score:
                melhor, melhor_score = r, score
        if melhor is not None:
            out.append((data_ine(periodo), float(str(melhor["valor"]).replace(",", ".").replace(" ", ""))))
    return out


# ---------------------------------------------------------------- períodos
def chave(d, freq):
    if freq == "M":
        return "%d-%02d" % (d.year, d.month)
    if freq == "T":
        return "%d-Q%d" % (d.year, (d.month - 1) // 3 + 1)
    return d.isoformat()


def deslocar(k, freq, n):
    """Chave n períodos antes (n>0)."""
    if freq == "M":
        a, m = map(int, k.split("-"))
        i = a * 12 + (m - 1) - n
        return "%d-%02d" % (i // 12, i % 12 + 1)
    a, q = k.split("-Q")
    i = int(a) * 4 + (int(q) - 1) - n
    return "%d-Q%d" % (i // 4, i % 4 + 1)


def normalizar(pontos, freq):
    """Ordena e reduz a um valor por período. Devolve [(chave, valor)].

    M/T: o último valor de cada mês/trimestre.
    E (taxas que só mudam em decisões, ex.: BCE): os pontos em que o valor muda, mais o
    último dia observado.
    """
    pontos = sorted(pontos)
    if freq in ("M", "T"):
        por = {}
        for d, v in pontos:
            por[chave(d, freq)] = v
        return sorted(por.items())
    out, ant = [], None
    for d, v in pontos:
        if v != ant:
            out.append((d.isoformat(), v))
            ant = v
    if pontos and out[-1][0] != pontos[-1][0].isoformat():
        out.append((pontos[-1][0].isoformat(), pontos[-1][1]))
    return out


# ---------------------------------------------------------------- cálculo
def _var(a, b, tipo):
    if b is None:
        return None
    if tipo == "pp":
        return round(a - b, 6)
    return round((a / b - 1) * 100, 6) if b else None


def construir_serie(cfg, pontos, freq=None, historico=True):
    """Estrutura final de um indicador: último valor, variações e histórico."""
    freq = freq or cfg["freq"]
    norm = normalizar(pontos, freq)
    if not norm:
        return None
    tipo = cfg["var"]
    ult_k, ult_v = norm[-1]
    s = {k: cfg[k] for k in ("id", "grupo", "subgrupo", "titulo", "unidade", "casas", "fonte", "codigo", "var") if k in cfg}
    s["freq"] = freq
    s["ultimo"] = {"p": ult_k, "v": round(ult_v, 6)}

    if freq == "E":
        # anterior: o nível anterior ao atual; ano: valor em vigor um ano antes
        s["vs_ant"] = None
        for k, v in reversed(norm[:-1]):
            if v != ult_v:
                # data em que o nível atual começou = primeiro ponto com ult_v depois deste
                ini = next(kk for kk, vv in norm if kk > k and vv == ult_v)
                s["vs_ant"] = {"p": ini, "d": _var(ult_v, v, tipo)}
                break
        alvo = (dt.date.fromisoformat(ult_k) - dt.timedelta(days=365)).isoformat()
        antes = [(k, v) for k, v in norm if k <= alvo]
        s["vs_ano"] = {"p": alvo, "d": _var(ult_v, antes[-1][1], tipo)} if antes else None
    else:
        d = dict(norm)
        for nome, n in (("vs_ant", 1), ("vs_ano", 12 if freq == "M" else 4)):
            k0 = deslocar(ult_k, freq, n)
            s[nome] = {"p": k0, "d": _var(ult_v, d.get(k0), tipo)} if k0 in d else None

    s["hist"] = [[k, round(v, 6)] for k, v in norm] if historico else []
    return s


def anexar_comparacao(serie, cfg_comp, pontos_comp):
    norm = normalizar(pontos_comp, serie["freq"])
    if norm:
        serie["comparar"] = {"id": cfg_comp["id"], "rotulo": cfg_comp["rotulo"],
                             "ultimo": {"p": norm[-1][0], "v": round(norm[-1][1], 6)},
                             "hist": [[k, round(v, 6)] for k, v in norm]}


# ---------------------------------------------------------------- rede
def obter(url, params=None, timeout=300, tentativas=3, codificacao="utf-8"):
    """GET com repetição (o INE é lento e falha de vez em quando)."""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    ultimo_erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vps-barometro/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(codificacao)
        except Exception as e:  # noqa: BLE001 - queremos repetir em qualquer falha de rede
            ultimo_erro = e
            if i < tentativas - 1:
                time.sleep(5 * (3 ** i))
    raise RuntimeError("falha a obter %s: %s" % (url, ultimo_erro))
