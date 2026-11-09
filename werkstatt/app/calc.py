"""Kalkulation: Maschinenstundensätze, Abnutzung, Auftragskosten, Schnellrechner."""
import math

from . import settings


def r2(x):
    return round((x or 0) + 0.0, 2)


def f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def machine_rates(m, parts):
    """€ pro Betriebsstunde, aufgeteilt."""
    lh = f(m.get("lebensdauer_h"))
    abschreibung = f(m.get("anschaffung_preis")) / lh if lh > 0 else 0
    verschleiss = sum(f(p["preis"]) / f(p["lebensdauer_h"]) for p in parts if f(p["lebensdauer_h"]) > 0)
    verschleiss += f(m.get("wartung_eur_h"))
    strom = f(m.get("leistung_w")) / 1000 * settings.num("strompreis", 0.3)
    return {"abschreibung": abschreibung, "verschleiss": verschleiss, "strom": strom,
            "satz": abschreibung + verschleiss + strom}


def material_cost(mat, menge):
    if not mat:
        return 0.0
    q = f(menge)
    if (mat.get("einheit") or "") == "kg":
        q = q / 1000.0  # Eingabe in Gramm
    return q * f(mat.get("preis")) * (1 + settings.num("ausschuss_pct", 0) / 100)


def round_price(x):
    step = settings.num("rundung", 0)
    if step <= 0:
        return r2(x)
    return r2(math.ceil(round(x / step, 6)) * step)


def enrich(data):
    """Rechnet Kennzahlen in die geladenen Tabellen ein (in place)."""
    parts_by_m = {}
    for p in data["wear_parts"]:
        parts_by_m.setdefault(p["machine_id"], []).append(p)
    mats = {m["id"]: m for m in data["materials"]}
    persons = {p["id"]: p for p in data["persons"]}

    job_h = {}
    for j in data["order_jobs"]:
        job_h[j["machine_id"]] = job_h.get(j["machine_id"], 0) + f(j["dauer_h"])
    # Drucke aus Home Assistant ohne Auftrag (privat, offen) nutzen die Maschine auch ab
    frei_h = {}
    for p in data.get("prints", []):
        if not p.get("job_id"):
            frei_h[p["machine_id"]] = frei_h.get(p["machine_id"], 0) + f(p["dauer_h"])

    machines = {}
    for m in data["machines"]:
        rates = machine_rates(m, parts_by_m.get(m["id"], []))
        h_auftr = job_h.get(m["id"], 0)
        h_frei = frei_h.get(m["id"], 0)
        h_ges = f(m["stunden_vorher"]) + h_auftr + h_frei
        lh = f(m["lebensdauer_h"])
        m.update({k: round(v, 3) for k, v in rates.items()})
        m["stunden_auftraege"] = r2(h_auftr)
        m["stunden_ha_frei"] = r2(h_frei)
        m["stunden_gesamt"] = r2(h_ges)
        m["verbraucht_pct"] = r2(h_ges / lh * 100) if lh > 0 else 0
        m["abnutzung_eur"] = r2(h_ges * (rates["abschreibung"] + rates["verschleiss"]))
        m["restwert"] = r2(max(0.0, f(m["anschaffung_preis"]) - h_ges * rates["abschreibung"]))
        m["faellig"] = 0
        for p in parts_by_m.get(m["id"], []):
            seit = h_ges - f(p["gewechselt_bei_h"])
            p["stunden_seit"] = r2(seit)
            p["pct"] = r2(seit / f(p["lebensdauer_h"]) * 100) if f(p["lebensdauer_h"]) > 0 else 0
            p["eur_h"] = round(f(p["preis"]) / f(p["lebensdauer_h"]), 4) if f(p["lebensdauer_h"]) > 0 else 0
            if p["pct"] >= 100:
                m["faellig"] += 1
        machines[m["id"]] = m

    # Kosten pro Auftrag
    per = {o["id"]: {"maschine": 0.0, "material": 0.0, "arbeit": 0.0, "fremd": 0.0, "stunden_arbeit": 0.0,
                     "stunden_maschine": 0.0, "umsatz": 0.0, "stueck": 0.0} for o in data["orders"]}
    for j in data["order_jobs"]:
        k = per.get(j["order_id"])
        if k is None:
            continue
        m = machines.get(j["machine_id"])
        if j.get("kwh") is not None and m:
            # gemessener Strom statt Schätzung über die mittlere Leistung
            j["kosten_maschine"] = r2(f(j["dauer_h"]) * (m["abschreibung"] + m["verschleiss"])
                                      + f(j["kwh"]) * settings.num("strompreis", 0.3))
        else:
            j["kosten_maschine"] = r2(f(j["dauer_h"]) * (m["satz"] if m else 0))
        j["kosten_material"] = r2(material_cost(mats.get(j["material_id"]), j["menge"]))
        k["maschine"] += j["kosten_maschine"]
        k["material"] += j["kosten_material"]
        k["stunden_maschine"] += f(j["dauer_h"])
        k["stueck"] += f(j["stueck"])
    for t in data["order_times"]:
        k = per.get(t["order_id"])
        if k is None:
            continue
        p = persons.get(t["person_id"])
        t["kosten"] = r2(f(t["stunden"]) * (f(p["stundensatz"]) if p else 0))
        k["arbeit"] += t["kosten"]
        k["stunden_arbeit"] += f(t["stunden"])
    for x in data["order_costs"]:
        k = per.get(x["order_id"])
        if k is not None:
            k["fremd"] += f(x["betrag"])
    for it in data["order_items"]:
        k = per.get(it["order_id"])
        if k is not None:
            k["umsatz"] += f(it["menge"]) * f(it["einzelpreis"])

    std_auf = settings.num("aufschlag_pct", 30)
    for o in data["orders"]:
        k = per[o["id"]]
        selbst = k["maschine"] + k["material"] + k["arbeit"] + k["fremd"]
        auf = f(o["aufschlag_pct"]) if o.get("aufschlag_pct") not in (None, "") else std_auf
        k = {kk: r2(v) for kk, v in k.items()}
        k["selbstkosten"] = r2(selbst)
        k["aufschlag_pct"] = auf
        k["empfohlen"] = round_price(selbst * (1 + auf / 100)) if selbst else 0
        k["gewinn"] = r2(k["umsatz"] - selbst)
        o["kosten"] = k
    return data


def quick(inp, machines, parts, materials, persons):
    """Schnellrechner ohne Auftrag.

    Mehrere Zeilen möglich: jobs=[{machine_id, material_id, dauer_h, menge}], arbeit=[{person_id, stunden}],
    extras=[{bezeichnung, betrag}]. Die alten Einzelfelder (machine_id, dauer_h, …) gehen weiterhin.
    """
    jobs = inp.get("jobs")
    if jobs is None:
        jobs = [{k: inp.get(k) for k in ("machine_id", "material_id", "dauer_h", "menge")}]
    arbeit = inp.get("arbeit")
    if arbeit is None:
        arbeit = [{"person_id": inp.get("person_id"), "stunden": inp.get("arbeit_h")}]
    extras = inp.get("extras")
    if extras is None:
        extras = [{"bezeichnung": "", "betrag": inp.get("extra")}]

    out_jobs, k_m, k_mat = [], 0.0, 0.0
    for j in jobs:
        m = next((x for x in machines if x["id"] == j.get("machine_id")), None)
        mat = next((x for x in materials if x["id"] == j.get("material_id")), None)
        satz = machine_rates(m, [x for x in parts if m and x["machine_id"] == m["id"]]) if m else None
        km = f(j.get("dauer_h")) * (satz["satz"] if satz else 0)
        kmat = material_cost(mat, j.get("menge"))
        k_m += km
        k_mat += kmat
        out_jobs.append({"maschine": r2(km), "material": r2(kmat),
                         "satz_detail": {k: round(v, 3) for k, v in satz.items()} if satz else None})
    out_arb, k_arb = [], 0.0
    for a in arbeit:
        p = next((x for x in persons if x["id"] == a.get("person_id")), None)
        ka = f(a.get("stunden")) * (f(p["stundensatz"]) if p else 0)
        k_arb += ka
        out_arb.append({"kosten": r2(ka), "stundensatz": f(p["stundensatz"]) if p else 0})
    k_extra = sum(f(x.get("betrag")) for x in extras)
    satz = out_jobs[0]["satz_detail"] if len(out_jobs) == 1 else None
    selbst = k_m + k_mat + k_arb + k_extra
    auf = f(inp.get("aufschlag_pct")) if inp.get("aufschlag_pct") not in (None, "") else settings.num("aufschlag_pct", 30)
    stueck = max(1.0, f(inp.get("stueck")) or 1.0)
    netto = selbst * (1 + auf / 100)
    ust = 0 if settings.flag("kleinunternehmer") else settings.num("ust_satz", 20)
    return {
        "maschine": r2(k_m), "material": r2(k_mat), "arbeit": r2(k_arb), "extra": r2(k_extra),
        "satz": satz["satz"] if satz else 0,
        "satz_detail": satz,
        "jobs": out_jobs, "arbeit_zeilen": out_arb,
        "selbstkosten": r2(selbst), "aufschlag_pct": auf,
        "netto": r2(netto), "netto_gerundet": r2(round_price(netto / stueck) * stueck),
        "stueck": stueck, "netto_stueck": r2(netto / stueck), "netto_stueck_gerundet": round_price(netto / stueck),
        "ust_satz": ust, "brutto_stueck": r2(round_price(netto / stueck) * (1 + ust / 100)),
        "gewinn": r2(netto - selbst),
    }
