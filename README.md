# Barómetro VPS

Página de indicadores oficiais (24 cartões: 10 de imobiliário e 14 de macroeconomia) em tema escuro VPS.
Os dados vêm do INE, do BPstat (Banco de Portugal) e do Eurostat e atualizam-se sozinhos.

## Como funciona
| Peça | Ficheiro | O que faz |
|---|---|---|
| Lista de indicadores | `config/series.json` | Código, nome, unidade e fonte de cada indicador |
| Robô | `scripts/update.py` + `scripts/barometro.py` | Vai às 3 fontes, calcula variações, escreve `site/data.json` |
| Página | `site/index.html` | Lê `data.json` e desenha os cartões |
| Agendamento | `.github/workflows/atualizar.yml` | Dias úteis de 2 em 2 horas; fins de semana 1 vez por dia |

## Acrescentar um indicador
Acrescentar uma linha em `config/series.json` (INE: `fonte":"INE"` e o código do indicador; BPstat: código da série) e fazer commit. O robô trata do resto.

## Atualizar à mão
GitHub → separador **Actions** → *Atualizar barómetro* → **Run workflow**.

## Ver localmente
```
python scripts/update.py          # opcional: vai às fontes
cd site && python -m http.server 8000   # abrir http://localhost:8000
```
Opções do URL: `?grupo=imobiliario` ou `?grupo=macro` (só um bloco), `?embed=1` (sem cabeçalho/rodapé), `?abrir=ID` (abre o gráfico ampliado).

## Dados iniciais
`scripts/seed_from_excel.py` gera um `data.json` inicial a partir do Excel (folhas JCOVAS_MENSAL e MACRO TRIMESTRAL). Só é preciso uma vez; a primeira execução do robô substitui tudo pelos dados diretos das fontes.

## Cores
Em `site/index.html`, bloco `:root`: `--accent: #ff6600` (VPS), fundo `#0b0b0c`, texto branco.
