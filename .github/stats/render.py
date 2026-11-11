#!/usr/bin/env python3
"""THE NUMBERS — gera os painéis de estatísticas do perfil (assets/stats*.svg).

Somente dados reais, lidos da API GraphQL do GitHub:
  - calendário de contribuições dos últimos 12 meses (inclui contribuições
    privadas apenas como contagem, se o perfil tiver essa opção ativada);
  - linguagens dos repositórios públicos do usuário (bytes de código).
Nenhum nome de repositório privado é lido ou exibido.

Saídas (em --out):
  stats.svg / stats-mobile.svg  painéis desktop e celular
  stats.json                    "impressão digital" dos números; o workflow só
                                faz commit quando este arquivo muda

Uso:
  GITHUB_TOKEN=... python render.py --user Vinissaos --out assets
  python render.py --data dados.json --out assets      (prévia local)
"""
import argparse, datetime as dt, html, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
GLYPHS = json.loads((HERE / "glyphs.json").read_text(encoding="utf-8"))

BLACK, RED, GOLD, WHITE = "#080808", "#B31320", "#D4AF37", "#FFFFFF"
HEAT = ["#161616", "#4a0a0f", "#7a0f18", RED, GOLD]
LANG_COLORS = [GOLD, RED, "#E9E2CF", "#8A6A1F", "#5a5a5a", "#3a3a3a"]

QUERY = """query($login:String!,$privacy:RepositoryPrivacy){user(login:$login){
 contributionsCollection{contributionCalendar{totalContributions
  weeks{contributionDays{date contributionCount}}}}
 repositories(ownerAffiliations:OWNER,isFork:false,privacy:$privacy,first:100){
  nodes{languages(first:20){edges{size node{name}}}}}}}"""


# ----------------------------------------------------------------- dados
def fetch(user, token, include_private=False, attempts=3):
    body = json.dumps({"query": QUERY,
                       "variables": {"login": user, "privacy": None if include_private else "PUBLIC"}}).encode()
    for n in range(1, attempts + 1):
        req = urllib.request.Request(
            "https://api.github.com/graphql", data=body,
            headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                     "User-Agent": "profile-stats"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.load(r)
            break
        except (urllib.error.URLError, TimeoutError) as e:   # falha de rede/5xx: tenta de novo
            if n == attempts:
                sys.exit(f"Falha ao consultar a API do GitHub: {e}")
            time.sleep(5 * n)
    if res.get("errors") or not (res.get("data") or {}).get("user"):
        sys.exit(f"Resposta inválida da API: {res.get('errors') or 'usuário não encontrado'}")
    u = res["data"]["user"]
    days = [(d["date"], d["contributionCount"])
            for w in u["contributionsCollection"]["contributionCalendar"]["weeks"]
            for d in w["contributionDays"]]
    langs = {}
    for repo in u["repositories"]["nodes"]:
        for e in repo["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
    return {"days": days, "langs": langs}


def summarize(data, today=None):
    days = sorted(tuple(d) for d in data["days"])
    if not days:
        sys.exit("Calendário de contribuições vazio — nada foi gerado.")
    # referência = último dia do calendário retornado pela API (evita diferença de fuso do runner)
    today = today or days[-1][0]
    days = [d for d in days if d[0] <= today]
    counts = [c for _, c in days]
    # sequência atual: termina hoje; se hoje ainda não teve contribuição, conta a partir de ontem
    i = len(counts) - 1
    if counts and counts[i] == 0:
        i -= 1
    cur = 0
    while i >= 0 and counts[i] > 0:
        cur += 1; i -= 1
    best = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        best = max(best, run)
    total_b = sum(data["langs"].values()) or 1
    langs = sorted(data["langs"].items(), key=lambda kv: -kv[1])
    top = [(n, b / total_b * 100) for n, b in langs[:5]]
    rest = sum(b for _, b in langs[5:]) / total_b * 100
    if rest >= 0.05:
        top.append(("Outras", rest))
    return {
        "total": sum(counts), "current": cur, "longest": best,
        "active": sum(1 for c in counts if c > 0), "days": days, "langs": top,
        "updated": today, "private": data.get("private", False),
    }


# ----------------------------------------------------------------- texto em curvas
class Text:
    """Converte texto em <use> de glifos (fonte embutida como curvas)."""
    def __init__(self):
        self.used = {}

    def width(self, s, font, size, tr=0.0):
        f = GLYPHS[font]; k = size / f["upm"]
        w = sum((f["g"].get(ch, f["g"][" "])[0]) * k + tr * size for ch in s)
        return w - (tr * size if s else 0)

    def __call__(self, s, font, size, x, y, fill, tr=0.0, anchor="start", opacity=1):
        f = GLYPHS[font]; k = size / f["upm"]
        w = self.width(s, font, size, tr)
        x0 = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
        parts, cx = [], x0
        for ch in s:
            adv, d = f["g"].get(ch, f["g"][" "])
            if d:
                gid = f"{font}{ord(ch)}"
                self.used[gid] = d
                parts.append(f'<use href="#{gid}" transform="translate({cx:.1f} {y:.1f}) scale({k:.5f} {-k:.5f})"/>')
            cx += adv * k + tr * size
        op = f' fill-opacity="{opacity}"' if opacity != 1 else ""
        return f'<g fill="{fill}"{op}>{"".join(parts)}</g>'

    def defs(self):
        return "".join(f'<path id="{i}" d="{d}"/>' for i, d in self.used.items())


def fmt(n):
    return f"{n:,}".replace(",", ".")


MESES = ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"]


# ----------------------------------------------------------------- peças
def corners(x, y, w, h, c=12):
    return (f'<g fill="none" stroke="{GOLD}" stroke-width="1.1" opacity=".85">'
            f'<path d="M{x},{y+c}V{y}H{x+c}M{x+w-c},{y}H{x+w}V{y+c}M{x},{y+h-c}V{y+h}H{x+c}M{x+w-c},{y+h}H{x+w}V{y+h-c}"/></g>')


def tile(T, x, y, w, h, value, label, sub, accent=False, k=1.0):
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{BLACK}" stroke="{GOLD}" stroke-opacity=".35"/>',
           corners(x + 6, y + 6, w - 12, h - 12),
           f'<rect x="{x + w/2 - 18}" y="{y}" width="36" height="2" fill="{RED if accent else GOLD}"/>',
           T(value, "dun", 50, x + w / 2, y + h * 0.50, "url(#g)", tr=.04, anchor="middle"),
           T(label, "im", 11.5 * k, x + w / 2, y + h * 0.72, WHITE, tr=.22 if k == 1 else .14, anchor="middle", opacity=.9),
           T(sub, "il", 10 * k, x + w / 2, y + h * 0.86, "#8b8b8b", tr=.22 if k == 1 else .14, anchor="middle")]
    return "".join(out)


def heatmap(T, x, y, days, weeks, cell=11, gap=3, fs=9.5):
    # organiza por semana (domingo = linha 0), alinhado ao calendário do GitHub
    first = dt.date.fromisoformat(days[0][0])
    pad = (first.weekday() + 1) % 7
    grid = [None] * pad + days
    cols = [grid[i:i + 7] for i in range(0, len(grid), 7)][-weeks:]
    mx = max([c for _, c in days] + [1])
    out, last_m = [], None
    for ci, col in enumerate(cols):
        for ri, d in enumerate(col):
            if d is None:
                continue
            date, c = d
            lvl = 0 if c == 0 else min(4, 1 + int(3 * c / mx)) if mx > 1 else 4
            out.append(f'<rect x="{x + ci*(cell+gap)}" y="{y + ri*(cell+gap)}" width="{cell}" height="{cell}" rx="2" fill="{HEAT[lvl]}"/>')
        first_day = next((d for d in col if d), None)
        if first_day:
            m = int(first_day[0][5:7])
            if m != last_m and ci < len(cols) - 1:
                out.append(T(MESES[m - 1], "im", fs, x + ci*(cell+gap), y - 8, "#8b8b8b", tr=.15))
                last_m = m
    return "".join(out), len(cols) * (cell + gap) - gap


def legend(T, right, y):
    total = T.width("MENOS", "im", 9, .15) + 8 + 5 * 14 + 4 + T.width("MAIS", "im", 9, .15)
    x = right - total
    out = [T("MENOS", "im", 9, x, y + 9, "#8b8b8b", tr=.15)]
    lx = x + T.width("MENOS", "im", 9, .15) + 8
    for i, c in enumerate(HEAT):
        out.append(f'<rect x="{lx + i*14}" y="{y}" width="11" height="11" rx="2" fill="{c}"/>')
    out.append(T("MAIS", "im", 9, lx + 5*14 + 4, y + 9, "#8b8b8b", tr=.15))
    return "".join(out)


def lang_bar(T, x, y, w, langs, cols=3, row_h=24):
    out, cx = [], x
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="10" rx="5" fill="#161616"/>')
    out.append(f'<clipPath id="lb"><rect x="{x}" y="{y}" width="{w}" height="10" rx="5"/></clipPath><g clip-path="url(#lb)">')
    for i, (n, p) in enumerate(langs):
        seg = w * p / 100
        out.append(f'<rect x="{cx:.1f}" y="{y}" width="{max(seg, 0):.1f}" height="10" fill="{LANG_COLORS[i]}"/>')
        cx += seg
    out.append("</g>")
    colw = w / cols
    for i, (n, p) in enumerate(langs):
        r, c = divmod(i, cols)
        lx, ly = x + c * colw, y + 34 + r * row_h
        out.append(f'<path d="M{lx+5},{ly-9} l5,5 l-5,5 l-5,-5z" fill="{LANG_COLORS[i]}"/>')
        out.append(T(n, "im", 12.5, lx + 16, ly, "#e8e8e8", tr=.03))
        out.append(T(f"{p:.1f}%".replace(".", ","), "im", 12.5, lx + 16 + T.width(n, "im", 12.5, .03) + 8, ly, GOLD, tr=.03))
    return "".join(out)


def section_label(T, text, cx, y, w=None):
    tw = T.width(text, "im", 11, .3)
    return (T(text, "im", 11, cx, y, GOLD, tr=.3, anchor="middle")
            + f'<g stroke="{RED}" stroke-width="1"><line x1="{cx - tw/2 - 46}" y1="{y-4}" x2="{cx - tw/2 - 12}" y2="{y-4}"/>'
              f'<line x1="{cx + tw/2 + 12}" y1="{y-4}" x2="{cx + tw/2 + 46}" y2="{y-4}"/></g>')


def wrap(W, H, body, T, alt):
    defs = (f'<linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F6E3A1"/>'
            f'<stop offset=".5" stop-color="{GOLD}"/><stop offset="1" stop-color="#A8832A"/></linearGradient>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{alt}">'
            f'<defs>{defs}{T.defs()}</defs>'
            f'<style>.in{{animation:in 1.2s ease-out both}}@keyframes in{{from{{opacity:0}}to{{opacity:1}}}}'
            f'@media (prefers-reduced-motion:reduce){{.in{{animation:none}}}}</style>'
            f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="8" fill="{BLACK}" stroke="{GOLD}" stroke-opacity=".5" stroke-width="1.2"/>'
            f'{corners(10, 10, W-20, H-20, 16)}<line x1="{W*.2}" y1="1.5" x2="{W*.8}" y2="1.5" stroke="{GOLD}" stroke-width="2"/>'
            f'<g>{body}</g></svg>')


def tiles_data(s):
    return [(fmt(s["total"]), "CONTRIBUIÇÕES", "ÚLTIMOS 12 MESES", False),
            (str(s["current"]), "SEQUÊNCIA ATUAL", "DIAS SEGUIDOS", True),
            (str(s["longest"]), "MAIOR SEQUÊNCIA", "ÚLTIMOS 12 MESES", False),
            (str(s["active"]), "DIAS ATIVOS", "ÚLTIMOS 12 MESES", False)]


def alt_text(s):
    l = html.escape(", ".join(f"{n} {p:.1f}%" for n, p in s["langs"]))
    return (f"Estatísticas do GitHub: {s['total']} contribuições nos últimos 12 meses, sequência atual de {s['current']} dias, "
            f"maior sequência de {s['longest']} dias, {s['active']} dias ativos. Linguagens: {l}.")


def updated_label(s):
    d = dt.date.fromisoformat(s["updated"])
    return f"ATUALIZADO EM {d.day:02d}/{d.month:02d}/{d.year}"


def render_desktop(s):
    T = Text(); W = 820; b = []
    tw, gap, x0, y = 182, 14, 0, 40
    x0 = (W - (4 * tw + 3 * gap)) / 2
    for i, (v, l, sub, acc) in enumerate(tiles_data(s)):
        b.append(tile(T, x0 + i * (tw + gap), y, tw, 132, v, l, sub, acc))
    y = 214
    b.append(section_label(T, "ATIVIDADE · ÚLTIMOS 12 MESES", W / 2, y))
    hm, hw = heatmap(T, 0, 0, s["days"], 53)
    hx = (W - hw) / 2
    b.append(f'<g transform="translate({hx:.1f} {y + 34})">{hm}</g>')
    b.append(legend(T, hx + hw, y + 34 + 7 * 14 + 8))
    b.append(T(updated_label(s), "il", 9, hx, y + 34 + 7 * 14 + 17, "#6b6b6b", tr=.2))
    y = y + 34 + 7 * 14 + 66
    if s["langs"]:
        b.append(section_label(T, "LINGUAGENS · " + ("REPOSITÓRIOS" if s.get("private") else "REPOSITÓRIOS PÚBLICOS"), W / 2, y))
        b.append(lang_bar(T, 60, y + 24, W - 120, s["langs"], cols=3))
        rows = (len(s["langs"]) + 2) // 3
        y = y + 24 + 34 + rows * 24 + 8
    H = y + 18
    return wrap(W, H, "".join(b), T, alt_text(s))


def render_mobile(s):
    T = Text(); W = 420; b = []
    tw, th, gap = 182, 124, 12
    x0 = (W - (2 * tw + gap)) / 2; y = 36
    for i, (v, l, sub, acc) in enumerate(tiles_data(s)):
        r, c = divmod(i, 2)
        b.append(tile(T, x0 + c * (tw + gap), y + r * (th + gap), tw, th, v, l, sub, acc, k=1.12))
    y = y + 2 * th + gap + 46
    b.append(section_label(T, "ÚLTIMOS 6 MESES", W / 2, y))
    hm, hw = heatmap(T, 0, 0, s["days"], 26, cell=11, gap=3, fs=10.5)
    hx = (W - hw) / 2
    b.append(f'<g transform="translate({hx:.1f} {y + 34})">{hm}</g>')
    b.append(legend(T, hx + hw, y + 34 + 7 * 14 + 8))
    b.append(T(updated_label(s), "il", 9, hx, y + 34 + 7 * 14 + 17, "#6b6b6b", tr=.2))
    y = y + 34 + 7 * 14 + 66
    if s["langs"]:
        b.append(section_label(T, "LINGUAGENS", W / 2, y))
        b.append(lang_bar(T, 30, y + 24, W - 60, s["langs"], cols=2))
        rows = (len(s["langs"]) + 1) // 2
        y = y + 24 + 34 + rows * 24 + 8
    H = y + 18
    return wrap(W, H, "".join(b), T, alt_text(s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=os.environ.get("GITHUB_REPOSITORY_OWNER"))
    ap.add_argument("--data", help="JSON com {days:[[data,contagem]...], langs:{nome:bytes}}")
    ap.add_argument("--today", help="data de referência (AAAA-MM-DD)")
    ap.add_argument("--out", default="assets")
    a = ap.parse_args()
    if a.data:
        data = json.loads(Path(a.data).read_text(encoding="utf-8"))
    else:
        pat = (os.environ.get("STATS_TOKEN") or "").strip()
        data = fetch(a.user, pat or os.environ["GITHUB_TOKEN"], include_private=bool(pat))
        data["private"] = bool(pat)
    s = summarize(data, a.today)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    # impressão digital: números + semana do calendário (o mapa de atividade avança 1 coluna por semana)
    y, w, _ = dt.date.fromisoformat(s["updated"]).isocalendar()
    fp = {"total": s["total"], "current": s["current"], "longest": s["longest"], "active": s["active"],
          "langs": [[n, round(p, 1)] for n, p in s["langs"]], "week": f"{y}-W{w:02d}"}
    fp_path = out / "stats.json"
    if fp_path.exists() and json.loads(fp_path.read_text(encoding="utf-8")) == fp:
        print("Números inalterados — painéis mantidos.")
        return
    (out / "stats.svg").write_text(render_desktop(s), encoding="utf-8")
    (out / "stats-mobile.svg").write_text(render_mobile(s), encoding="utf-8")
    fp_path.write_text(json.dumps(fp, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(fp, ensure_ascii=False))


if __name__ == "__main__":
    main()
