from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / '.env')
DB_PATH = BASE_DIR / os.getenv('HSLU_DB_PATH', 'data/duckdb/hslu_ris.duckdb')
RAW_DIR = BASE_DIR / os.getenv('HSLU_RAW_DIR', 'data/raw')
EXPORT_DIR = BASE_DIR / 'exports'
HOST = os.getenv('HSLU_HOST', '127.0.0.1')
PORT = int(os.getenv('HSLU_PORT', '8050'))
DEBUG = os.getenv('HSLU_DEBUG', 'true').lower() == 'true'
COLORS = {
    'navy': '#17365D', 'blue': '#2F75B5', 'teal': '#00A6A6', 'green': '#70AD47',
    'orange': '#ED7D31', 'red': '#C00000', 'background': '#F4F7FA', 'surface': '#FFFFFF',
    'text': '#1F2937', 'light': '#F4F7FA', 'gray': '#6B7280',
}
STATUS_COLORS = {
    'VALID': COLORS['green'],
    'CONTENT_CHANGED': COLORS['teal'],
    'METADATA_CHANGED': COLORS['blue'],
    'CRAWLER_REDIRECT': COLORS['orange'],
    'INVALID_LINK': COLORS['red'],
    'INVALID_PDF': COLORS['navy'],
    'MUNICIPALITY_MISMATCH': COLORS['gray'],
    'REVIEW_REQUIRED': COLORS['gray'],
}
NAV_ITEMS = [
    {'label': 'Suche', 'href': '/suche', 'icon': '⌕'},
    {'label': 'Dashboard', 'href': '/', 'icon': '▤'},
    {'label': 'Gemeinderanking', 'href': '/ranking', 'icon': '▲'},
    {'label': 'Gemeindeprofil', 'href': '/gemeinde', 'icon': '◉'},
    {'label': 'Reglementanalyse', 'href': '/regulierung', 'icon': '⚖'},
    {'label': 'Baugesuche', 'href': '/Baugesuche', 'icon': '▣'},
    {'label': 'Investment Case', 'href': '/investment-case', 'icon': '◈'},
    {'label': 'Datenqualität', 'href': '/datenqualitaet', 'icon': '✓'},
    {'label': 'Administration', 'href': '/administration', 'icon': '⚙'},
]

# Kategorial-Palette für Charts: blue/teal zuerst (mehr Blautöne), navy bewusst ausgeschlossen
# (zu dunkel/kontrastarm für Kategorie-Identität) und orange/grün nicht benachbart (zu
# ähnlich für Deuteranopie) - per dataviz-Skill-Validator geprüft (node validate_palette.js).
PLOTLY_COLORWAY = [COLORS['blue'], COLORS['teal'], COLORS['orange'], COLORS['red'], COLORS['green']]
