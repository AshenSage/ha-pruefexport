# HA Prüfexport 1.1.0

- Kurze Alarm-PINs in YAML-Aktionen, Laufzeitdefinitionen und gespeicherten Traces werden maskiert. Kurze/numerische bekannte Secrets werden als ganze YAML-/JSON-Werte abgeglichen. Öffentliche Codes und Templates bleiben erhalten.
- Die Verlaufsauswahl berücksichtigt jetzt Automationen und Skripte einschliesslich aufgelöster HA-Blueprint-Referenzen sowie Dashboards. Die begrenzten Plätze werden abwechselnd vergeben; Herkunft und ausgelassene Entitäten sind dokumentiert.
- Erwartete Umfangshinweise stehen getrennt von echten Erfassungslücken im Bericht und Manifest. Nur echte Lücken führen zu `teilweise`; der Sensor nennt beide Anzahlen.

Nach dem HACS-Update Home Assistant vollständig neu starten und einen neuen Export erstellen. Vorhandene ZIPs bleiben unverändert. Für die präzisere Beschriftung „Erfassungslücken im Bericht“ die Karten-YAML einmal vollständig ersetzen; die bisherige Karte bleibt verwendbar.

Geprüft: 84 Offline-Tests, Python-/JSON-/YAML-Prüfung und die tatsächlichen JavaScript-Templates der Karte. Kein Live-Test auf einem HA-Server.
