# Änderungen

## 1.0.5

- HACS-Manifest, öffentliche Dokumentation, Issue-Tracker und Codeowner ergänzt.
- Repository enthält genau eine Integration unter `custom_components/ha_pruefexport`.
- Festen persönlichen Projektkontext aus dem Standard-Prüfauftrag entfernt.
  Der Prüfauftrag richtet sich nach der tatsächlich konfigurierten HA-Zeitzone.
- Eigene Vorgaben bleiben über `ha_pruefexport_kontext.md` ergänzbar und werden weiterhin maskiert.
- Die öffentliche Beispielkarte verwendet die konfigurierte HA-Zeitzone mit UTC als Standard;
  Tests verwenden ausschliesslich synthetische Orts- und Zeitangaben.
- Bestehende Dashboardkarte und Export-/Downloadbedienung bleiben verwendbar.

## 1.0.4

- Öffentliche Speicherkennungen in nachgewiesenen HA-Storage-Umschlägen werden erhalten;
  echte und verschachtelte Schlüssel bleiben maskiert.
- Maskierte YAML-Skalarwerte werden bei Bedarf als gültige Zeichenketten geschrieben.
  `!include` und `!secret` bleiben erhalten; nicht sicher maskierbare Dateien werden ausgelassen.
- Frühere Prüfordner mit `ha_pruefung_YYYYMMDD_HHMMSS` werden nicht erneut eingepackt.
- HACS-Ressourcen unter `/hacsfiles/` werden den Dateien unter `www/community/` zugeordnet.
- Fehlende unterstützte lokale HA-Logs werden ausdrücklich als Lücke ausgewiesen.

## 1.0.3

- Maskierungsprüfung und Manifestprüfung auf getrennte Quell- und Metadatenbereiche abgestimmt.
- Dynamischer Ersatzmarker bei Kollisionen mit bekannten Secret-Werten.
- Maskierte Archivnamen, Inventarverweise und Prüfsummen bleiben konsistent.

## 1.0.2

- JSON-Feldnamen und kollidierende maskierte Namen werden berücksichtigt.
- Registry-Erfassung unterstützt iterierbare Gerätesammlungen.
- Bereinigte Fehlerdiagnose mit Arbeitsschritt und Codeposition.

## 1.0.1

- Exportdienst akzeptiert `pruefmodus: methode` und `pruefmodus: gesamt` über ein ausdrückliches Schema.

## 1.0.0

- Lokaler Exportdienst, Statussensor und geschützter ZIP-Download.
