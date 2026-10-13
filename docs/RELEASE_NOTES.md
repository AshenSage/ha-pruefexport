# HA Prüfexport 1.0.9

Ungültige YAML-Dateien bleiben aus dem Prüfarchiv ausgeschlossen. Das Dateiinventar und der Exportbericht nennen jetzt die Parser-Fehlerart sowie Zeile und Spalte, damit sich die Ursache auch ohne vollständige HA-Logs finden lässt. Rohdatei, Parser-Snippets und möglicherweise enthaltene Zugangsdaten werden weiterhin nicht exportiert.

Normales stabiles HACS-Release. Nach dem Update Home Assistant neu starten. Bestehende Integration und Dashboardkarte bleiben verwendbar.

Geprüft: vollständige Offline-Tests, Python-/JSON-/YAML-Prüfung und die tatsächlichen JavaScript-Templates der Karte. Regressionen prüfen eine ungültige YAML-Datei mit synthetischem Geheimnis sowie eine gültige Beschreibung mit zitiertem Doppelpunkt. Die Prüfungen benötigen keine Verbindung zum eigenen HA.
