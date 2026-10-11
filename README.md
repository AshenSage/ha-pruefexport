# HA Prüfexport

Lokale Home-Assistant-Integration für ein dokumentiertes Prüfarchiv aus Konfiguration,
Dashboards und Laufzeitdaten. Das ZIP wird auf dem HA-System erstellt und kann über
eine authentifizierte Administrator-Sitzung heruntergeladen werden.

Version **1.0.8** · Home Assistant **2026.10.0 oder neuer** · keine zusätzlichen
Python-Abhängigkeiten für die Integration.

## Installation mit HACS

1. HACS öffnen und oben rechts **⋮ → Benutzerdefinierte Repositories** wählen.
2. `https://github.com/AshenSage/ha-pruefexport` eintragen.
3. Typ **Integration** wählen und hinzufügen.
4. **HA Prüfexport** in HACS suchen und herunterladen.
5. Home Assistant vollständig neu starten.
6. Bei einer Erstinstallation unter **Einstellungen → Geräte & Dienste → Integration hinzufügen**
   nach **HA Prüfexport** suchen und den Einrichtungsdialog bestätigen.

Es werden keine Zugangsdaten oder zusätzlichen Tokens benötigt. Die Integration legt
`sensor.ha_pruefexport` an. Falls HA einen abweichenden Entitätsnamen vergibt, diesen
in der optionalen Karten-YAML anpassen.

### Wechsel von einer manuellen Installation

Das Repository einmal wie oben in HACS hinzufügen und dort herunterladen beziehungsweise
erneut herunterladen. HACS verwaltet danach denselben Integrationsordner
`custom_components/ha_pruefexport`. Vorhandene Dateien müssen nicht vorher gelöscht werden.
Anschliessend Home Assistant vollständig neu starten.

Der bestehende Integrationseintrag und die vorhandene Dashboardkarte bleiben verwendbar.
Exportarchive und Statusdatei liegen im aktiven HA-Konfigurationsordner unter
`.ha_pruefexport/`, ausserhalb des Integrationsordners.

### Spätere Updates

Neue Versionen über HACS installieren und Home Assistant vollständig neu starten.
Das manuelle Löschen und Hochladen von Integrationsdateien entfällt.
Ein Neuladen der Integration allein ersetzt den aus `async_setup` registrierten Dienst nicht.

HACS kann veröffentlichte GitHub-Releases verwenden. Solange es keinen Release gibt,
kann die Standardbranch heruntergeladen werden; HACS verwendet dann eine Commitkennung
als Remoteversion. Die Integration selbst meldet ihre Version aus `manifest.json`.

## Export erstellen

Als HA-Administrator die Aktion `ha_pruefexport.export` ausführen:

```yaml
action: ha_pruefexport.export
```

Jedes neue ZIP enthält denselben modellagnostischen Gesamtprüfauftrag in
`PRUEFAUFTRAG.md`: Exportgrundlage und Exporter auf Lücken, Maskierung und
Verbesserungsbedarf prüfen, danach Home Assistant samt allen exportierten
Dashboardkacheln systematisch prüfen und konkrete Änderungen liefern.
Dateiliste, Inventar, Abhängigkeiten, Exportbericht und `KONTEXT.md` begleiten den Auftrag.
Es gibt keine Modusauswahl mehr. Bestehende Karten mit dem früheren Parameter
`pruefmodus: methode` oder `pruefmodus: gesamt` bleiben nutzbar und erzeugen ebenfalls
den gemeinsamen Gesamtprüfauftrag. Bereits erstellte ZIPs behalten ihren alten Auftrag;
nach dem Update ein neues Archiv erstellen.

Die Aktion startet den Export im Hintergrund. Der Sensor zeigt Fortschritt, letzten
Erfolg, Umfang und bereinigte Fehlerdetails. Ein vorheriges fertiges ZIP bleibt auch
nach einem fehlgeschlagenen neuen Versuch erhalten.

### Fortschrittsanzeige ab 1.0.6

Die kompakte Karte zeigt während des Exports Prozentbalken, aktuellen Arbeitsschritt,
verarbeitete Dateien oder Abrufe und Laufzeit. Nach Abschluss zeigt sie nur ZIP-Status,
Datum, Grösse und Dateianzahl. Der Exportstatus wird während eines Laufs
alle zwei Sekunden aktualisiert, auch wenn gerade auf eine HA-Antwort gewartet wird.
Der Startknopf zeigt währenddessen **Läuft …** und startet keinen zweiten Lauf.
Wiederholte Aktionsaufrufe bleiben beim laufenden Export und melden keinen Fehler.

Die Prozentanzeige beschreibt den Fortschritt nach gewichteten Arbeitsschritten und
den Bearbeitungszählern innerhalb eines Schritts. Sie ist keine Restzeitvorhersage.
Einzelne grosse Dateien können länger dauern; bei mehr als zwei Minuten ohne neue
Fortschrittsmeldung weist die Karte darauf hin. Eine Statusmeldung bestätigt, dass
HA seinen Status aktualisiert, und ist keine Garantie, dass der Dateiarbeiter Fortschritt macht.
100 % wird erst nach erfolgreicher ZIP-Prüfung und Abschluss angezeigt.

Für diese Anzeige die Integration über HACS aktualisieren und HA vollständig neu starten.
Dann die bestehende Exportkarte einmal durch die vollständige neue
`system_pruefexport_karte.yaml` ersetzen. HACS aktualisiert die Integrationsdateien;
die im Dashboard gespeicherte Karten-YAML wird separat gepflegt.

## Optionale Dashboardkarte

`system_pruefexport_karte.yaml` als vollständige manuelle Karte einfügen.
Die aktuelle [Karten-YAML auf GitHub](system_pruefexport_karte.yaml) ist vollständig und
benötigt **custom:button-card 6 oder neuer** sowie HA Prüfexport ab 1.0.6.
Die Karte startet den Export und holt für
den Download einen kurz gültigen, signierten Pfad aus der angemeldeten HA-Sitzung.

Die Beispielkarte formatiert Zeiten in der konfigurierten HA-Zeitzone und verwendet UTC,
wenn die Einstellung nicht verfügbar ist. Die Export-Laufzeitdaten verwenden ebenfalls die tatsächliche HA-Zeitzone.
Die Karten-YAML wird von HACS nicht automatisch ins Dashboard eingesetzt oder aktualisiert.

Die kompakte Fassung vom 11.10.2026 funktioniert mit der bereits installierten Integration
1.0.8. Dafür nur die vorhandene Prüfexportkarte im Dashboard vollständig durch die neue
YAML ersetzen und speichern; kein Integrationsupdate oder HA-Neustart erforderlich.
Der Prozentbalken verschwindet nach Abschluss. **Hinweise im Bericht** kennzeichnet ein
erstelltes ZIP mit dokumentierten Erfassungsgrenzen. Ein vorhandenes älteres Archiv bleibt
während eines Laufs oder nach einem Fehler als **Vorheriges ZIP** herunterladbar.
Ein Tipp auf die obere Statuskarte öffnet die ausführlichen Sensorattribute mit
Fehlerdetails, Laufzeit, Statuszeitstempeln und Exporter-Version.
Die beiden flachen Aktionsknöpfe behalten mindestens 44 Pixel Höhe.

## Eigener Prüfkontext

Optional `ha_pruefexport_kontext.md` im aktiven HA-Konfigurationsordner pflegen.
Dort können beispielsweise gewünschte Darstellung, bekannte Einschränkungen oder
Vorgaben für spätere Änderungen stehen. Der Inhalt wird nach dem Secret-Abgleich in
`KONTEXT.md` aufgenommen. Die Datei bleibt ausserhalb des durch HACS verwalteten Ordners.

Der öffentliche Integrationscode enthält keinen fest vorgegebenen privaten Projektstandort.
Standort, Hardware und Zeitzone werden aus den exportierten Daten abgeleitet.

## Umfang und Grenzen

Das Archiv enthält einen Prüfauftrag, Kontext, Exportbericht, Dateiinventar und ein
Manifest mit SHA256 und Bytezahl für alle Archivdateien ausser dem Manifest selbst.

Erfasst werden unter anderem:

- Textkonfiguration, YAML-Einbindungen, Helferspeicher und Quellen eigener Erweiterungen;
- aktive UI- und YAML-Dashboards sowie Frontendressourcen;
- automatisch erzeugte Übersichten mit Herkunftshinweis statt einer erfundenen statischen Kartenliste;
- aktuelle Zustände samt Zeitstempeln, Registries, Integrationseinträge und Dienste;
- bis zu 100 zusammengefasste Warnungen/Fehler aus dem HA-Fehlerspeicher, vorhandene
  lokale HA-Logdateien als begrenzte Ausschnitte und auf Datenträger gespeicherte Traces;
- Wetterprognosen und Kalenderantworten über lesende HA-Aktionen;
- ein begrenzter Recorder-Verlauf für ausdrücklich im Dashboard genannte Entitäten.

Nicht unterstützte Formate, fehlende Referenzen, Abruffehler und erreichte Limits
stehen als Lücken im Exportbericht. Unbekannte `.storage`-Formate werden inventarisiert,
aber nicht ungeprüft kopiert. Anbieterdiagnosen, Langzeitstatistiken und externe Apps
werden nicht pauschal als vollständig erfasst ausgegeben.
Unbekannte Dateiformate werden ausdrücklich zur Prüfung markiert; bekannte Medien,
Fonts und ergänzende Source-Maps bleiben bewusst ausgelassen. Medien-/Backup-/Export-
Verzeichnisse werden nur am Konfigurationswurzelverzeichnis ausgeschlossen, damit
gleichnamige funktionale Unterordner eigener Integrationen mitgesammelt werden.

Grenzen: 12 MiB je Textdatei, 80 MiB Quelldatenbudget, 100000 inventarisierte Dateien;
Logausschnitte bis 256 KiB je unterstützter Datei. Der Recorder-Abruf versucht 48 Stunden
für bis zu 100 Entitäten und ist auf 10000 Zeilen begrenzt. Vollständige Core- und
Supervisor-Logs werden nicht automatisch abgerufen.
Das Zeilenbudget wird gleichmässig auf ausgewählte Entitäten verteilt. Häufige
Messwerte können dadurch ältere Tür-/Alarmereignisse anderer Entitäten nicht verdrängen.
Je Entität werden die neuesten Änderungen bis zum Budget erfasst; gekürzte Entitäten,
Zeilenzähler und Abfragezeitfenster sind dokumentiert. Ein Abfragezeitfenster von
48 Stunden bedeutet bei Kürzungen keinen lückenlosen Verlauf jeder Entität.

Ein Exportstatus „vollständig“ beschreibt nur den dokumentierten Erfassungsumfang,
keine fehlerfreie HA-Konfiguration. „Umfang prüfen“ verweist auf Einschränkungen im Bericht.

## Speicherung und Maskierung

Die letzten drei fertigen Archive bleiben lokal unter `.ha_pruefexport/` erhalten.
Die Integration lädt nichts auf GitHub oder andere externe Dienste hoch.
Der Download verlangt eine authentifizierte HA-Administratoridentität.

Auth-Dateien, Inhalte von `secrets.yaml`, Datenbanken, Backups, private Schlüssel und
Medien werden ausgeschlossen. Bekannte Zugangsdatenfelder und lokal erkannte Secret-Werte
werden maskiert; `input_text`-Zustandsinhalte werden vorsorglich maskiert.
Nachgewiesene öffentliche ConnectLife-Buttonkennungen in den ausgelieferten
Datenwörterbüchern bleiben erhalten. Die Ausnahme gilt nur für bekannte Kennungen
im passenden Dateipfad und in einer Buttondefinition mit Schreibbeschreibung;
gleichlautende Werte, die anderswo als Zugangsdaten erkannt werden, bleiben maskiert.
Archivpfade und übernommene Manifestdaten werden ebenfalls geprüft.

Gerätenamen, interne IPs, Kalenderdaten und Log-/Trace-Inhalte können persönliche
Informationen enthalten. Das ZIP ist eine bereinigte Prüfgrundlage und kein anonymisiertes
Backup. Erzeugte ZIPs und eigene Kontextdateien gehören nicht in dieses öffentliche Repository.

## Entwicklung und Prüfung

Die Tests arbeiten mit synthetischen Dateien und HA-API-Doubles, ohne Verbindung zu einem
HA-System. Anleitung und Grenzen stehen in [TESTING.md](TESTING.md).
Die Veröffentlichung über HACS ersetzt keinen Live-Test in Home Assistant.

Änderungen stehen in [CHANGELOG.md](CHANGELOG.md). Lizenz: [MIT](LICENSE).
