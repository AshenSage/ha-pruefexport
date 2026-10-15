# HA Prüfexport 1.1.1

- Sicherheitskorrektur für Tapo/TP-Link: Das Feld `credentials_hash` wird jetzt maskiert. Es kann trotz seines Namens rückwandelbare Base64-Zugangsdaten enthalten.
- Ähnliche Feldnamen, geschützte Objekte und Listen werden über die Exportquellen hinweg erkannt: Konfiguration, Laufzeitdaten, YAML, Skripte, Logs und sensible URL-Parameter.
- JSON-/Base64-Zugangsdaten und Basic-Auth werden begrenzt erkannt. Enthaltene Klartextwerte werden zusätzlich an anderen Stellen maskiert. Öffentliche Daten und Templates bleiben auswertbar.

Nach dem HACS-Update Home Assistant vollständig neu starten und einen neuen Export erstellen. Vorhandene ZIPs bleiben unverändert und können weiterhin Zugangsdaten enthalten. Die vorhandene Dashboardkarte bleibt verwendbar.

Geprüft: 98 Offline-Tests, Python-/JSON-/YAML-Prüfung und die tatsächlichen JavaScript-Templates der Karte. Kein Live-Test auf einem HA-Server.
