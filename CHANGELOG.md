# Änderungen

## 1.0.7

- Ein gemeinsamer modellagnostischer Prüfauftrag für Exportgrundlage, Exporter,
  Home Assistant und sämtliche exportierten Dashboardkacheln.
- Modusauswahl aus Aktion und Beispielkarte entfernt. Ein Aufruf ohne Parameter
  genügt; bestehende Karten mit dem alten Modusparameter erzeugen ebenfalls
  den gemeinsamen Gesamtprüfauftrag.
- Der Auftrag nennt Dateiliste, Abhängigkeiten, Exportgrenzen und enthaltenen
  Exporter-Code ausdrücklich und verlangt konkrete Änderungen samt Prüfungen.
- Bereits erstellte ZIPs behalten ihre bisherigen Anweisungen; der neue Auftrag
  gilt für frisch erstellte Archive.

## 1.0.6

- Exportstatus meldet gewichteten Fortschritt, Arbeitsschritt und Bearbeitungszähler.
- Regelmässige Statusmeldungen und Laufzeit bleiben auch bei langsamen HA-Abrufen sichtbar.
- Die Karte zeigt Prozentbalken, aktuellen Schritt und letzte Statusmeldung.
  Bei längerer Zeit ohne messbaren Fortschritt erscheint ein Hinweis.
- Laufender Export deaktiviert den Startknopf und kennzeichnet ein vorhandenes ZIP als vorheriges Archiv.
- Wiederholte Startaufrufe lösen keinen zweiten Export und keine Fehlermeldung aus.
- Fortschrittsmeldungen aus dem Dateiarbeiter werden auf den HA-Eventloop übertragen;
  alte Meldungen können einen neuen oder beendeten Lauf nicht überschreiben.
- ZIP-Mitglieder werden bei der CRC-Prüfung stückweise gelesen, um den Abbruch auch
  während grosser Dateien prüfen zu können. Fehlerhafte Archive werden nicht freigegeben.
- Die neue Fortschrittsanzeige erfordert einmalig die aktualisierte Karten-YAML.

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
