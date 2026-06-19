"""Fundamental 'X-ray' for a stock — 6 layers, green/red flags, a weighted 0-10 health
score, and a plain-Hebrew bottom line. Uses only free yfinance data. Best-effort: any
metric we can't fetch is marked ❓ and left OUT of the score so it isn't unfairly punished.

Public API:
    xray(sym)            -> dict {ok, sym, score, verdict, items, opportunity, danger, sector}
    xray_text(sym)       -> full multi-layer Hebrew report (str) or None
    xray_short(sym)      -> one-block summary: score + opportunity + danger (str) or None
"""

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


def _fetch(sym):
    t = yf.Ticker(sym)
    try:
        info = t.info or {}
    except Exception:
        info = {}
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
    return out


def evaluate(data):
    """Turn raw fundamentals into scored, flagged, explained items + a bottom line."""
    info = data.get("info") or {}
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

    # ---- Layer 2: תמחור ----
    pe = g("trailingPE") or g("forwardPE")
    add("תמחור", "מכפיל רווח (P/E)", _num(pe), f3(pe is not None and 0 < pe < 25, pe is not None), W_PE,
        "מחיר סביר ביחס לרווחים" if (pe and 0 < pe < 25) else "יקרה — צריך שנים רבות להחזיר את ההשקעה מהרווח")
    peg = g("trailingPegRatio") or g("pegRatio")
    add("תמחור", "מחיר ביחס לצמיחה (PEG)", _num(peg), f3(peg is not None and 0 < peg <= 1.5, peg is not None), W_PEG,
        "המחיר מוצדק לעומת קצב הצמיחה" if (peg and 0 < peg <= 1.5) else "יקרה ביחס לכמה שהיא צומחת")

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

    # ---- Layer 4: חוסן ואיתנות ----
    cash, debt, de = g("totalCash"), g("totalDebt"), g("debtToEquity")
    debt_known = (cash is not None and debt is not None) or de is not None
    debt_ok = (cash is not None and debt is not None and cash >= debt) or (de is not None and de < 80)
    add("חוסן ואיתנות", "חוב מול מזומן", f"מזומן {_money(cash)} מול חוב {_money(debt)}",
        f3(debt_ok, debt_known), W_DEBT,
        "מספיק כסף פנוי כדי לשרוד משבר" if debt_ok else "החוב גדול — חשופה ללחץ אם משהו משתבש")
    roe = g("returnOnEquity")
    add("חוסן ואיתנות", "יעילות הנהלה (ROE)", _pct(roe), f3((roe or 0) >= 0.15, roe is not None), W_ROE,
        "ההנהלה מייצרת תשואה גבוהה על הכסף" if (roe or 0) >= 0.15 else "תשואה נמוכה על ההון המושקע")

    # ---- Layer 5: איתותים לעתיד ----
    eg = g("earningsGrowth") or g("earningsQuarterlyGrowth")
    tgt, price = g("targetMeanPrice"), g("currentPrice")
    fwd_known = eg is not None or (tgt is not None and price is not None)
    fwd_ok = ((eg or 0) > 0) or (tgt is not None and price is not None and tgt > price * 1.05)
    fwd_val = "צופים שיפור" if fwd_ok else ("צופים האטה" if fwd_known else "אין נתון")
    add("איתותים לעתיד", "תחזית קדימה (רווח/יעד אנליסטים)", fwd_val, f3(fwd_ok, fwd_known), W_FORWARD,
        "ההמשך צפוי להיות טוב יותר" if fwd_ok else "התחזיות לא מלהיבות")
    ins = data.get("insider_net")
    ins_known = ins is not None
    add("איתותים לעתיד", "אמון פנימי (קניות מנהלים)",
        ("קונים" if (ins or 0) > 0 else "מוכרים") if ins_known else "אין נתון",
        f3((ins or 0) > 0, ins_known), W_INSIDER,
        "מנהלים קונים מהכסף שלהם — אמון אמיתי" if (ins or 0) > 0 else "אין קנייה פנימית בולטת")

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
    earned = sum(it["weight"] for it in items if it["flag"] == "green")
    possible = sum(it["weight"] for it in items if it["flag"] in ("green", "red"))
    score = round(10 * earned / possible) if possible else 0
    verdict = ("מצוין" if score >= 8 else "טוב" if score >= 6 else "בינוני" if score >= 4 else "חלש")

    opportunity, danger = _bottom_line(items)
    return {"items": items, "score": score, "verdict": verdict,
            "opportunity": opportunity, "danger": danger,
            "sector": info.get("sector"), "known": possible > 0}


def _find(items, label_part):
    for it in items:
        if label_part in it["label"]:
            return it
    return None


def _bottom_line(items):
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

    if red("חוב מול מזומן"):
        dgr = "החוב גדול מהמזומן — רבעון חלש או עליית ריבית עלולים ללחוץ אותם בשקט."
    elif red("איכות הרווח"):
        dgr = "הרווח קיים על הנייר אבל פחות ממנו נכנס כמזומן — סימן אזהרה שרבים מפספסים."
    elif red("רווח נקי"):
        dgr = "עדיין לא רווחית בשורה התחתונה — שורפת כסף עד שתתהפך."
    elif red("FCF"):
        dgr = "שורפת מזומן חופשי — תלויה ביכולת לגייס עוד כסף."
    elif red("P/E") or red("PEG"):
        dgr = "תמחור גבוה — מתומחרות בה ציפיות שצריך לעמוד בהן, אחרת תיפול."
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


def xray(sym):
    try:
        res = evaluate(_fetch(sym))
        res.update({"ok": res.get("known", False), "sym": sym})
        return res
    except Exception:
        return {"ok": False, "sym": sym}


def xray_text(sym, res=None):
    res = res or xray(sym)
    if not res.get("ok"):
        return None
    sector = f"  ({res['sector']})" if res.get("sector") else ""
    lines = [f"🩻 רנטגן פונדמנטלי — {sym}{sector}",
             f"ציון בריאות: {res['score']}/10 — {res['verdict']}"]
    for layer in _LAYERS:
        lines.append("")
        lines.append("🔬 " + _LAYER_TITLE[layer])
        for it in [i for i in res["items"] if i["layer"] == layer]:
            lines.append(f"{FLAG_EMOJI[it['flag']]} {it['label']}: {it['value']} — {it['note']}")
    lines += ["", f"💡 ההזדמנות: {res['opportunity']}", f"⚠️ הסכנה: {res['danger']}"]
    return "\n".join(lines)


def xray_short(sym, res=None):
    res = res or xray(sym)
    if not res.get("ok"):
        return None
    return (f"🩻 ציון בריאות פונדמנטלי: {res['score']}/10 ({res['verdict']})\n"
            f"💡 ההזדמנות: {res['opportunity']}\n"
            f"⚠️ הסכנה: {res['danger']}")
