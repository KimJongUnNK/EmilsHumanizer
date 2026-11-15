# Beispieltexte neu erzeugen

Die Texte in `beispieltexte/` entstehen in drei Schritten aus de.wikisource.org:

```
python werkzeuge/texte_holen.py roh sachlich:Technik locker:Glosse bericht:Reportage:600 …
python werkzeuge/seiten_einsetzen.py roh seiten
python werkzeuge/texte_aufbereiten.py roh beispieltexte
```

1. `texte_holen.py` lädt alle Seiten der angegebenen Kategorien als Rohtext, abgelegt nach Textsorte (`sachlich`, `bericht`, `locker`). Die Zahl hinter der Kategorie begrenzt, wie viele Texte geholt werden (Standard 600).
2. `seiten_einsetzen.py` füllt Texte auf, die auf Wikisource nur aus eingebundenen Scan-Seiten bestehen (z. B. Artikel aus der "Gartenlaube").
3. `texte_aufbereiten.py` sortiert Gedichte und Listen aus, schneidet Auszüge von 150 bis 400 Wörtern, entfernt Absätze mit rassistischen oder antisemitischen Begriffen und passt die Rechtschreibung an.
