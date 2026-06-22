"""Fundamental 'X-ray' for a stock — 6 layers, green/red flags, a weighted 0-10 health
score, and a plain-Hebrew bottom line. Uses only free yfinance data. Best-effort: any
metric we can't fetch is marked ❓ and left OUT of the score so it isn't unfairly punished.

Public API:
    xray(sym)            -> dict {ok, sym, score, verdict, items, opportunity, danger, sector}
    xray_text(sym)       -> full multi-layer Hebrew report (str) or None
    xray_short(sym)      -> one-block summary: score + opportunity + danger (str) or None
"""

import os

import yfinance as yf

# Each check: (layer, label, weight, plain-Hebrew note). Weight = how much it matters to the
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
    return f"{x * 100:.0f}%" if isinstance(x, (int, float)) else "אין נתון"


def _num(x):
    return f"{x:.1f}" if isinstance(x, (int, float)) else "אין נתון"


def _money(x):
    if not isinstance(x, (int, float)):
        return "אין נתון"
    a = abs(x)
    if a >= 1e9:
        return f"${x / 1e9:.1f}B"
    if a >= 1e6:
        return f"${x / 1e6:.0f}M"
    return f"${x:,.0f}"


def _rev_growth_from_statements(t):
    """Statement-based YoY revenue growth (latest quarter vs same quarter a year ago) —
    the same method the daily scan shows, so the X-ray stays consistent with it."""
    try:
        for attr in ("quarterly_income_stmt", "quarterly_financials"):
            df = getattr(t, attr, None)
            if df is not None and not df.empty and "Total Revenue" in df.index:
                rev = df.loc["Total Revenue"].dropna().sort_index(ascending=False)
                if len(rev) >= 5 and float(rev.iloc[4]) != 0:
                    return (float(rev.iloc[0]) - float(rev.iloc[4])) / abs(float(rev.iloc[4]))
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

    # ---- Layer 1: רווחיות ----
    rg = g("revenueGrowth")
    add("רווחיות", "צמיחת הכנסות", _pct(rg), f3((rg or 0) > 0.05, rg is not None), W_REVENUE,
        "מכניסה יותר כסף משנה שעברה" if (rg or 0) > 0.05 else "ההכנסות בקושי צומחות / מתכווצות")
    gm = g("grossMargins")
    add("רווחיות", "שולי רווח גולמי", _pct(gm), f3((gm or 0) >= 0.35, gm is not None), W_GROSS,
        "מייצרת בזול ומוכרת ביוקר" if (gm or 0) >= 0.35 else "שוליים דקים — קשה להרוויח על כל מכירה")
    pm = g("profitMargins")
    add("רווחיות", "רווח נקי (שורה תחתונה)", _pct(pm), f3((pm or 0) > 0, pm is not None), W_NETPROFIT,
        "באמת נשאר כסף בכיס אחרי כל ההוצאות" if (pm or 0) > 0 else "מפסידה כסף בשורה התחתונה")

    # ---- Layer 2: תמחור ---- (only penalize EXTREME valuation; "fully valued" stays neutral)
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
    add("תמחור", "מכפיל רווח (P/E)", _num(pe), pe_flag, W_PE,
        "מחיר סביר ביחס לרווחים" if pe_flag == "green" else
        ("יקר מאוד — מכפיל גבוה במיוחד" if pe_flag == "red" else "מתומחר במלואו אך לא קיצוני"))
    peg = g("trailingPegRatio") or g("pegRatio")
    if peg is None:
        peg_flag = "na"
    elif 0 < peg <= 2:
        peg_flag = "green"
    elif peg > 3.5:
        peg_flag = "red"
    else:
        peg_flag = "na"
    add("תמחור", "מחיר ביחס לצמיחה (PEG)", _num(peg), peg_flag, W_PEG,
        "המחיר מוצדק לעומת קצב הצמיחה" if peg_flag == "green" else
        ("יקר מאוד ביחס לצמיחה" if peg_flag == "red" else "תמחור סביר-עד-מלא ביחס לצמיחה"))
    ps = g("priceToSalesTrailing12Months")
    if ps is None:
        ps_flag = "na"
    elif ps < 10:
        ps_flag = "green"
    elif ps > 20:
        ps_flag = "red"                              # >20x sales = speculative (catches pre-revenue hype)
    else:
        ps_flag = "na"
    add("תמחור", "מחיר ביחס למכירות (P/S)", _num(ps), ps_flag, W_PS,
        "תמחור הגיוני מול ההכנסות" if ps_flag == "green" else
        ("ספקולטיבי מאוד — השווי גבוה פי עשרות מההכנסות בפועל" if ps_flag == "red"
         else "תמחור גבוה-בינוני מול ההכנסות"))

    # ---- Layer 3: תזרים מזומנים ----
    ocf = g("operatingCashflow")
    ni = g("netIncomeToCommon")
    quality_known = ocf is not None and ni is not None
    quality_ok = quality_known and ni > 0 and ocf >= ni
    add("תזרים מזומנים", "איכות הרווח (מזומן מול 'רווח על הנייר')",
        f"מזומן {_money(ocf)} מול רווח {_money(ni)}", f3(quality_ok, quality_known), W_QUALITY,
        "הרווח באמת נכנס לבנק" if quality_ok else "הרווח קיים יותר על הנייר מאשר במזומן בפועל")
    fcf = g("freeCashflow")
    add("תזרים מזומנים", "תזרים מזומנים חופשי (FCF)", _money(fcf), f3((fcf or 0) > 0, fcf is not None), W_FCF,
        "נשאר מזומן טהור אחרי הכל" if (fcf or 0) > 0 else "שורפת מזומן — תלויה בגיוסים")

    # ---- Layer 4: חוסן ואיתנות ---- (cash-flow-aware: strong FCF can cover debt comfortably)
    cash, debt, de, cr = g("totalCash"), g("totalDebt"), g("debtToEquity"), g("currentRatio")
    debt_known = any(v is not None for v in (cash, debt, de, cr))
    debt_ok = (
        (cash is not None and debt is not None and cash >= debt) or              # net cash
        (fcf is not None and fcf > 0 and debt is not None and debt <= 5 * fcf) or # ~5y of FCF clears it
        (de is not None and de < 100) or                                          # modest leverage
        (cr is not None and cr >= 1.5 and (de is None or de < 200))               # liquid, not extreme
    )
    add("חוסן ואיתנות", "חוב מול מזומן/תזרים", f"מזומן {_money(cash)} מול חוב {_money(debt)}",
        f3(debt_ok, debt_known), W_DEBT,
        "מספיק מזומן/תזרים כדי לכסות את החוב בנוחות" if debt_ok else "החוב כבד יחסית למזומן ולתזרים")
    roe = g("returnOnEquity")
    add("חוסן ואיתנות", "יעילות הנהלה (ROE)", _pct(roe), f3((roe or 0) >= 0.15, roe is not None), W_ROE,
        "ההנהלה מייצרת תשואה גבוהה על הכסף" if (roe or 0) >= 0.15 else "תשואה נמוכה על ההון המושקע")

    # ---- Layer 5: איתותים לעתיד ----
    eg = g("earningsGrowth") or g("earningsQuarterlyGrowth")
    tgt, price = g("targetMeanPrice"), g("currentPrice")
    fwd_known = eg is not None or (tgt is not None and price is not None)
    fwd_ok = ((eg or 0) > 0) or (tgt is not None and price is not None and tgt > price * 1.05)
    fwd_val = "צופים שיפור" if fwd_ok else ("צופים האטה" if fwd_known else "אין נתון")
    add("איתותים לעתיד", "תחזית קדימה (צמיחת רווח/מחיר יעד)", fwd_val, f3(fwd_ok, fwd_known), W_FORWARD,
        "ההמשך צפוי להיות טוב יותר" if fwd_ok else "התחזיות לא מלהיבות")
    ins = data.get("insider_net")
    ins_known = ins is not None
    add("איתותים לעתיד", "אמון פנימי (קניות מנהלים)",
        ("קונים" if (ins or 0) > 0 else "מוכרים") if ins_known else "אין נתון",
        f3((ins or 0) > 0, ins_known), W_INSIDER,
        "מנהלים קונים מהכסף שלהם — אמון אמיתי" if (ins or 0) > 0 else "אין קנייה פנימית בולטת")
    # analyst consensus + price-target upside
    rec = g("recommendationKey")
    nop = g("numberOfAnalystOpinions")
    upside = (tgt / price - 1) if (tgt and price) else None
    analyst_known = (rec not in (None, "none")) or upside is not None
    analyst_ok = (rec in ("buy", "strong_buy")) or (upside is not None and upside > 0.10)
    analyst_bad = (rec in ("sell", "strong_sell")) or (upside is not None and upside < -0.05)
    a_flag = "green" if analyst_ok else ("red" if analyst_bad else ("na" if not analyst_known else "na"))
    a_val = f"{rec or '?'}" + (f", יעד {upside:+.0%}" if upside is not None else "") + (f" ({nop} אנליסטים)" if nop else "")
    add("איתותים לעתיד", "קונצנזוס אנליסטים + יעד מחיר", a_val, a_flag, W_ANALYST,
        "האנליסטים אופטימיים והיעד מעל המחיר" if analyst_ok else
        ("האנליסטים שליליים / היעד מתחת למחיר" if analyst_bad else "עמדת האנליסטים נייטרלית"))
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
    add("איתותים לעתיד", "שורט (הימור נגד המניה)", _pct(sf) if sf is not None else "אין נתון", sf_flag, W_SHORT,
        "כמעט אין מי שמהמר נגד המניה" if sf_flag == "green" else
        ("שורט גבוה — השוק מהמר נגדה (אך יש פוטנציאל סקוויז)" if sf_flag == "red" else "רמת שורט בינונית"))
    # earnings track record: did it beat estimates recently?
    eb = data.get("earn_beats")
    if eb:
        beats, tot = eb
        es_ok = beats >= max(1, round(tot * 0.75))
        add("איתותים לעתיד", "עקביות מול תחזיות (Beats)", f"{beats}/{tot} רבעונים מעל הציפיות",
            "green" if es_ok else "red", W_SURPRISE,
            "מכה את תחזיות האנליסטים בעקביות" if es_ok else "מאכזבת מול הציפיות לא פעם")

    # ---- Layer 6: מגן ופינוק ----
    dy, bb = g("dividendYield"), data.get("buyback")
    ret_known = dy is not None or bb is not None
    ret_ok = (dy is not None and dy > 0) or bb is True
    ret_val = []
    if dy:
        ret_val.append(f"דיבידנד {_pct(dy if dy < 1 else dy / 100)}")
    if bb:
        ret_val.append("רכישה עצמית")
    add("מגן ופינוק", "החזר הון (דיבידנד / Buyback)", ", ".join(ret_val) or ("לא" if ret_known else "אין נתון"),
        f3(ret_ok, ret_known), W_RETURNS,
        "מפנקת את המשקיעים בכסף חזרה" if ret_ok else "לא מחזירה כסף ישיר למשקיעים")
    moat_known = gm is not None and roe is not None
    moat_ok = (gm or 0) >= 0.4 and (roe or 0) >= 0.15      # pricing power + high returns = likely moat
    add("מגן ופינוק", "חפיר כלכלי (Moat)", "סימנים לחפיר" if moat_ok else ("חלש" if moat_known else "אין נתון"),
        "green" if moat_ok else "na", W_MOAT,
        "שוליים גבוהים + תשואה גבוהה = יתרון תחרותי קשה להעתקה" if moat_ok else "אין סימן ברור ליתרון תחרותי בנתונים")

    # ---- score: weighted, over the flags we actually know ----
    total = sum(it["weight"] for it in items)
    earned = sum(it["weight"] for it in items if it["flag"] == "green")
    possible = sum(it["weight"] for it in items if it["flag"] in ("green", "red"))
    score = round(10 * earned / possible) if possible else 0
    coverage = possible / total if total else 0.0

    flagof = lambda part: next((it["flag"] for it in items if part in it["label"]), "na")
    net_red = flagof("רווח נקי") == "red"
    fcf_red = flagof("FCF") == "red"
    ps_red = flagof("P/S") == "red"
    # "richly valued" = good business but not cheap; a mild caveat, not a health problem
    rich = (pe is not None and pe > 30) or (peg is not None and peg > 2.5) or ps_red

    # Hard caps so an obviously risky stock can never read as "excellent":
    caps = []
    if net_red and fcf_red:                 # losing money AND burning cash = speculative
        score = min(score, 4); caps.append("מפסידה כסף ושורפת מזומן")
    if ps_red:                              # priced at a huge multiple of actual sales
        score = min(score, 6); caps.append("תמחור ספקולטיבי (מכפיל מכירות עצום)")
    elif rich:                              # great company but fully priced -> can't be a perfect 10
        score = min(score, 9)
    # Sparse data must not inflate the score — a 10/10 off 1-2 known flags is meaningless.
    if coverage < 0.30:
        score = min(score, 4); confidence = "very_low"
    elif coverage < 0.50:
        score = min(score, 6); confidence = "low"
    else:
        confidence = "ok"

    verdict = ("מצוין" if score >= 8 else "טוב" if score >= 6 else "בינוני" if score >= 4 else "חלש")
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
    rev = _find(items, "צמיחת הכנסות")
    roe = _find(items, "ROE")

    if green("צמיחת הכנסות") and green("PEG"):
        opp = f"צומחת מהר ({rev['value']}) ועדיין לא יקרה ביחס לצמיחה — אם הקצב נמשך, השוק עוד לא תמחר את זה."
    elif green("FCF") and green("החזר הון"):
        opp = "מכונת מזומנים שמחזירה כסף למשקיעים — בסיס יציב שמושך קונים."
    elif green("ROE"):
        opp = f"ההנהלה מייצרת תשואה גבוהה על הכסף ({roe['value']}) — מנוע איכותי לאורך זמן."
    elif green("צמיחת הכנסות"):
        opp = f"ההכנסות צומחות יפה ({rev['value']}) — יש רוח גבית עסקית."
    else:
        opp = "אין כרגע זרז צמיחה בולט בנתונים — ההזדמנות תלויה בעיקר בתמונה הטכנית."

    if red("רווח נקי") and red("FCF"):
        dgr = "מפסידה כסף ושורפת מזומן — כדי לשרוד היא מגייסת הון ומדללת אתכם בשקט."
    elif red("חוב מול מזומן"):
        dgr = "החוב גדול מהמזומן — רבעון חלש או עליית ריבית עלולים ללחוץ אותם בשקט."
    elif red("P/S"):
        dgr = "תמחור ספקולטיבי — השווי גבוה פי עשרות מההכנסות בפועל; כל אכזבה תפיל אותה חזק."
    elif red("איכות הרווח"):
        dgr = "הרווח קיים על הנייר אבל פחות ממנו נכנס כמזומן — סימן אזהרה שרבים מפספסים."
    elif red("רווח נקי"):
        dgr = "עדיין לא רווחית בשורה התחתונה — שורפת כסף עד שתתהפך."
    elif red("FCF"):
        dgr = "שורפת מזומן חופשי — תלויה ביכולת לגייס עוד כסף."
    elif red("P/E") or red("PEG"):
        dgr = "תמחור גבוה — מתומחרות בה ציפיות שצריך לעמוד בהן, אחרת תיפול."
    elif rich:
        dgr = "החברה איכותית אבל מתומחרת ביוקר — הציפיות כבר בפנים, ויש מעט מקום לטעות אם רבעון יאכזב."
    else:
        dgr = "לא נמצאה סכנה שקטה בולטת בדוחות — הסיכון העיקרי הוא תנודתיות השוק."
    return opp, dgr


FLAG_EMOJI = {"green": "🟢", "red": "🔴", "na": "❓"}
_LAYERS = ["רווחיות", "תמחור", "תזרים מזומנים", "חוסן ואיתנות", "איתותים לעתיד", "מגן ופינוק"]
_LAYER_TITLE = {
    "רווחיות": "שכבה 1 — רווחיות (המנוע עובד?)",
    "תמחור": "שכבה 2 — תמחור (משלם מחיר מופקע?)",
    "תזרים מזומנים": "שכבה 3 — תזרים מזומנים (מציאות מול דמיון)",
    "חוסן ואיתנות": "שכבה 4 — חוסן (תשרוד משבר?)",
    "איתותים לעתיד": "שכבה 5 — איתותים לעתיד",
    "מגן ופינוק": "שכבה 6 — המגן והפינוק",
}


def _ai_layer(sym, res, web=False):
    """If an ANTHROPIC_API_KEY is set, let Sonnet read the real rule-based metrics and write a
    sharper opportunity / danger / bottom-line in Hebrew — catching nuance the rules can't.
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
    sector = res.get("sector") or "לא ידוע"
    web_line = ("יש לך גישה לחיפוש באינטרנט — חפש מידע עדכני (חדשות אחרונות, גיוסי הון/דילול, "
                "שורט, עמדות אנליסטים) כדי לדייק את התשובה.\n" if web else "")
    user = (f"מניה: {sym} | סקטור: {sector} | ציון פונדמנטלי לפי כללים: {res['score']}/10.\n"
            f"נתונים גולמיים מהדוחות: {facts}\n\n"
            f"{web_line}"
            "אתה אנליסט פיננסי בכיר. אל תמציא מספרים שלא נתמכים בנתונים/בחיפוש. ענה בעברית "
            "פשוטה בפורמט המדויק הזה, בלי שום תוספת:\n"
            "הזדמנות: <משפט אחד — מה הדבר שיכול להקפיץ את המניה>\n"
            "סכנה: <משפט אחד — הסכנה השקטה שמסתתרת ושרבים מפספסים>\n"
            "שורה תחתונה: <2-3 משפטים של שיפוט חד וכן, כולל ניואנס שהמספרים היבשים מפספסים>")
    kwargs = dict(
        model=os.environ.get("CHAT_MODEL", "claude-sonnet-4-6"),
        max_tokens=900,
        system="אתה אנליסט פיננסי בכיר שמסביר דברים מסובכים בפשטות. כן, ענייני, בלי הבטחות. זה לא ייעוץ השקעות.",
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
        if s.startswith("הזדמנות:"):
            res["opportunity"] = s.split(":", 1)[1].strip(); in_verdict = False
        elif s.startswith("סכנה:"):
            res["danger"] = s.split(":", 1)[1].strip(); in_verdict = False
        elif s.startswith("שורה תחתונה:"):
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
        return "⚠️ נתונים פונדמנטליים חלקיים מאוד — הציון מוגבל ולא אמין; תתייחס בזהירות רבה."
    if c == "low":
        return "⚠️ נתונים פונדמנטליים חלקיים — הציון נחתך כלפי מטה ופחות אמין."
    return ""


def xray_text(sym, res=None):
    res = res or xray(sym, ai=True, web=True)   # on-demand deep dive -> AI brain + live web search
    if not res.get("ok"):
        return None
    sector = f"  ({res['sector']})" if res.get("sector") else ""
    known = sum(1 for it in res["items"] if it["flag"] in ("green", "red"))
    lines = [f"🩻 רנטגן פונדמנטלי — {sym}{sector}",
             f"ציון בריאות: {res['score']}/10 — {res['verdict']}",
             f"📊 כיסוי נתונים: {known}/{len(res['items'])} בדיקות ({int(res.get('coverage', 0) * 100)}%)"]
    note = _confidence_note(res)
    if note:
        lines.append(note)
    for layer in _LAYERS:
        lines.append("")
        lines.append("🔬 " + _LAYER_TITLE[layer])
        for it in [i for i in res["items"] if i["layer"] == layer]:
            lines.append(f"{FLAG_EMOJI[it['flag']]} {it['label']}: {it['value']} — {it['note']}")
    lines += ["", f"💡 ההזדמנות: {res['opportunity']}", f"⚠️ הסכנה: {res['danger']}"]
    if res.get("ai_verdict"):
        lines += ["", f"🤖 שורה תחתונה (Sonnet): {res['ai_verdict']}"]
    return "\n".join(lines)


def xray_short(sym, res=None):
    res = res or xray(sym)                 # inline in /analyze -> rules only (ai_opinion adds the AI take)
    if not res.get("ok"):
        return None
    note = _confidence_note(res)
    head = f"🩻 ציון בריאות פונדמנטלי: {res['score']}/10 ({res['verdict']})"
    if note:
        head += "\n" + note
    out = (f"{head}\n"
           f"💡 ההזדמנות: {res['opportunity']}\n"
           f"⚠️ הסכנה: {res['danger']}")
    if res.get("ai_verdict"):
        out += f"\n🤖 שורה תחתונה (Sonnet): {res['ai_verdict']}"
    return out
