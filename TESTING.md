# Lokale Prüfung

Benötigt Python 3.12 oder neuer und Node.js für die Kartenprüfung.

```sh
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
python tests/validate.py
```

Die Tests verwenden synthetische HA-Daten und API-Doubles. Sie prüfen ZIP-Integrität,
Manifest-Prüfsummen, Inventarverweise, Maskierung von Quellwerten und Dateinamen,
Storage-Umschläge, YAML-Tags und Skalarwerte, Limits und dokumentierte Lücken,
Exportdienstparameter, Registry-Erfassung, Recorder-/Wetter-/Kalenderabrufe,
Administratorprüfung, Downloadpfade, Fehlerdiagnosen und die tatsächliche Kartenlogik.

Die Prüfung führt keine Geräteaktionen aus und benötigt keine HA-Zugangsdaten.
Die Test-Zugangsdaten in den Fixtures sind absichtlich erfundene Werte.

Version 1.0.8: 72 lokale Tests und die Syntax-/Kartenprüfung bestehen.
Neue Regressionstests prüfen den Unterschied zwischen automatisch erzeugter
Übersicht und echtem Ladefehler, begrenzte/maskierte Live-Fehlereinträge ohne
Geräteaktionen, fairen Verlauf mit einem häufigen Zähler und einem älteren Türereignis,
leere gegenüber abgebrochenen Verlaufabfragen, unbekannte Formate, funktionale
Unterordner, Lovelace-Ressourcenspeicher und die enge Ausnahme für öffentliche
ConnectLife-Buttonkennungen einschliesslich gleichlautender echter Zugangsdaten.
Der parameterlose Kartenaufruf und frühere Modusparameter werden mit beiden
Schema-Engines geprüft. Echte ZIPs aus dem Standardaufruf und einem früheren
`methode`-Aufruf enthalten denselben kombinierten Prüfauftrag; Archivmetadaten und
Managerstatus melden jeweils `gesamt`.
Zusätzlich geprüft: Bearbeitungszähler und Phasen vor Archivfreigabe, gedrosselte
Fortschrittsmeldungen, langsame HA-Abrufe mit Statusmeldungen ohne erfundenen Fortschritt,
Entity-Benachrichtigungen ausschliesslich auf dem Eventloop, doppelte Startaufrufe,
Zurücksetzen beim nächsten Lauf, alte Meldungen und Abbruch ohne 100-Prozent-Erfolg.
Ein absichtlich beschädigter komprimierter ZIP-Inhalt wird bei der CRC-Prüfung abgewiesen;
temporäre Dateien werden entfernt und kein ZIP veröffentlicht. Die tatsächlichen Karten-
Templates werden mit laufendem Export, Prozentgrenzen, Dateizählern, Laufzeit,
Statusuhrzeit, Escaping, länger ausbleibendem Fortschritt und vorherigem ZIP ausgeführt.
Diese Aussage bezieht sich auf die mitgelieferten API-Doubles, nicht auf einen vollständigen
HA-Core-Lauf. HA-Authentifizierungsmiddleware und WebSocket-Signierung werden durch
Doubles ersetzt. Die erste tatsächliche HACS-Installation muss separat in HA geprüft werden.
