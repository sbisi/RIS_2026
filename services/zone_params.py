"""Die 28 Zonenparameter-Typen aus data_hslu260312.csv, wie in etl/build_zone_parameters.py
extrahiert (Anzeigename -> Spalten-Slug-Präfix). Geteilte Konstante zwischen
pages/parzellen.py (Parameter-Tabelle) und services/data.py (Abdeckungs-Übersicht) - bewusst
NICHT in pages/ definiert, siehe services/geo.py für den Hintergrund dieser Konvention."""

ZONE_PARAM_TYPES = [
    ('Abstand Strasse', 'abstand_strasse'), ('Ausnützungsziffer', 'ausnuetzungsziffer'),
    ('Bachabstand', 'bachabstand'), ('Baumassenziffer', 'baumassenziffer'),
    ('Bonus Ausnützung', 'bonus_ausnuetzung'), ('Fassadenhöhe', 'fassadenhoehe'),
    ('Fassadenhöhe (giebelseitig)', 'fassadenhoehe_giebelseitig'),
    ('Fassadenhöhe (traufseitig)', 'fassadenhoehe_traufseitig'), ('Firsthöhe', 'firsthoehe'),
    ('Freiflächenziffer', 'freiflaechenziffer'), ('Fussgängerwege-Abstand', 'fussgaengerwege_abstand'),
    ('Gebäudeabstand', 'gebaeudeabstand'), ('Gebäudebreite', 'gebaeudebreite'),
    ('Gebäudehöhe', 'gebaeudehoehe'), ('Gebäudelänge', 'gebaeudelaenge'),
    ('Gesamtausnützung', 'gesamtausnuetzung'), ('Geschossflächenziffer', 'geschossflaechenziffer'),
    ('Geschosse', 'geschosse'), ('Gestaltungsplanbonus', 'gestaltungsplanbonus'),
    ('grosser Grenzabstand', 'grosser_grenzabstand'), ('kleiner Grenzabstand', 'kleiner_grenzabstand'),
    ('Grenzabstand', 'grenzabstand'), ('Mehrhöhenzuschlag', 'mehrhoehenzuschlag'),
    ('Mehrlängenzuschlag', 'mehrlaengenzuschlag'), ('Überbauungsziffer', 'ueberbauungsziffer'),
    ('Untergeschosse', 'untergeschosse'), ('Waldabstand', 'waldabstand'), ('Wohnanteil', 'wohnanteil'),
]
ZONE_PARAM_VARIANTS = [('standard', 'Standard'), ('bonus', 'Bonus'), ('arealueberbauung', 'Arealüberbauung')]
