# Änderungen

## 1.1.1 · 15.10.2026

- Sicherheitskorrektur: Tapo/TP-Link `credentials_hash` auch in Integrationseinträgen und `.storage/core.config_entries` maskieren. Der Feldinhalt kann rückwandelbare Base64-Zugangsdaten enthalten.
- Varianten sensibler Feldnamen einschliesslich CamelCase, Grossbuchstaben und Hash-/Daten-Suffixen einheitlich in JSON, YAML, Skripten, Logs und URL-Parametern erkennen.
- Geschützte Objekte und Listen vollständig maskieren; YAML-Verweise und `!secret`-Tags erhalten.
- JSON-/Base64-Zugangsdaten und Basic-Auth begrenzt erkennen und darin enthaltene Klartextwerte für den globalen Abgleich lernen. Öffentliche kodierte JSON-Daten bleiben erhalten.
- Wiederholte Maskierung darf Platzhalter nicht zu neuen Geheimnissen erklären. Ursprüngliche Zugangsdaten, die selbst einem Platzhalter entsprechen, bleiben geschützt.
- Lange öffentliche Frontend-Zeichenfolgen ohne wiederholtes Scannen ihrer Namenssuffixe verarbeiten.
- 14 zusätzliche Offline-Regressionen; bestehende Tests für Namenskollisionen und kurze PINs an die erweiterte Erkennung beziehungsweise zufällige Prüfsummen-Kollisionen angepasst.

## 1.1.0 · 15.10.2026

- Kurze Alarm-PINs unter `code` in YAML-Aktionen, Live-Definitionen und gespeicherten Traces maskieren; öffentliche Codes und Templates erhalten.
- Numerische und kurze bekannte Secret-Werte als ganze YAML-/JSON-Skalare abgleichen; Zeitstempel und Entitätsnamen bleiben lesbar.
- Geladene Automations-/Skriptdefinitionen und HA-Entitätsreferenzen einschliesslich aufgelöster Blueprint-Verweise ergänzen.
- Die 100 Recorder-Plätze abwechselnd auf Automationen, Skripte und Dashboards verteilen; Herkunft, ausgeschlossene und nicht ausgewählte Entitäten dokumentieren. Die Grenzen von 48 Stunden, 10000 Zeilen und 40 Sekunden bleiben bestehen.
- Erwartete Umfangshinweise von tatsächlichen Erfassungslücken trennen; nur letztere erzeugen den Status `teilweise`. Manifest und Sensor nennen Hinweise separat.
- Kartenbeschriftung auf „Erfassungslücken im Bericht“ präzisieren; ältere Karten bleiben funktionsfähig.
- Zehn zusätzliche Offline-Regressionen für PINs, YAML-Aliase, faire Verlaufsauswahl und Statusunterscheidung.

## 1.0.9 · 13.10.2026

- Ungültiges YAML mit Parser-Fehlerart, Zeile und Spalte direkt im Inventar und Bericht dokumentieren; sensibler Rohtext bleibt ausgeschlossen.
- Regressionen für geheimnishaltiges ungültiges YAML und gültige zitierte Doppelpunkte.
- Stabile HACS-Releases werden vor Veröffentlichung automatisch geprüft.

## Dashboardkarte · 11.10.2026

- Kompaktes Layout mit flachen Aktionsknöpfen und mindestens 44 Pixel Bedienhöhe.
- Fortschrittsbalken und Prozentwert nur während eines laufenden Exports; aktueller
  Schritt, Bearbeitungszähler und Laufzeit ohne doppelte Statuszeilen.
- Nach Abschluss kurze ZIP-Zusammenfassung mit Datum, Grösse und Dateianzahl.
- Hinweise auf Erfassungsgrenzen bleiben sichtbar. Ausführliche Sensorattribute,
  Fehlerdetails und Versionsnummer über Antippen der Statuskarte erreichbar.
- Vorheriges Archiv auch nach einem Fehler klar als solches bezeichnet;
  geschützter Download und gesperrter Start während eines Laufs bleiben erhalten.
- Reine Kartenänderung, kompatibel mit Integration 1.0.8; Karten-YAML im Dashboard
  einmal vollständig ersetzen. Kein Integrationsupdate oder HA-Neustart nötig.

## 1.0.8

- Automatisch erzeugte Lovelace-Übersichten werden anhand der HA-Info als solche
  dokumentiert. Echte Ladefehler und Recovery-Zustände bleiben Exportlücken.
- Begrenzten HA-Fehlerspeicher mit Warnungen und Fehlern lesend ergänzt, auch wenn
  kein lokales Core-Log vorliegt. Nachrichten werden zusätzlich auf Zugangsdaten-
  Zuweisungen geprüft; die Erfassung bleibt kein vollständiger Core-/Supervisor-Logexport.
- Recorder-Zeilenbudget fair je Entität verteilt. Häufige Zähler verdrängen keine
  anderen Entitäten; Kürzungen und Zeilenzähler werden je Entität dokumentiert.
- Öffentliche ConnectLife-Buttonkennungen in nachgewiesenen Datenwörterbüchern
  erhalten; allgemeine Schlüssel und tatsächlich erkannte Geheimnisse bleiben maskiert.
- Lovelace-Ressourcenspeicher ergänzt, unbekannte Dateiformate ausdrücklich gemeldet.
- Ausschlüsse für Medien/Backup/Export auf die Konfigurationswurzel begrenzt;
  gleichnamige funktionale Unterordner von Integrationen werden erfasst.
- Den während des Eigenexports aufgenommenen Status und die Grenzen gespeicherter
  Traces ausdrücklich erläutert.

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
