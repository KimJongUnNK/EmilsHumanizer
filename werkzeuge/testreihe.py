"""Testreihe: schreibt feste Testtexte mit einem echten Modell um und prüft jede Ausgabe gegen feste Kriterien.

Aufruf:  python werkzeuge/testreihe.py [--url http://localhost:11434] [--model gemma3:12b] [--runs 1] [--out datei.json]
Die Quellenangaben in den Testtexten sind erfunden.
"""
import argparse
import glob
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import humanizer as h  # noqa: E402


def check(source: str, out: str, style: str) -> dict:
    """Jedes Kriterium als (Messwert, bestanden)."""
    strict = style == "Akademisch"
    # Absätze gleicher Position gehören zusammen; Überschriften und Einzeiler der Vorlage bleiben außen vor.
    pairs = [(a, b) for a, b in zip(h.paragraphs(source), h.paragraphs(out)) if h.needs_rewrite(a)]
    src_paras = [a for a, _ in pairs]
    qualifiers = [q for p in src_paras for q in h.extract_qualifiers(p)]
    count = max(len(h.sentences(out)), 1)
    ratio = len(out.split()) / max(len(source.split()), 1)
    values = {
        "Zahlen fehlen": (h.missing_facts(source, out), lambda v: not v),
        "Zahlen erfunden": (h.added_facts(source, out), lambda v: not v),
        "Quellen fehlen": (h.missing_citations(source, out), lambda v: not v),
        "Quellen verrutscht": ([c for c, _ in h.misplaced_citations(source, out)], lambda v: not v),
        "Einschränkungen fehlen": (h.missing_qualifiers(qualifiers, out), lambda v: len(v) <= 1),
        "neue Verknüpfungen": (sum(e for a, b in pairs for _, e, _ in h.new_connectors(a, b)), lambda v: v <= 1),
        "Sätze ohne Grundlage": ([s[:60] for a, b in pairs for s in h.unsupported_sentences(a, b)], lambda v: len(v) <= 1),
        "Fragmente": (h.fragments(out) if strict else [], lambda v: not v),
        "Abschwächungen fehlen": ([x for a, b in pairs for x in h.missing_hedges(h.extract_hedges(a), b)], lambda v: len(v) <= 1),
        "Verneinungen fehlen": ([x[:60] for a, b in pairs for x in h.missing_negations(a, b)], lambda v: not v),
        "Quellen erfunden": (h.invented_citations(source, out), lambda v: not v),
        "Teilsätze ohne Grundlage": ([x[:60] for a, b in pairs for x in h.unsupported_clauses(a, b)], lambda v: len(v) <= 1),
        "Verneinungen erfunden": ([x[:60] for a, b in pairs for x in h.added_negations(a, b)], lambda v: not v),
        "Wiederholungen": (h.repeated_sentences(out) + [s for s in h.raw_sentences(out) if h.doubled_clauses(s)],
                           lambda v: not v),
        "Aussagen fehlen": ([x[:60] for a, b in pairs for x in h.dropped_statements(a, b)], lambda v: not v),
        # In 98 % der Menschentexte höchstens einer.
        "Füllsätze und Satzmuster-Echos": (h.filler_sentences(out) + [b for _, b in h.echo_pairs(out)], lambda v: len(v) <= 1),
        # An 900 mitgelieferten Menschentexten geeicht: 80 % von ihnen haben höchstens 2, und 80 % der sachlichen
        # eine Streuung ab 0,45.
        "Floskeln": (h.tell_count(out) + len(h.habits(out)), lambda v: v <= 2),
        "Streuung": (h.burstiness(out), lambda v: v >= 0.45),
        "kaum verändert": (len(h.unchanged_sentences(source, out)), lambda v: v <= 0.2 * count),
        # Kürzer ist in Ordnung, solange nichts verloren geht; das prüfen die Kriterien oben.
        "Länge": (round(ratio, 2), lambda v: 0.7 <= v <= 1.2),
    }
    return {name: {"wert": value, "ok": bool(ok(value))} for name, (value, ok) in values.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=h.OLLAMA_URL)
    parser.add_argument("--model", default=h.PREFERRED_MODEL)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--out", default="")
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testtexte")
    results = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.txt"))):
        name = os.path.basename(path)[:-4]
        if args.only and args.only not in name:
            continue
        head, source = open(path, encoding="utf-8").read().split("\n", 1)
        style, source = head.split(":", 1)[1].strip(), source.strip()
        pool, _ = h.plan_pool("Mitgeliefert", style, [])
        for run in range(args.runs):
            start = time.time()
            out, passes, _ = h.humanize_checked(source, style, args.model, args.url, pool, rng=random.Random(run))
            checks = check(source, out, style)
            failed = [k for k, v in checks.items() if not v["ok"]]
            results[f"{name}#{run}"] = {"bestanden": not failed, "durchgefallen": failed, "kriterien": checks,
                                        "sekunden": round(time.time() - start), "durchgaenge": passes, "text": out}
            print(f"{name}#{run}: {'BESTANDEN' if not failed else 'durchgefallen: ' + ', '.join(f'{k} = {checks[k]['wert']}' for k in failed)}",
                  flush=True)
            if args.out:
                json.dump(results, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    passed = sum(r["bestanden"] for r in results.values())
    print(f"\n{passed} von {len(results)} Läufen bestanden")


if __name__ == "__main__":
    main()
