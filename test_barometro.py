import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import barometro as b  # noqa: E402

D = dt.date

# Amostras reais (27/11/2026) das respostas das APIs, encurtadas
BPSTAT = """# Series;Series description (EN);Metric;Unit of Measure;Reference date;Value;State
5739222;HICP - All-items - YoY - Monthly (YoY inflation rate);Year-on-year rate of change;Percentage;1997-02-28;2.4;
5739222;HICP - All-items - YoY - Monthly (YoY inflation rate);Year-on-year rate of change;Percentage;1997-01-31;2.8;
12748362;Interest Rate-Loans-Individuals MU-House purchase (Pure New Loans);Annualized agreed rate;Percentage;2026-09-30;3.07;
"""
EUROSTAT = """DATAFLOW,LAST UPDATE,freq,purchase,unit,geo,TIME_PERIOD,OBS_VALUE,OBS_FLAG,CONF_STATUS
ESTAT:PRC_HPI_Q(1.0),01/10/26 11:00:00,Q,TOTAL,RCH_A,EU27_2020,2025-Q3,5.5,,
ESTAT:PRC_HPI_Q(1.0),01/10/26 11:00:00,Q,TOTAL,RCH_A,PT,2026-Q2,16.5,,
"""
INE = [{"IndicadorCod": "0012248", "Dados": {
    "Outubro de 2026": [
        {"dim_3": "2", "dim_3_t": "Moradias", "geocod": "PT", "valor": "1640"},
        {"dim_3": "T", "dim_3_t": "Total", "geocod": "PT", "valor": "2282"},
        {"dim_3": "T", "dim_3_t": "Total", "geocod": "11", "valor": "9999"}],
    "2.º Trimestre de 2026": [{"dim_3_t": "Total", "geocod": "PT", "valor": "10,5"}]}}]


class Leitura(unittest.TestCase):
    def test_bpstat_ordem_e_valores(self):
        r = b.parse_bpstat(BPSTAT)
        self.assertEqual(set(r), {"5739222", "12748362"})
        self.assertEqual(b.normalizar(r["5739222"], "M"), [("1997-01", 2.8), ("1997-02", 2.4)])

    def test_eurostat(self):
        r = b.parse_eurostat(EUROSTAT)
        self.assertEqual(r["PT"], [(D(2026, 4, 1), 16.5)])
        self.assertEqual(r["EU27_2020"], [(D(2025, 7, 1), 5.5)])

    def test_ine_escolhe_linha_total_e_portugal(self):
        r = dict(b.parse_ine(INE, ["total"]))
        self.assertEqual(r[D(2026, 10, 1)], 2282.0)
        self.assertEqual(r[D(2026, 4, 1)], 10.5)

    def test_ine_sem_dados_falha(self):
        with self.assertRaises(ValueError):
            b.parse_ine([{"Sucesso": {"Falso": "erro"}}], ["total"])

    def test_datas_ine(self):
        self.assertEqual(b.data_ine("Março de 2020"), D(2020, 3, 1))
        self.assertEqual(b.data_ine("4.º Trimestre de 2019"), D(2019, 10, 1))
        self.assertEqual(b.data_ine("2018"), D(2018, 1, 1))


class Calculo(unittest.TestCase):
    def test_deslocar(self):
        self.assertEqual(b.deslocar("2026-01", "M", 1), "2025-12")
        self.assertEqual(b.deslocar("2026-10", "M", 12), "2025-10")
        self.assertEqual(b.deslocar("2026-Q1", "T", 1), "2025-Q4")
        self.assertEqual(b.deslocar("2026-Q2", "T", 4), "2025-Q2")

    def test_variacao_pct_e_pp(self):
        cfg = {"id": "x", "titulo": "x", "unidade": "", "casas": 0, "fonte": "INE", "codigo": "1", "freq": "M", "var": "pct"}
        pts = [(D(2025, 10, 31), 100.0), (D(2026, 9, 30), 110.0), (D(2026, 10, 31), 112.0)]
        s = b.construir_serie(cfg, pts)
        self.assertAlmostEqual(s["vs_ant"]["d"], 1.818182, 5)
        self.assertAlmostEqual(s["vs_ano"]["d"], 12.0, 5)
        s = b.construir_serie(dict(cfg, var="pp"), pts)
        self.assertAlmostEqual(s["vs_ant"]["d"], 2.0, 5)

    def test_periodo_em_falta_da_null(self):
        cfg = {"id": "x", "titulo": "x", "unidade": "", "casas": 0, "fonte": "INE", "codigo": "1", "freq": "T", "var": "pct"}
        s = b.construir_serie(cfg, [(D(2026, 6, 30), 5.0)])
        self.assertIsNone(s["vs_ant"])
        self.assertIsNone(s["vs_ano"])

    def test_trimestral_bpstat_fim_de_trimestre(self):
        cfg = {"id": "x", "titulo": "x", "unidade": "", "casas": 0, "fonte": "BPstat", "codigo": "1", "freq": "T", "var": "pp"}
        s = b.construir_serie(cfg, [(D(2026, 3, 31), 1.0), (D(2026, 6, 30), 2.5)])
        self.assertEqual(s["ultimo"]["p"], "2026-Q2")
        self.assertEqual(s["vs_ant"]["d"], 1.5)

    def test_taxa_bce_diaria_reduz_a_alteracoes(self):
        cfg = {"id": "bce", "titulo": "x", "unidade": "%", "casas": 2, "fonte": "BPstat", "codigo": "1", "freq": "E", "var": "pp"}
        pts = []
        d = D(2025, 11, 1)
        while d <= D(2026, 11, 25):
            v = 2.0 if d < D(2026, 6, 17) else (2.25 if d < D(2026, 9, 16) else 2.5)
            pts.append((d, v))
            d += dt.timedelta(days=1)
        s = b.construir_serie(cfg, pts)
        self.assertEqual(s["ultimo"], {"p": "2026-11-25", "v": 2.5})
        self.assertEqual(s["vs_ant"], {"p": "2026-09-16", "d": 0.25})
        self.assertEqual(s["vs_ano"]["d"], 0.5)
        self.assertEqual(len(s["hist"]), 4)  # 3 níveis + último dia


class DadosPublicados(unittest.TestCase):
    """Valida o site/data.json que está no repositório."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(os.path.dirname(__file__), "..", "site", "data.json"), encoding="utf-8") as f:
            cls.doc = json.load(f)
        with open(os.path.join(os.path.dirname(__file__), "..", "config", "series.json"), encoding="utf-8") as f:
            cls.cfg = json.load(f)

    def test_todas_as_series_presentes(self):
        self.assertEqual([s["id"] for s in self.doc["series"]], [s["id"] for s in self.cfg["series"]])

    def test_historicos_ordenados_e_sem_nulos(self):
        for s in self.doc["series"]:
            ks = [k for k, _ in s["hist"]]
            self.assertEqual(ks, sorted(ks), s["id"])
            self.assertTrue(all(isinstance(v, (int, float)) for _, v in s["hist"]), s["id"])
            self.assertEqual(s["hist"][-1][0], s["ultimo"]["p"], s["id"])


if __name__ == "__main__":
    unittest.main()
