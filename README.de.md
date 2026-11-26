<h1 align="center">geizhals-mcp</h1>

<p align="center"><sub>Aus derselben Reihe: <a href="https://github.com/Samxel/kleinanzeigen-mcp">kleinanzeigen-mcp</a> · <a href="https://github.com/Samxel/willhaben-mcp">willhaben-mcp</a></sub></p>

Ein MCP-Server, mit dem eine KI die Preisvergleichsdaten von
[Geizhals](https://geizhals.at) durchsuchen kann: Produkte, Bestpreise,
Preisverlauf, Bewertungen und Kategorien. Er nutzt die API der Geizhals-App
(`api.geizhals.net/gh/v9`) und gibt der KI die wichtigen Felder zurück.

<p align="center">
  <a href="https://geizhals.at/"><img alt="Products tracked" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fgeizhals-mcp%2Fcoverage%2Fcoverage.json&query=%24.products&label=products&color=green&suffix=%20tracked&cacheSeconds=3600"></a>
  <a href="https://geizhals.at/"><img alt="Prices compared" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fgeizhals-mcp%2Fcoverage%2Fcoverage.json&query=%24.prices&label=prices&color=ff7300&suffix=%20compared&cacheSeconds=3600"></a>
  <a href="https://geizhals.at/"><img alt="Merchants" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FSamxel%2Fgeizhals-mcp%2Fcoverage%2Fcoverage.json&query=%24.merchants&label=merchants&color=1e6fff&suffix=%20shops&cacheSeconds=3600"></a>
</p>

<p align="center">
  <a href="#highlights">Highlights</a> ·
  <a href="#einrichtung">Einrichtung</a> ·
  <a href="#in-claude-einbinden-und-andere-mcp-clients">In Claude einbinden</a> ·
  <a href="#selbst-starten">Starten</a> ·
  <a href="#tools">Tools</a> ·
  <a href="#hinweise">Hinweise</a> ·
  <a href="#haftungsausschluss">Haftungsausschluss</a> ·
  <a href="#lizenz">Lizenz</a>
</p>

<p align="center"><sub><a href="README.md">Read this in English</a></sub></p>

## Highlights

- **Bestpreis über alle Shops**  
  Ein Produkt finden und dazu **Bestpreis, die günstigsten Shops mit Versand und Lagerstand, die ganze Preisspanne, Sternebewertungen und die Zahl der Testberichte** bekommen, zusammengefasst über alle Geizhals-Händler statt nur eines Angebots.

- **Wissen, wann sich der Kauf lohnt**  
  Den **kompletten Preisverlauf** und die **aktuellen Preissenkungen** (Schnäppchen) abrufen, gefiltert nach Kategorie und danach, wie viele Shops sie führen, und direkt aus dem Chat einen **Geizhals-Preisalarm per E-Mail** setzen. So beantwortet ein Modell „ist das gerade günstig oder soll ich warten“.

- **Vom Suchbegriff zur Kategorie**  
  Per Freitext suchen oder den **kompletten Geizhals-Kategoriebaum** (über 2200 Kategorien, liegen dem Server bei) durchgehen, um genau das richtige Segment zu treffen, und dann eine Auswahl nebeneinander vergleichen.

- **Gebrauchtangebote einschätzen**  
  `match_geizhals` findet das Geizhals-Produkt hinter einer Gebrauchtanzeige (mit Konfidenzwert), und `get_model_price_range` zeigt, was dieses Modell neu über alle Varianten kostet. Zusammen beantworten sie „ist dieses Gebrauchtangebot ein guter Deal?“.

## Einrichtung

Drei Wege, einer reicht. Bei keinem muss etwas im Hintergrund laufen: Der
Client startet den Server, wenn er ihn braucht.

**Claude Desktop, ohne Terminal.** `geizhals-mcp.mcpb` aus dem
[neuesten Release](https://github.com/Samxel/geizhals-mcp/releases/latest)
herunterladen und doppelklicken. Claude Desktop zeigt einen
Installationsdialog und richtet die Abhängigkeiten selbst ein. Fertig, den Rest
dieses Abschnitts kannst du überspringen.

**Mit [uv](https://docs.astral.sh/uv/), ohne Klonen.** Ein Befehl startet die
aktuelle Version direkt von GitHub:

```bash
uvx --from git+https://github.com/Samxel/geizhals-mcp geizhals-mcp --stdio
```

**Aus einem Klon.** Braucht Python 3.10+.

```bash
git clone https://github.com/Samxel/geizhals-mcp
cd geizhals-mcp
pip install -r requirements.txt
python main.py --stdio
```

`uv run main.py --stdio` geht auch ohne `pip install`: `main.py` bringt die
Liste seiner Abhängigkeiten selbst mit.

## In Claude einbinden (und andere MCP-Clients)

### Claude Code

Ein Befehl, keine Konfigurationsdatei:

```bash
claude mcp add geizhals -- uvx --from git+https://github.com/Samxel/geizhals-mcp geizhals-mcp --stdio
```

Aus einem Klon zeigst du stattdessen auf `main.py`:

```bash
claude mcp add geizhals -- python /pfad/zu/geizhals-mcp/main.py --stdio
```

Mit `--scope user` steht der Server in jedem Projekt zur Verfügung, nicht nur
im aktuellen. `claude mcp list` zeigt, ob die Verbindung steht, `claude mcp
remove geizhals` entfernt ihn wieder.

### Claude Desktop

Am einfachsten ist die `.mcpb` aus der [Einrichtung](#einrichtung). Ohne sie
öffnest du **Settings > Developer > Edit Config**, trägst `geizhals` in
`claude_desktop_config.json` ein und startest Claude Desktop neu:

```json
{
  "mcpServers": {
    "geizhals": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Samxel/geizhals-mcp", "geizhals-mcp", "--stdio"]
    }
  }
}
```

Aus einem Klon nimmst du `"command": "python"` und `"args":
["C:\\pfad\\zu\\geizhals-mcp\\main.py", "--stdio"]` (der volle Pfad zu
`main.py`, unter macOS/Linux mit normalen Schrägstrichen).

Eigene Connectors (**Settings > Connectors**) verbinden sich aus der Cloud von
Anthropic und erreichen deshalb keinen Server, der nur auf deinem Rechner
läuft. Willst du die Tools auch in claude.ai und den Mobil-Apps nutzen, machst
du den HTTP-Server (siehe [Selbst starten](#selbst-starten)) über cloudflared,
ngrok oder einen Rechner mit öffentlichem Hostnamen erreichbar und trägst die
HTTPS-URL unter **Settings > Connectors > Add custom connector** ein. Dann kann
aber jeder, der die URL kennt, den Server nutzen, also stell eine
Authentifizierung davor.

Alle Tools außer `create_price_alarm` sind als nur lesend markiert, Clients,
die das beachten, fragen also nicht vor jedem Aufruf nach. In Claude Desktop
kannst du außerdem unter **Settings > Connectors > geizhals** das Dropdown
rechts bei den Tools auf **Always allow** stellen.

### Cursor, Codex, VS Code und andere Clients mit JSON-Konfiguration

Derselbe Eintrag wie bei Claude Desktop, in der MCP-Konfiguration des Clients:

```json
{
  "mcpServers": {
    "geizhals": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/Samxel/geizhals-mcp", "geizhals-mcp", "--stdio"]
    }
  }
}
```

Clients, die sich stattdessen mit einer URL verbinden, bekommen `"type":
"http"` und `"url": "http://127.0.0.1:8000/mcp"`, mit dem Server wie unten
gestartet.

## Selbst starten

Ohne `--stdio` startet der Server über Streamable HTTP und zeigt an, wo er
lauscht:

```bash
python main.py
```

```
Starting geizhals-mcp server on http://127.0.0.1:8000/mcp
```

Diese URL trägst du im Client ein, zum Beispiel mit `claude mcp add
--transport http geizhals http://127.0.0.1:8000/mcp`. Host, Port und Pfad
stehen oben in `geizhals/server.py`. Mit pip oder uv installiert, machen der
Befehl `geizhals-mcp` und `python -m geizhals` dasselbe wie `python main.py`.

## Tools

Die meisten Tools haben drei gemeinsame Parameter: `loc` ist die Länderseite,
`"at"` (Standard) oder `"de"`; `hloc` listet die Shop-Länder, die einbezogen
werden, und ist standardmäßig `[loc]`; `lang` (`"en"` oder `"de"`) bestimmt die
Sprache der Kategorienamen. Ergebnisse kommen als kompaktes JSON, Felder ohne
Wert fallen weg. Treffer haben keinen eigenen Link: Die Produktseite ist
`https://geizhals.at/a{id}.html` (`geizhals.de` bei `loc="de"`). Das steht
einmal in den Server-Anweisungen, statt in jedem Treffer wiederholt zu werden.

<details>
<summary><code>search_geizhals(query, ...)</code>: Produkte per Suchbegriff finden, mit aktuellen Preisen</summary>

Produkte per Suchbegriff finden, mit Filtern für Kategorie und Hersteller,
Sortierung und Blättern (`rows` standardmäßig 5, höchstens 50). Jeder Treffer
bringt seinen aktuellen `best_price`, `avg_price`, `offer_count`, `currency`,
den günstigsten `shop`, `rating_*`, `category_code` und ein `available`-Flag
mit, eine einfache Preis- oder Bewertungsfrage braucht also keinen weiteren
Aufruf. Treffer ohne aktuelle Angebote bekommen `alltime_price_min` /
`alltime_price_max` / `alltime_last_date` dazu, damit auch ausgelaufene
Produkte einen Preis haben, ohne einen Aufruf pro Treffer. Die Facetten nennen
die zehn größten Kategorien (mit Namen) und Hersteller, um die Suche damit
einzugrenzen.

`sort` nimmt `""` (Relevanz), `"p"` (günstigste zuerst) oder `"-p"` (teuerste
zuerst); eine Sortierung nach Neuheit oder Bewertung gibt es bei Geizhals für
die Suche nicht. Eine Preissortierung grenzt die Ergebnisse zugleich ein:
Geizhals kann Produkte ohne Preis nicht nach Preis ordnen, also fallen nicht
verfügbare Produkte aus `results` und aus `total` heraus.

</details>

<details>
<summary><code>get_product(product_id, n_offers=5)</code>: ein Produkt vollständig, mit den günstigsten Shops</summary>

Alle Details zu einem Produkt: aktueller Bestpreis und Zahl der Angebote, Name,
Kategorie, Bewertung, Bilder, GTIN, Angebotslink, Preisspanne über die ganze
Zeit und Zahl der Testberichte. `offers` listet die günstigsten Shops mit
Preis, günstigstem Versand, Gesamtpreis, dem Lagertext des Shops und seiner
Bewertung. Bei einem Produkt ohne aktuelle Angebote werden `last_known_price` /
`last_known_date` ergänzt. Bei Kleidung stehen die `sizes` dabei.

</details>

<details>
<summary><code>get_price_history(product_id, days=31)</code>: sehen, wie sich der Preis entwickelt hat</summary>

Gibt eine Zusammenfassung des gewählten Zeitraums
(`window_min/max/avg/change_percent`) und, getrennt davon, der ganzen
Produktgeschichte (`alltime_min/max`) zurück, dazu eine Reihe aus
`[iso_date, price]`, die nur die Tage mit Preisänderung enthält.
`granularity="day"` oder `"week"` liefern stattdessen einen Punkt pro Tag oder
pro Woche, und `include_series=False` lässt die Reihe weg.

</details>

<details>
<summary><code>get_product_ratings(product_id)</code>: die Nutzerbewertungen eines Produkts</summary>

Durchschnittsbewertung, Gesamtzahl, Anzahl pro Stern und der Link zu den
Bewertungen.

</details>

<details>
<summary><code>browse_category(category, ...)</code>: die Produkte einer Kategorie auflisten</summary>

Listet die Produkte einer Kategorie anhand ihres Codes, mit Preisgrenzen,
Blättern (`rows` standardmäßig 10, höchstens 50) und Sortierung: `"t"`
(Relevanz), `"p"` / `"-p"` (Preis auf- oder absteigend), `"n"` (neueste
Einträge) oder `"bew"` (beste Bewertung). Die Treffer haben dieselben Felder
wie bei `search_geizhals`. Die Kategorie wird einmal oben im Ergebnis genannt
statt in jedem Treffer, und die mitgelieferte `price_range` ist die echte der
Kategorie (die der Suchfacette ist es nicht).

</details>

<details>
<summary><code>compare_products(product_ids)</code>: Produkte nebeneinander vergleichen, mit Datenblatt</summary>

Bis zu zehn Produkte nebeneinander vergleichen, inklusive Datenblatt.
Eigenschaften, die auf ein Produkt nicht zutreffen, fallen weg, statt leer
dazustehen, und das Datenblatt ist auf Deutsch, weil Geizhals es nur so hat.
Ausgelaufene Produkte bringen ihren letzten bekannten Preis mit.

</details>

<details>
<summary><code>get_deals(sort="percent", ...)</code>: aktuelle Preissenkungen auflisten</summary>

Aktuelle Preissenkungen: Produkte, deren Bestpreis gerade gefallen ist, mit
Prozent und Betrag der Senkung. Sortiert nach größter Senkung in `percent`,
`price`, `latest`, `popularity` oder `top`-Deals, gefiltert mit:
- `min_discount_percent` und `max_price`
- `min_offer_count`: Eine Senkung bei nur einem oder zwei Shops ist oft ein
  Preisfehler oder ein Abverkauf eines einzelnen Shops; ab 3 fällt das meiste
  davon heraus
- `category`: ein Kategoriecode (`"gra16_512"`) oder ein Name irgendwo im
  Kategoriepfad, auf Englisch oder Deutsch (`"Hardware"`, `"Grafikkarten"`)

Filter und Sortierung laufen über alle aktuellen Senkungen (rund zweitausend),
und `limit` (standardmäßig 10, höchstens 50) bestimmt, wie viele Treffer
zurückkommen. Die Flags `alltime_best` und `top_deal` stehen nur bei den Deals,
auf die sie zutreffen. `next_offset` holt die nächste Seite; der Feed wird zwei
Minuten zwischengespeichert, weitere Seiten kommen also sofort.

</details>

<details>
<summary><code>get_model_price_range(model, ...)</code>: was ein Modell über alle Varianten kostet</summary>

Was ein Modell gerade über alle seine Varianten kostet (`min`, `median`, `max`
und die fünf günstigsten), etwa jede RTX 5070 statt nur die Version eines
Herstellers. Geschwistermodelle (`4070 Ti`, `4070 Super`) bleiben draußen. Das
Ergebnis kommt immer aus einer Kategorie, weil eine einfache Suche nach einer
Grafikkarte auch billigere Wasserkühler und Gehäuse und teurere Komplett-PCs
findet. Gibst du keine Kategorie an, wird sie erkannt und als `category_code`
zurückgegeben. Bis zu 300 Suchtreffer fließen ein.

</details>

<details>
<summary><code>match_geizhals(title, ...)</code>: herausfinden, um welches Produkt es in einer Gebrauchtanzeige geht</summary>

Nimmt den Titel einer Gebrauchtanzeige („Gigabyte RTX 5070 Windforce OC 12GB
NEU OVP mit Rechnung“) und gibt die Geizhals-Produkte zurück, die gemeint sein
könnten, jeweils mit einer `confidence` zwischen 0 und 1 und dem aktuellen
Preis. Marktplatz-Einträge ohne Kategorie (meist Komplett-PCs, die die
verbaute Karte nennen) bekommen einen niedrigen Wert, damit sie nicht als die
Karte selbst durchgehen. Liegen die besten Kandidaten zu nah beieinander oder
überzeugt keiner, sagt eine `note` das, statt einen Münzwurf wie eine Antwort
aussehen zu lassen.

</details>

<details>
<summary><code>list_categories(query, lang="en")</code>: Kategoriecodes nach Namen nachschlagen</summary>

Durchsucht den Geizhals-Kategoriebaum nach den Codes, die `browse_category`
braucht. Findet englische und deutsche Namen („graphics cards“ und
„grafikkarten“ gehen beide) und gibt jeden Code mit seinem Pfad in `lang`
zurück. Der ganze Baum liegt dem Server in `geizhals/data/categories.json` bei.

</details>

<details>
<summary><code>create_price_alarm(product_id, email, price_limit, expiry_days=61)</code>: eine E-Mail bekommen, wenn ein Produkt billiger wird</summary>

Setzt einen Geizhals-Preisalarm, ganz ohne Konto: Geizhals schickt eine
E-Mail, sobald der Bestpreis auf `price_limit` fällt. Der Alarm läuft
`expiry_days` lang: 7, 14, 21, 28, 61 (Standard) oder 183 Tage, andere Werte
nimmt Geizhals nicht an. Bei Kleidung beschränkt `sizes` ihn auf die Größen,
die `get_product` listet. Ein erneuter Aufruf für dieselbe Adresse und
dasselbe Produkt aktualisiert den Alarm. Der erste Alarm einer Adresse läuft
erst, nachdem der Bestätigungslink von Geizhals angeklickt wurde, abbestellt
wird er über den Link in den Mails von Geizhals. Die Anweisungen sagen der KI,
einen Alarm anzubieten, wenn ein Produkt deutlich über seinem Tiefstpreis
liegt oder ein Sale bevorsteht, mit einer Laufzeit, die den Sale überdauert,
und nach der Adresse zu fragen, statt sie zu raten.

</details>

## Hinweise

- `geizhals/server.py` ist der Server mit seinen Tools; `main.py` startet ihn
  nur aus einem Klon heraus. Worauf die Tools aufbauen, liegt daneben im Paket
  `geizhals`: `api.py` signiert und verschickt die Anfragen, `summaries.py`
  macht aus den Rohdaten Ergebnisse, `matching.py` gleicht Anzeigentitel und
  Modelle ab, und `categories.py` liest den Kategoriebaum.
- `geizhals/data/categories.json` ist ein Abzug des Geizhals-Kategoriebaums
  (title, title_de, id, children). `list_categories` gleicht Anfragen mit den
  englischen und den deutschen Namen ab.
- Was alle Tools gemeinsam haben (mit welchem Tool man anfängt, was
  `loc`/`hloc`/`lang` bedeuten, `id` gegenüber `variant_id`, wie ein Link
  entsteht), wird einmal als Server-Anweisung geschickt, statt in jeder
  Tool-Beschreibung zu stehen. Die Tool-Schemas lassen die Titel und
  `null`-Zweige weg, die pydantic sonst einfügt, und Ergebnisse gehen als
  kompaktes JSON raus. All das hält klein, was das Modell in jedem Schritt
  lesen muss.
- Angeboten werden nur die österreichische und die deutsche Seite. Bei den
  anderen (`eu`, `uk`, `pl`) sind sich die Endpunkte bei der Währung uneinig,
  `sk` lehnt jeden Aufruf ab, und die Seiten at/de ignorieren Shops aus anderen
  Ländern ohnehin.
- Releases: `version` in `pyproject.toml` und `manifest.json` erhöhen, dann
  einen Tag wie `v1.1` pushen (eine Patch-Stelle `.0` darf fehlen, `v1.1` veröffentlicht also 1.1.0). Der Release-Workflow lässt die Tests laufen,
  baut Wheel, sdist und das `.mcpb`-Bundle und hängt sie an ein GitHub-Release.
- Die Badges oben lesen `coverage.json` aus dem Branch `coverage`.
  `scripts/update_coverage.py` aktualisiert die Datei von der
  Geizhals-Startseite, und eine tägliche GitHub Action committet Änderungen in
  diesen Branch, damit die Historie von `main` sauber bleibt.
- Die API ist in [`search_api.md`](search_api.md) dokumentiert (auf Englisch).
- Das hier nutzt die interne App-API von Geizhals, keine offizielle.
  Geh pfleglich damit um.

## Haftungsausschluss

Das ist ein unabhängiges, inoffizielles Projekt und steht in keiner Verbindung
zu Geizhals, wird von Geizhals weder unterstützt noch empfohlen. „Geizhals“
und alle zugehörigen Marken gehören ihren jeweiligen Inhabern.

Es wird nur zu Lern- und Forschungszwecken veröffentlicht. Es spricht mit der
internen API von Geizhals, die nicht für die Öffentlichkeit gedacht ist und
sich jederzeit ändern oder wegfallen kann. Du bist dafür verantwortlich, wie
du es nutzt: Halte dich an die Nutzungsbedingungen von Geizhals, die
Robots-Regeln und geltendes Recht, und überlaste die Server nicht.

## Lizenz

[`MIT LICENSE`](LICENSE). Bereitgestellt „wie besehen“, ohne Gewährleistung.

<p align="center"><sub><a href="README.md">Read this in English</a></sub></p>
