"""Fundamental 'X-ray' for a stock — 6 layers, green/red flags, a weighted 0-10 health
score, and a plain-English bottom line. Uses only free yfinance data. Best-effort: any
metric we can't fetch is marked ❓ and left OUT of the score so it isn't unfairly punished.

Public API:
    xray(sym)            -> dict {ok, sym, score, verdict, items, opportunity, danger, sector}
    xray_text(sym)       -> full multi-layer English report (str) or None
    xray_short(sym)      -> one-block summary: score + opportunity + danger (str) or None
"""

import os

import yfinance as yf

# Each check: (layer, label, weight, plain-English note). Weight = how much it matters to the
# score — the strategy cares most about real growth, real cash, low debt and high returns.
W_REVENUE   = 3.0
W_NETPROFIT = 2.5
W_FCF       = 2.5
W_ROE       = 2.5
W_DEBT      = 2.5
W_QUALITY   = 2.0
W_GROSS     = 1.5
W_PE        = 1.5
W_PEG       = 1.5
W_FORWARD   = 1.5
W_MOAT      = 1.5
W_PS        = 1.5
W_ANALYST   = 1.0
W_SHORT     = 1.0
W_SURPRISE  = 1.0
W_INSIDER   = 1.0
W_RETURNS   = 1.0


def _pct(x):
    return f"{x * 100:.0f}%" if isinstance(x, (int, float)) else "no data"


def _num(x):
    return f"{x:.1f}" if isinstance(x, (int, float)) else "no data"


def _money(x):
    if not isinstance(x, (int, float)):
        return "no data"
    a = abs(x)
    if a >= 1e9:
        return f"${x / 1e9:.1f}B"
    if a >= 1e6:
        return f"${x / 1e6:.0f}M"
    return f"${x:,.0f}"


def _rev_growth_from_statements(t):
    """Statement-based YoY revenue growth — latest quarterly column vs the column DATED
    ~1 year earlier (blind index positions broke on mixed annual/TTM columns), with an
    annual-statement fallback for semi-annual reporters. Keeps the X-ray consistent with
    the daily scan's revenue check."""
    try:
        for attr in ("quarterly_income_stmt", "quarterly_financials"):
            df = getattr(t, attr, None)
            if df is None or df.empty or "Total Revenue" not in df.index:
                continue
            rev = df.loc["Total Revenue"].dropna().sort_index(ascending=False)
            if len(rev) < 2:
                continue
            latest_date, latest = rev.index[0], float(rev.iloc[0])
            best, best_gap = None, None
            for d, v in rev.iloc[1:].items():
                gap = abs((latest_date - d).days - 365)
                if gap <= 95 and (best_gap is None or gap < best_gap):
                    best, best_gap = float(v), gap
            if best and best != 0:
                g = (latest - best) / abs(best)
                if abs(g) <= 2:                     # sanity: >200% = mislabeled columns
                    return g
            break
    except Exception:
        pass
    try:                                            # annual fallback (e.g. ARGX reports semi-annually)
        df = getattr(t, "income_stmt", None)
        if df is not None and not df.empty and "Total Revenue" in df.index:
            rev = df.loc["Total Revenue"].dropna().sort_index(ascending=False)
            if len(rev) >= 2 and float(rev.iloc[1]) != 0:
                return (float(rev.iloc[0]) - float(rev.iloc[1])) / abs(float(rev.iloc[1]))
    except Exception:
        pass
    return None


def _latest(df, *names):
    """Most-recent value of any of the named rows in a yfinance statement DataFrame."""
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            s = df.loc[n].dropna()
            if len(s):
                return float(s.iloc[0])
    return None


def _fill_from_statements(t, info):
    """Fill in key metrics from the financial statements when Yahoo's quick `info` blob is
    sparse (it often is on the free endpoint). Keeps the score stable instead of swinging on
    missing data. All best-effort."""
    try:
        fin = t.income_stmt
    except Exception:
        fin = None
    try:
        bs = t.balance_sheet
    except Exception:
        bs = None
    try:
        cf = t.cashflow
    except Exception:
        cf = None
    rev = _latest(fin, "Total Revenue")
    ni = _latest(fin, "Net Income", "Net Income Common Stockholders")
    gp = _latest(fin, "Gross Profit")
    if info.get("netIncomeToCommon") is None and ni is not None:
        info["netIncomeToCommon"] = ni
    if info.get("profitMargins") is None and ni is not None and rev:
        info["profitMargins"] = ni / rev
    if info.get("grossMargins") is None and gp is not None and rev:
        info["grossMargins"] = gp / rev
    ocf = _latest(cf, "Operating Cash Flow", "Total Cash From Operating Activities")
    capex = _latest(cf, "Capital Expenditure", "Capital Expenditures")
    fcf = _latest(cf, "Free Cash Flow")
    if info.get("operatingCashflow") is None and ocf is not None:
        info["operatingCashflow"] = ocf
    if info.get("freeCashflow") is None:
        if fcf is not None:
            info["freeCashflow"] = fcf
        elif ocf is not None and capex is not None:
            info["freeCashflow"] = ocf + capex      # capex is negative in the statement
    cash = _latest(bs, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
    debt = _latest(bs, "Total Debt")
    if info.get("totalCash") is None and cash is not None:
        info["totalCash"] = cash
    if info.get("totalDebt") is None and debt is not None:
        info["totalDebt"] = debt


def _fetch(sym):
    t = yf.Ticker(sym)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    if info.get("revenueGrowth") is None:           # keep revenue consistent with the daily scan
        rg = _rev_growth_from_statements(t)          # (don't discard a legit flat 0% reading)
        if rg is not None:
            info["revenueGrowth"] = rg
    if info.get("currentPrice") is None:            # some tickers only expose regularMarketPrice
        info["currentPrice"] = info.get("regularMarketPrice")
    try:
        _fill_from_statements(t, info)              # backfill sparse `info` from the statements
    except Exception:
        pass
    out = {"info": info, "buyback": None, "insider_net": None}
    try:                                            # buybacks: cash spent repurchasing stock
        cf = t.cashflow
        for row in ("Repurchase Of Capital Stock", "Repurchase Of Stock", "Common Stock Payments"):
            if cf is not None and not cf.empty and row in cf.index:
                v = cf.loc[row].dropna()
                if len(v):
                    out["buyback"] = float(v.iloc[0]) < 0
                    break
    except Exception:
        pass
    try:                                            # net insider buying (very best-effort)
        ip = t.insider_purchases
        if ip is not None and not ip.empty:
            col = ip.columns[0]
            mask = ip.index.astype(str).str.contains("Net Shares Purchased", case=False)
            if mask.any():
                out["insider_net"] = float(ip.loc[mask, col].iloc[0])
    except Exception:
        pass
    out["earn_beats"] = None                         # recent earnings beats vs estimates
    try:
        import pandas as pd
        ed = t.get_earnings_dates(limit=10)
        if ed is not None and not ed.empty:
            scol = next((c for c in ed.columns if "Surprise" in str(c)), None)
            if scol:
                past = pd.to_numeric(ed[scol], errors="coerce").dropna().head(4)  # robust to strings/NaN
                if len(past):
                    out["earn_beats"] = (int((past > 0).sum()), int(len(past)))
    except Exception:
        pass
    return out


def _normalize_units(info):
    """Defend the score against yfinance scale glitches across versions: ratios are expected as
    fractions (0.46 = 46%), but some versions return percentages (46). Detect the percentage
    form by magnitude and convert. Applied exactly once, at the start of evaluate()."""
    # margins: a POSITIVE value > 1.5 can't be a fraction (>150% margin) -> it's a percentage.
    # (negative margins can legitimately be large fractions for cash-burners, so leave those.)
    for k in ("grossMargins", "profitMargins", "operatingMargins"):
        v = info.get(k)
        if isinstance(v, (int, float)) and v > 1.5:
            info[k] = v / 100.0
    # ROE/ROA can legitimately exceed 100% (e.g. AAPL ~1.5), so only treat very large as percent
    for k in ("returnOnEquity", "returnOnAssets"):
        v = info.get(k)
        if isinstance(v, (int, float)) and abs(v) > 5:
            info[k] = v / 100.0
    # growth: a fraction can be >1 (161% = 1.61); only >5 (>500%) signals a percentage form
    for k in ("revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth"):
        v = info.get(k)
        if isinstance(v, (int, float)) and abs(v) > 5:
            info[k] = v / 100.0
    # short % of float and dividend yield are fractions; >1.x means a percentage slipped through
    for k, cut in (("shortPercentOfFloat", 1.5), ("dividendYield", 1.0)):
        v = info.get(k)
        if isinstance(v, (int, float)) and v > cut:
            info[k] = v / 100.0
    return info


def evaluate(data):
    """Turn raw fundamentals into scored, flagged, explained items + a bottom line."""
    info = _normalize_units(data.get("info") or {})
    g = info.get
    items = []

    def add(layer, label, value, flag, weight, note):
        items.append({"layer": layer, "label": label, "value": value,
                      "flag": flag, "weight": weight, "note": note})

    def f3(ok, known):                              # green / red / na(unknown)
        return ("green" if ok else "red") if known else "na"

    # ---- Layer 1: Profitability ----
    rg = g("revenueGrowth")
    add("Profitability", "Revenue growth", _pct(rg), f3((rg or 0) > 0.05, rg is not None), W_REVENUE,
        "Bringing in more money than last year" if (rg or 0) > 0.05 else "Revenue is barely growing / shrinking")
    gm = g("grossMargins")
    add("Profitability", "Gross margin", _pct(gm), f3((gm or 0) >= 0.35, gm is not None), W_GROSS,
        "Makes cheap, sells dear" if (gm or 0) >= 0.35 else "Thin margins — hard to profit on each sale")
    pm = g("profitMargins")
    add("Profitability", "Net profit (bottom line)", _pct(pm), f3((pm or 0) > 0, pm is not None), W_NETPROFIT,
        "Actually keeps money after all costs" if (pm or 0) > 0 else "Losing money on the bottom line")

    # ---- Layer 2: Valuation ---- (only penalize EXTREME valuation; "fully valued" stays neutral)
    pe = g("trailingPE") or g("forwardPE")
    if pe is None:
        pe_flag = "na"
    elif pe <= 0:
        pe_flag = "red"
    elif pe < 30:
        pe_flag = "green"
    elif pe > 50:
        pe_flag = "red"
    else:
        pe_flag = "na"
    add("Valuation", "P/E ratio", _num(pe), pe_flag, W_PE,
        "Reasonable price vs earnings" if pe_flag == "green" else
        ("Very expensive — unusually high multiple" if pe_flag == "red" else "Fully priced but not extreme"))
    peg = g("trailingPegRatio") or g("pegRatio")
    if peg is None:
        peg_flag = "na"
    elif 0 < peg <= 2:
        peg_flag = "green"
    elif peg > 3.5:
        peg_flag = "red"
    else:
        peg_flag = "na"
    add("Valuation", "PEG (price vs growth)", _num(peg), peg_flag, W_PEG,
        "Price justified by its growth rate" if peg_flag == "green" else
        ("Very expensive relative to growth" if peg_flag == "red" else "Fair-to-full price vs growth"))
    ps = g("priceToSalesTrailing12Months")
    if ps is None:
        ps_flag = "na"
    elif ps < 10:
        ps_flag = "green"
    elif ps > 20:
        ps_flag = "red"                              # >20x sales = speculative (catches pre-revenue hype)
    else:
        ps_flag = "na"
    add("Valuation", "Price/Sales (P/S)", _num(ps), ps_flag, W_PS,
        "Reasonable price vs sales" if ps_flag == "green" else
        ("Highly speculative — valued at dozens of times actual sales" if ps_flag == "red"
         else "Elevated price vs sales"))

    # ---- Layer 3: Cash flow ----
    ocf = g("operatingCashflow")
    ni = g("netIncomeToCommon")
    quality_known = ocf is not None and ni is not None
    quality_ok = quality_known and ni > 0 and ocf >= ni
    add("Cash flow", "Earnings quality (cash vs 'paper' profit)",
        f"cash {_money(ocf)} vs profit {_money(ni)}", f3(quality_ok, quality_known), W_QUALITY,
        "The profit actually hits the bank" if quality_ok else "Profit is more on paper than in real cash")
    fcf = g("freeCashflow")
    add("Cash flow", "Free cash flow (FCF)", _money(fcf), f3((fcf or 0) > 0, fcf is not None), W_FCF,
        "Real cash left over after everything" if (fcf or 0) > 0 else "Burning cash — depends on raising money")

    # ---- Layer 4: Balance-sheet strength ---- (cash-flow-aware: strong FCF can cover debt comfortably)
    cash, debt, de, cr = g("totalCash"), g("totalDebt"), g("debtToEquity"), g("currentRatio")
    debt_known = any(v is not None for v in (cash, debt, de, cr))
    # FCF offsets debt only when ~3 years of free cash flow would clear it. AAPL-style names
    # (huge debt, but FCF clears it in ~1y) stay green; names that need 4+ years (e.g. MRSH) flag red.
    fcf_covers = (fcf is not None and fcf > 0 and debt is not None and debt <= 3 * fcf)
    debt_ok = (
        (cash is not None and debt is not None and cash >= debt) or   # net cash position
        fcf_covers or                                                  # a few years of FCF clears it
        (de is not None and de < 100) or                              # modest leverage
        (cr is not None and cr >= 1.5 and (de is None or de < 200))  # liquid, not extreme
    )
    add("Balance-sheet strength", "Debt vs cash/cash-flow", f"cash {_money(cash)} vs debt {_money(debt)}",
        f3(debt_ok, debt_known), W_DEBT,
        "Enough cash/cash-flow to cover the debt comfortably" if debt_ok else "Debt is heavy vs cash and cash-flow")
    roe = g("returnOnEquity")
    add("Balance-sheet strength", "Management efficiency (ROE)", _pct(roe), f3((roe or 0) >= 0.15, roe is not None), W_ROE,
        "Management earns a high return on the money" if (roe or 0) >= 0.15 else "Low return on invested equity")

    # ---- Layer 5: Forward signals ----
    eg = g("earningsGrowth") or g("earningsQuarterlyGrowth")
    tgt, price = g("targetMeanPrice"), g("currentPrice")
    fwd_known = eg is not None or (tgt is not None and price is not None)
    fwd_ok = ((eg or 0) > 0) or (tgt is not None and price is not None and tgt > price * 1.05)
    fwd_val = "improving" if fwd_ok else ("slowing" if fwd_known else "no data")
    add("Forward signals", "Forward outlook (earnings growth/target)", fwd_val, f3(fwd_ok, fwd_known), W_FORWARD,
        "The road ahead looks better" if fwd_ok else "Forecasts are uninspiring")
    ins = data.get("insider_net")
    ins_known = ins is not None
    add("Forward signals", "Insider buying",
        ("buying" if (ins or 0) > 0 else "selling") if ins_known else "no data",
        f3((ins or 0) > 0, ins_known), W_INSIDER,
        "Insiders buying with their own money — real confidence" if (ins or 0) > 0 else "No notable insider buying")
    # analyst consensus + price-target upside
    rec = g("recommendationKey")
    nop = g("numberOfAnalystOpinions")
    upside = (tgt / price - 1) if (tgt and price) else None
    analyst_known = (rec not in (None, "none")) or upside is not None
    analyst_ok = (rec in ("buy", "strong_buy")) or (upside is not None and upside > 0.10)
    analyst_bad = (rec in ("sell", "strong_sell")) or (upside is not None and upside < -0.05)
    a_flag = "green" if analyst_ok else ("red" if analyst_bad else "na")
    a_val = f"{rec or '?'}" + (f", target {upside:+.0%}" if upside is not None else "") + (f" ({nop} analysts)" if nop else "")
    add("Forward signals", "Analyst consensus + price target", a_val, a_flag, W_ANALYST,
        "Analysts are positive and the target is above the price" if analyst_ok else
        ("Analysts are negative / target below price" if analyst_bad else "Analyst view is neutral"))
    # short interest (bearish positioning / squeeze risk)
    sf = g("shortPercentOfFloat")
    if sf is None:
        sf_flag = "na"
    elif sf < 0.05:
        sf_flag = "green"
    elif sf > 0.15:
        sf_flag = "red"
    else:
        sf_flag = "na"
    add("Forward signals", "Short interest", _pct(sf) if sf is not None else "no data", sf_flag, W_SHORT,
        "Almost nobody is betting against it" if sf_flag == "green" else
        ("High short interest — the market is betting against it (squeeze potential too)" if sf_flag == "red"
         else "Moderate short interest"))
    # earnings track record: did it beat estimates recently?
    eb = data.get("earn_beats")
    if eb:
        beats, tot = eb
        es_ok = beats >= max(1, round(tot * 0.75))
        add("Forward signals", "Earnings beats vs estimates", f"{beats}/{tot} quarters beat",
            "green" if es_ok else "red", W_SURPRISE,
            "Consistently beats analyst estimates" if es_ok else "Misses estimates fairly often")

    # ---- Layer 6: Moat & shareholder returns ----
    dy, bb = g("dividendYield"), data.get("buyback")
    ret_known = dy is not None or bb is not None
    ret_ok = (dy is not None and dy > 0) or bb is True
    ret_val = []
    if dy:
        ret_val.append(f"dividend {_pct(dy if dy < 1 else dy / 100)}")
    if bb:
        ret_val.append("buybacks")
    add("Moat & shareholder returns", "Shareholder returns (dividend/buyback)",
        ", ".join(ret_val) or ("none" if ret_known else "no data"),
        f3(ret_ok, ret_known), W_RETURNS,
        "Returns cash to shareholders" if ret_ok else "No direct cash returned to shareholders")
    moat_known = gm is not None and roe is not None
    moat_ok = (gm or 0) >= 0.4 and (roe or 0) >= 0.15      # pricing power + high returns = likely moat
    add("Moat & shareholder returns", "Economic moat",
        "signs of a moat" if moat_ok else ("weak" if moat_known else "no data"),
        "green" if moat_ok else "na", W_MOAT,
        "High margins + high returns = a hard-to-copy edge" if moat_ok else "No clear competitive edge in the data")

    # ---- score: weighted, over the flags we actually know ----
    total = sum(it["weight"] for it in items)
    earned = sum(it["weight"] for it in items if it["flag"] == "green")
    possible = sum(it["weight"] for it in items if it["flag"] in ("green", "red"))
    score = round(10 * earned / possible) if possible else 0
    coverage = possible / total if total else 0.0

    flagof = lambda part: next((it["flag"] for it in items if part in it["label"]), "na")
    net_red = flagof("Net profit") == "red"
    fcf_red = flagof("FCF") == "red"
    ps_red = flagof("P/S") == "red"
    # "richly valued" = good business but not cheap; a mild caveat, not a health problem
    rich = (pe is not None and pe > 30) or (peg is not None and peg > 2.5) or ps_red

    # Hard caps so an obviously risky stock can never read as "excellent":
    caps = []
    # A perfect 10 is reserved for a clean sheet — a SINGLE red flag caps the score at 9.
    # (Heavier or multiple red flags pull the weighted score lower than 9 on their own.)
    if any(it["flag"] == "red" for it in items):
        score = min(score, 9)
    if net_red and fcf_red:                 # losing money AND burning cash = speculative
        score = min(score, 4); caps.append("Losing money and burning cash")
    if ps_red:                              # priced at a huge multiple of actual sales
        score = min(score, 6); caps.append("Speculative valuation (huge sales multiple)")
    elif rich:                              # great company but fully priced -> can't be a perfect 10
        score = min(score, 9)
    # Sparse data must not inflate the score — a 10/10 off 1-2 known flags is meaningless.
    if coverage < 0.30:
        score = min(score, 4); confidence = "very_low"
    elif coverage < 0.50:
        score = min(score, 6); confidence = "low"
    else:
        confidence = "ok"

    verdict = ("Excellent" if score >= 8 else "Good" if score >= 6 else "Fair" if score >= 4 else "Weak")
    opportunity, danger = _bottom_line(items, rich)
    return {"items": items, "score": score, "verdict": verdict,
            "opportunity": opportunity, "danger": danger, "caps": caps,
            "confidence": confidence, "coverage": round(coverage, 2),
            "sector": info.get("sector"), "known": possible > 0}


def _find(items, label_part):
    for it in items:
        if label_part in it["label"]:
            return it
    return None


def _bottom_line(items, rich=False):
    by = {it["label"]: it["flag"] for it in items}
    green = lambda part: any(part in lbl and fl == "green" for lbl, fl in by.items())
    red = lambda part: any(part in lbl and fl == "red" for lbl, fl in by.items())
    rev = _find(items, "Revenue growth")
    roe = _find(items, "ROE")

    if green("Revenue growth") and green("PEG"):
        opp = f"Growing fast ({rev['value']}) and still not expensive vs growth — if the pace holds, the market hasn't priced it in yet."
    elif green("FCF") and green("Shareholder returns"):
        opp = "A cash machine that returns money to shareholders — a stable base that draws buyers."
    elif green("ROE"):
        opp = f"Management earns a high return on capital ({roe['value']}) — a quality compounding engine."
    elif green("Revenue growth"):
        opp = f"Revenue is growing nicely ({rev['value']}) — a real business tailwind."
    else:
        opp = "No standout growth catalyst in the data right now — the opportunity rests mainly on the chart."

    if red("Net profit") and red("FCF"):
        dgr = "Losing money and burning cash — to survive it raises capital and quietly dilutes you."
    elif red("Debt"):
        dgr = "Debt is larger than cash — a weak quarter or higher rates could quietly squeeze them."
    elif red("P/S"):
        dgr = "Speculative valuation — priced at dozens of times sales; any disappointment hits hard."
    elif red("Earnings quality"):
        dgr = "Profit exists on paper but less of it shows up as cash — a warning sign many miss."
    elif red("Net profit"):
        dgr = "Not yet profitable on the bottom line — burning money until it turns."
    elif red("FCF"):
        dgr = "Burning free cash — dependent on its ability to raise more."
    elif red("P/E") or red("PEG"):
        dgr = "High valuation — expectations are baked in that it must meet, or it falls."
    elif rich:
        dgr = "Quality company but richly valued — expectations are already priced in, little room for error if a quarter disappoints."
    else:
        dgr = "No glaring hidden danger in the numbers — the main risk is market volatility."
    return opp, dgr


FLAG_EMOJI = {"green": "🟢", "red": "🔴", "na": "❓"}
_LAYERS = ["Profitability", "Valuation", "Cash flow", "Balance-sheet strength",
           "Forward signals", "Moat & shareholder returns"]
_LAYER_TITLE = {
    "Profitability": "Layer 1 — Profitability (is the engine working?)",
    "Valuation": "Layer 2 — Valuation (am I overpaying?)",
    "Cash flow": "Layer 3 — Cash flow (reality vs paper)",
    "Balance-sheet strength": "Layer 4 — Strength (will it survive a crisis?)",
    "Forward signals": "Layer 5 — Forward signals",
    "Moat & shareholder returns": "Layer 6 — Moat & shareholder returns",
}


def _ai_layer(sym, res, web=False):
    """If an ANTHROPIC_API_KEY is set, let Sonnet read the real rule-based metrics and write a
    sharper opportunity / danger / bottom-line in English — catching nuance the rules can't.
    With web=True it may search the web for current context (news, dilution, short squeeze,
    analyst views). It only rewrites the narrative; the numeric score stays anchored to data."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return
    try:
        import anthropic
    except ImportError:
        return
    facts = "; ".join(f"{it['label']}={it['value']} [{it['flag']}]" for it in res["items"])
    sector = res.get("sector") or "unknown"
    web_line = ("You have web search — look up current info (latest news, capital raises/dilution, "
                "short interest, analyst views) to sharpen the answer.\n" if web else "")
    user = (f"Stock: {sym} | Sector: {sector} | Rule-based fundamental score: {res['score']}/10.\n"
            f"Raw data from filings: {facts}\n\n"
            f"{web_line}"
            "You are a senior financial analyst. Do not invent numbers not supported by the data/search. "
            "Answer in plain English in EXACTLY this format, with nothing extra:\n"
            "Opportunity: <one sentence — the thing that could push the stock up>\n"
            "Danger: <one sentence — the quiet hidden risk most people miss>\n"
            "Bottom line: <2-3 sentences of sharp, honest judgment, including nuance the dry numbers miss>")
    kwargs = dict(
        model=os.environ.get("CHAT_MODEL", "claude-sonnet-4-6"),
        max_tokens=900,
        system="You are a senior financial analyst who explains complex things simply. Honest, concrete, no promises. Not financial advice.",
        messages=[{"role": "user", "content": user}],
    )
    if web:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}]
    try:
        client = anthropic.Anthropic(api_key=key)
        try:
            resp = client.messages.create(**kwargs)
        except Exception as e:
            if "tools" in kwargs:          # web search unsupported on this account -> retry plain
                print(f"xray web search unavailable ({e}); retrying without it.")
                kwargs.pop("tools", None)
                resp = client.messages.create(**kwargs)
            else:
                raise
        txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    except Exception as e:
        print(f"xray AI failed: {e}")
        return
    verdict, in_verdict = [], False
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith("Opportunity:"):
            res["opportunity"] = s.split(":", 1)[1].strip(); in_verdict = False
        elif s.startswith("Danger:"):
            res["danger"] = s.split(":", 1)[1].strip(); in_verdict = False
        elif s.startswith("Bottom line:"):
            verdict = [s.split(":", 1)[1].strip()]; in_verdict = True
        elif in_verdict:
            if not s:                       # stop at the first blank line after the bottom line
                break
            verdict.append(s)
    vt = " ".join(v for v in verdict if v).strip()
    if vt:
        res["ai_verdict"] = vt
    res["ai"] = True


def xray(sym, ai=False, web=False):
    try:
        res = evaluate(_fetch(sym))
        res.update({"ok": res.get("known", False), "sym": sym})
        if ai and res["ok"]:
            try:
                _ai_layer(sym, res, web=web)
            except Exception as e:
                print(f"xray AI layer error: {e}")
        return res
    except Exception:
        return {"ok": False, "sym": sym}


def _confidence_note(res):
    c = res.get("confidence")
    if c == "very_low":
        return "⚠️ Very limited fundamental data — the score is capped and unreliable; treat with caution."
    if c == "low":
        return "⚠️ Partial fundamental data — the score is capped and less reliable."
    return ""


def xray_text(sym, res=None):
    res = res or xray(sym, ai=True, web=True)   # on-demand deep dive -> AI brain + live web search
    if not res.get("ok"):
        return None
    sector = f"  ({res['sector']})" if res.get("sector") else ""
    known = sum(1 for it in res["items"] if it["flag"] in ("green", "red"))
    lines = [f"🩻 Fundamental X-ray — {sym}{sector}",
             f"Health score: {res['score']}/10 — {res['verdict']}",
             f"📊 Data coverage: {known}/{len(res['items'])} checks ({int(res.get('coverage', 0) * 100)}%)"]
    note = _confidence_note(res)
    if note:
        lines.append(note)
    for layer in _LAYERS:
        lines.append("")
        lines.append("🔬 " + _LAYER_TITLE[layer])
        for it in [i for i in res["items"] if i["layer"] == layer]:
            lines.append(f"{FLAG_EMOJI[it['flag']]} {it['label']}: {it['value']} — {it['note']}")
    lines += ["", f"💡 Opportunity: {res['opportunity']}", f"⚠️ Danger: {res['danger']}"]
    if res.get("ai_verdict"):
        lines += ["", f"🤖 Bottom line (Sonnet): {res['ai_verdict']}"]
    return "\n".join(lines)


def xray_short(sym, res=None):
    res = res or xray(sym)                 # inline in /analyze -> rules only (ai_opinion adds the AI take)
    if not res.get("ok"):
        return None
    note = _confidence_note(res)
    head = f"🩻 Fundamental health: {res['score']}/10 ({res['verdict']})"
    if note:
        head += "\n" + note
    out = (f"{head}\n"
           f"💡 Opportunity: {res['opportunity']}\n"
           f"⚠️ Danger: {res['danger']}")
    if res.get("ai_verdict"):
        out += f"\n🤖 Bottom line (Sonnet): {res['ai_verdict']}"
    return out
