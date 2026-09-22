// Meldet einen Fokus auf das Suchfeld (#search-input) an den Dash-Store 'search-focus-store',
// damit "Letzte Suchen" nur bei einem echten Klick ins Feld erscheint - nicht schon beim Laden
// der Seite. dcc.Input hat kein eigenes Fokus-Ereignis; 'focus' bubbelt nicht, daher Listener
// im Capture-Modus auf document (funktioniert unabhängig davon, wann/wie oft Dash das Eingabe-
// element bei Seitenwechseln neu erzeugt, ohne dass der Listener neu angehängt werden müsste).
document.addEventListener('focus', function (event) {
  if (event.target && event.target.id === 'search-input' && window.dash_clientside && window.dash_clientside.set_props) {
    window.dash_clientside.set_props('search-focus-store', {data: Date.now()});
  }
}, true);
