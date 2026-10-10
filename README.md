# HA Prüfexport

Lokale Home-Assistant-Integration für ein dokumentiertes Prüfarchiv aus Konfiguration,
Dashboards und Laufzeitdaten. Das ZIP wird auf dem HA-System erstellt und kann über
eine authentifizierte Administrator-Sitzung heruntergeladen werden.

Version **1.0.5** · Home Assistant **2026.10.0 oder neuer** · keine zusätzlichen
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
data:
  pruefmodus: methode
```

- `methode`: Prüfauftrag nur für Exportmethode, Umfang und Maskierung; Standardwert.
- `gesamt`: Prüfauftrag für eine systematische Konfigurations- und Dashboardprüfung.

Die Aktion startet den Export im Hintergrund. Der Sensor zeigt Fortschritt, letzten
Erfolg, Umfang und bereinigte Fehlerdetails. Ein vorheriges fertiges ZIP bleibt auch
nach einem fehlgeschlagenen neuen Versuch erhalten.

## Optionale Dashboardkarte

`system_pruefexport_karte.yaml` als vollständige manuelle Karte einfügen.
Benötigt **custom:button-card 6 oder neuer**. Die Karte startet den Export und holt für
den Download einen kurz gültigen, signierten Pfad aus der angemeldeten HA-Sitzung.

Die Beispielkarte formatiert Zeiten in der konfigurierten HA-Zeitzone und verwendet UTC,
wenn die Einstellung nicht verfügbar ist. Die Export-Laufzeitdaten verwenden ebenfalls die tatsächliche HA-Zeitzone.
Die Karten-YAML wird von HACS nicht automatisch ins Dashboard eingesetzt oder aktualisiert.

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
- aktuelle Zustände samt Zeitstempeln, Registries, Integrationseinträge und Dienste;
- vorhandene lokale HA-Logdateien als begrenzte Ausschnitte und gespeicherte Traces;
- Wetterprognosen und Kalenderantworten über lesende HA-Aktionen;
- ein begrenzter Recorder-Verlauf für ausdrücklich im Dashboard genannte Entitäten.

Nicht unterstützte Formate, fehlende Referenzen, Abruffehler und erreichte Limits
stehen als Lücken im Exportbericht. Unbekannte `.storage`-Formate werden inventarisiert,
aber nicht ungeprüft kopiert. Anbieterdiagnosen, Langzeitstatistiken und externe Apps
werden nicht pauschal als vollständig erfasst ausgegeben.

Grenzen: 12 MiB je Textdatei, 80 MiB Quelldatenbudget, 100000 inventarisierte Dateien;
Logausschnitte bis 256 KiB je unterstützter Datei. Der Recorder-Abruf versucht 48 Stunden
für bis zu 100 Entitäten und ist auf 10000 Zeilen begrenzt. Vollständige Core- und
Supervisor-Logs werden nicht automatisch abgerufen.

Ein Exportstatus „vollständig“ beschreibt nur den dokumentierten Erfassungsumfang,
keine fehlerfreie HA-Konfiguration. „Umfang prüfen“ verweist auf Einschränkungen im Bericht.

## Speicherung und Maskierung

Die letzten drei fertigen Archive bleiben lokal unter `.ha_pruefexport/` erhalten.
Die Integration lädt nichts auf GitHub oder andere externe Dienste hoch.
Der Download verlangt eine authentifizierte HA-Administratoridentität.

Auth-Dateien, Inhalte von `secrets.yaml`, Datenbanken, Backups, private Schlüssel und
Medien werden ausgeschlossen. Bekannte Zugangsdatenfelder und lokal erkannte Secret-Werte
werden maskiert; `input_text`-Zustandsinhalte werden vorsorglich maskiert.
Archivpfade und übernommene Manifestdaten werden ebenfalls geprüft.

Gerätenamen, interne IPs, Kalenderdaten und Log-/Trace-Inhalte können persönliche
Informationen enthalten. Das ZIP ist eine bereinigte Prüfgrundlage und kein anonymisiertes
Backup. Erzeugte ZIPs und eigene Kontextdateien gehören nicht in dieses öffentliche Repository.

## Entwicklung und Prüfung

Die Tests arbeiten mit synthetischen Dateien und HA-API-Doubles, ohne Verbindung zu einem
HA-System. Anleitung und Grenzen stehen in [TESTING.md](TESTING.md).
Die Veröffentlichung über HACS ersetzt keinen Live-Test in Home Assistant.

Änderungen stehen in [CHANGELOG.md](CHANGELOG.md). Lizenz: [MIT](LICENSE).
