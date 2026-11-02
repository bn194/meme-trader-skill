# Der Meme Trader Skill

13 Claude skills for meme coin trading: scan the coins in play, catch new launches the second they go live, rug-check every one, time every entry and exit, replay every outcome after fees before you risk a dollar, and keep an honest journal of the real trades.

13 Claude-Skills für Meme Coins (Solana zuerst, also das, was du in Phantom,
Jupiter oder Fomo handelst):
- **Finden:** Der Scanner zeigt die Coins, die gerade laufen, sortiert danach, ob die Regel bei ihnen früher funktioniert hat. Der Radar sieht jeden neuen pump.fun-Coin in der ersten Sekunde und sagt nach 30 Sekunden KAUFEN oder NICHT KAUFEN, zuerst im Papier-Test.
- **Prüfen:** Der Analyst sucht vor jedem Kauf nach Rug-Fallen, mit RugCheck und GoPlus.
- **Planen:** Der Entry-Timer sagt, wann der Ausbruch wirklich da ist. Der Exit-Planer setzt Stop, Ziel und Zeitstopp vorher und rechnet die Gebühren deiner App ein.
- **Testen:** Die Time Machine spielt die nächste Stunde 10.000 Mal durch, testet die Regel auf vielen Coins und rechnet aus, wie wahrscheinlich dein Konto sich halbiert.
- **Auswerten:** Das Journal zeigt, ob es bei dir mit echtem Geld nach Gebühren funktioniert.

Kostenlos, MIT, keine Anmeldung, kein API-Key. Die Tools sind reines Python
und lesen freie öffentliche Daten (Liste unten).

Und: **Kein Trade ohne dein Ja.** Nichts in diesem Paket verbindet sich mit
einer Wallet, kein Tool fragt nach einem Private Key oder einer Seed Phrase.
Gekauft und verkauft wird von dir, in deiner App, auf dein Zeichen.

> Aufgebaut wie der [Day Trader skill](https://github.com/Jakeschincariol/day-trader-skill)
> von Jake Schincariol (MIT): gleiche Rollen, gleiche Sicherheitsregeln,
> gleicher Ablauf. Hier ist alles auf Meme Coins umgebaut: andere Daten,
> andere Risiken, 24/7-Markt, Gebühren und Rug-Pulls statt Börsenzeiten und
> Quartalszahlen. Dazu kommen Radar, Journal und Time Machine 2.0.

## Ehrlich vorweg

Schneller Gewinn bei wenig Risiko ist bei Meme Coins nicht drin:
- Meist schafft es nur etwa 1 % der neuen pump.fun-Coins überhaupt aus der Bonding Curve heraus.
- Die ersten Käufer sind Bots.
- Gebühren kosten bei 100 € Budget pro Runde etwa 1,8 bis 7,4 %, je nach App.

Die Time Machine hat die Ausbruchs-Regel dieses Pakets am Abend des 1.
November 2026 auf 11 aktiven Coins getestet: 52 Trades, im Schnitt **−0,6R
pro Trade nach Gebühren**. Mit deinen Einstellungen fällt das Konto in 96 von
100 Fällen innerhalb von 50 Trades auf die Hälfte. Genau deshalb blockt der
Risk-Manager solche Trades, und genau deshalb beginnt echtes Geld mit einer
Testphase.

Was das Paket kann:
- Risiko klein und vorher bekannt machen.
- Fallen aussortieren.
- Ehrlich zählen.

Was es nicht kann: aus einem Glücksspiel eine sichere Sache machen. Setz nur
Geld ein, dessen Totalverlust du verkraften kannst.

## Installieren

In Claude einfügen:

```
https://github.com/bn194/meme-trader-skill

install skill
```

Oder als Plugin in Claude Code:

```
/plugin marketplace add bn194/meme-trader-skill
/plugin install meme-trader-skill@meme-trader-skill
```

Als Plugin heißen die Skills `/meme-trader-skill:meme-scanner` usw. Ohne
Präfix kopierst du die Ordner direkt:

```bash
git clone https://github.com/bn194/meme-trader-skill.git
cp -r meme-trader-skill/meme-* ~/.claude/skills/
```

Die Tools brauchen Python 3.8 oder neuer, nichts zu installieren. Als Erstes
`meme-budget/config.example.json` nach `meme/config.json` kopieren; Claude
fragt dich nach Budget und Limits.

### Nur Handy, kein Rechner

Das geht. Du sprichst in der Claude-App mit Claude Code. Claude führt die
Tools in einer Cloud-Sitzung aus, mit echten Live-Daten, und du tippst den
Trade selbst in deiner App.

Zwei Dinge dazu:
1. **Deine Daten speichern:** Eine Cloud-Sitzung vergisst ihre Dateien. Lege
   deshalb ein **privates** GitHub-Repo (z. B. `meme-trader-data`) für den
   Ordner `meme/` an: Einstellungen, Journal, Broker-Log. Claude committet es
   nach jeder Sitzung. Nie in ein öffentliches Repo.
2. **Alarme:** Sie klingeln nur, solange eine Sitzung läuft. Für dauerhafte
   Stops brauchst du eine App mit echten Stop-Orders oder später einen
   eigenen Rechner.

## Die dreizehn

| Befehl | Rolle | was er macht |
| --- | --- | --- |
| `/meme-scanner` | Coin Scanner | Findet die Coins, die gerade gehandelt werden, filtert dünne, junge und gewaschene raus, meldet Setups und 1-Minuten-Ausbrüche, sortiert nach Edge. |
| `/meme-radar` | Launch Radar | Sieht jeden neuen pump.fun-Coin in der ersten Sekunde, sortiert Fallen sofort aus, prüft nach 10 s den Dev und die Holder, sagt nach 30 s BUY oder SKIP, verfolgt jedes BUY als 5-€-Papier-Trade mit realistischer Verzögerung und Gebühren, meldet Graduierungen und gebündelte Insider-Launches. |
| `/meme-analyst` | Token Analyst (Rug-Check) | Mint und Freeze, LP gelockt oder verbrannt, Top-Holder, Dev-Bag, Insider, Bundles über viele gleich große Wallets, gelockter Supply, Holder-Verlauf; GoPlus auch für Base und BSC: PASS, CAUTION oder AVOID. |
| `/meme-news` | News Monitor | Krypto-Schlagzeilen, öffentliche Telegram-Kanäle, bezahlte Boosts, Community Takeovers, Rug-Warnung bei abfließender Liquidität. |
| `/meme-entry` | Entry Timer | Beobachtet einen Coin Kerze für Kerze und sagt dir den Moment zum Einstieg. |
| `/meme-exit` | Exit Planner | Stop, Ziel, Zeitstopp, optional Teilverkauf und Trailing Stop, vor dem Kauf, mit den Gebühren deiner App. |
| `/meme-timemachine` | Time Machine | 10.000 Durchläufe der nächsten Stunde, echte Historie, 180 Varianten mit Gegenprobe auf ungesehenen Tagen, Test über viele Coins, Pleite-Risiko. |
| `/meme-risk` | Risk Manager | Prüft jeden Trade gegen deine Limits, inklusive Edge nach Gebühren und Testphase, und stoppt alles darüber. |
| `/meme-budget` | Budget Manager | Größe nach Budget und maximalem Verlust inklusive Gebühren, in Euro, mit Kostenvergleich Jupiter, Phantom und Fomo. |
| `/meme-broker` | Order Executor | Ein klares Ticket für deine App oder ein Paper-Fill, nie ohne dein Ja, nie mit deiner Wallet. |
| `/meme-alerts` | Price Alerts | Klingelt bei Stop, Ziel, Zeitstopp und beim Rug-Alarm. |
| `/meme-whales` | Whale Tracker | Dev-Wallet, große Holder und Top-Trader-Listen auf der Chain, mit Cluster-Alarm, wenn mehrere denselben Coin kaufen. |
| `/meme-journal` | Trade Journal | Deine echten Trades nach Gebühren: Trefferquote, Erwartungswert, Profit-Faktor, und das Urteil über die Testphase. |

## Deine Einstellungen (Standard: 100 €)

Die Tools rechnen in Dollar; 1 € ist etwa 1,11 $, das Budget-Tool zeigt Euro
dazu.

| Einstellung | Wert |
| --- | --- |
| Budget | 111 $ ≈ 100 € |
| Max. Verlust pro Trade (am Stop, inkl. Gebühren) | 3,30 $ ≈ 3 € |
| Max. Verlust pro Tag | 11 $ ≈ 10 € |
| Größte Order / Position | 33 $ ≈ 30 € (30 % vom Budget) |
| Testphase | die ersten 20 echten Trades max. 22 $ ≈ 20 €, bis das Journal "bestanden" sagt |
| Trades pro Tag / offene Positionen | 4 / 2 |
| Pause | 2 Stunden nach 2 Verlusten in Folge |
| Coin-Filter | Liquidität ≥ 50.000 $, Pool ≥ 6 h alt, Top-10 ≤ 30 %, Dev ≤ 5 %, Insider ≤ 15 %, LP ≥ 90 % gesperrt |
| Edge-Prüfung | an: Setups, die in der Time Machine nach Gebühren verlieren, werden blockiert |
| App | Phantom (0,85 %); Profile für Jupiter (≈ 0,1 %) und Fomo (0,5 %, mind. 0,95 $) |
| Frische Coins (Radar) | 5 € pro Signal, erst als Papier-Test: 50 Signale, Kauf 45 s nach dem Signal, Stop −25 %, Ziel +50 %, raus nach 10 Minuten, pump.fun-Gebühr 1,25 % pro Seite |

Fomos Mindestgebühr macht kleine Trades teuer. Derselbe 33-$-Trade kostet an
einem Beispiel bei Jupiter 0,60 $, bei Phantom 1,08 $ und bei Fomo 2,43 $
(Hin- und Rückweg).

`"paper": true` ist im Muster eingestellt. Für echtes Geld stellst du es in
deiner eigenen `meme/config.json` auf `false`; dann gilt die Testphase.

## So läuft ein Trade

Alles landet in `meme/`, und jeder Skill liest, was der vorige geschrieben hat:

```
scanner / radar -> analyst -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (ein Trade)
alerts: Stop, Ziel, Zeitstopp, Rug-Alarm                                                   (solange er läuft)
journal: nach jedem geschlossenen Trade        whales / news / analyst: nach Zeitplan
```

Ein Beispiel mit echten Daten: GATO (GTA6CAT), Sonntag, 1. November 2026,
abends, Uhrzeiten in Europe/Berlin, mit den 100-€-Einstellungen.

1. **`/meme-scanner`** um 21:55:
   - 104 Coins im Umlauf, 42 noch auf der Bonding Curve.
   - 19 liquide genug, einer als gewaschen aussortiert, 4 mit Setup.
   - Um 21:58 meldet der 1-Minuten-Scan GATO: Ausbruch aus der Range 21:42 bis 21:57 (0.0074560 bis 0.0077195) bei 0.0077889, 2,7-faches Volumen.
   - Mit `--edge` steht dahinter: −0,89R nach Kosten über 8 frühere Ausbrüche, LOST MONEY.
2. **`/meme-analyst`**:
   - Mint und Freeze revoked, LP zu 100 % verbrannt, 278.500 $ Liquidität.
   - 13.645 Holder, Top 10 bei 15,5 %, Dev bei 3,32 %. GoPlus sieht es genauso: PASS.
   - Am selben Abend bekamen vier andere geboostete Coins AVOID, darunter Dacity (Insider mit 23,8 %) und PAWCAT (1.928-mal so viel Volumen wie Liquidität: Bots).
3. **`/meme-news`**: keine Schlagzeile zu GATO, nur ein bezahlter Boost. Der Markt an dem Wochenende: der 6,3-Milliarden-Hack bei Binance.
4. **`/meme-entry`**: TRIGGERED um 21:58, Schlusskurs 0.0077889.
5. **`/meme-exit`**:
   - Stop am Range-Tief 0.0074560 (4,28 % Risiko), Ziel 3R bei 0.0087878, raus spätestens 22:58.
   - Mit Phantom kostet die Runde 3,3 %: nach Kosten −7,58 % am Stop, +9,52 % am Ziel, Chance:Risiko 1,26.
   - Ein Stop in der Range-Mitte wird abgelehnt: Er läge näher als die Gebühren.
6. **`/meme-timemachine`**:
   - 10.000 Durchläufe: Ziel zuerst 12,1 %, Stop zuerst 44,1 %.
   - Vor Kosten +0,22R, nach Kosten −0,55R. Die echte Historie: 32 Trades, −0,42R nach Kosten.
   - `compare`: Auch die beste von 180 Varianten verlor auf den Tagen, die sie nicht kannte.
   - `multi` auf 11 Coins: −0,60R pro Trade. `ruin`: in 96 % der Fälle halbiert sich das Konto innerhalb von 50 Trades.
7. **`/meme-budget`**:
   - 33 $ (≈ 29,64 €, 0,3503 SOL), am Stop −2,24 €, am Ziel +2,83 €.
   - Bei Jupiter wäre derselbe Trade 0,48 $ billiger gewesen.
8. **`/meme-risk`**: **BLOCK.** Alles andere war grün, aber die Edge-Prüfung sagt: Dieses Setup hat auf GATO nach Gebühren Geld verloren.
9. **`/meme-broker`** zeigt das Ticket deshalb nicht zur Bestätigung. Mit `"require_edge": false` wäre es durchgegangen: "ok" und "ja, aber nur 100" zählen nicht als Ja, "ja" schon.
10. **`/meme-alerts`** hätte Stop, Ziel, Zeitstopp und Rug-Alarm überwacht. Was GATO danach wirklich tat:
    - Weder Stop noch Ziel. Um 22:58 klingelte der Zeitstopp bei +5,46 %, nach Kosten etwa +0,51R, rund +0,70 $.
    - Der geblockte Trade hätte diesmal also ein kleines Plus gebracht.
    - Ein Trade beweist nichts. Die 32 davor lagen nach Kosten bei −0,42R im Schnitt, und genau darauf schaut die Prüfung.
11. **`/meme-journal`** zählt jeden echten Trade nach Gebühren. Nach 20 Trades sagt es "bestanden" oder "durchgefallen". Erst dann darf die Größe steigen.

Und der Radar am Montagmorgen, 2. November 2026:
- 07:19 bis 07:23: 20 neue Coins, jeder hatte nach spätestens 30 Sekunden sein Urteil. 3-mal BUY (als Papier-Trade), 16-mal SKIP, ein gebündelter Launch.
- Ein Entwickler hatte vorher schon 171 Coins gestartet, ein anderer 191: sofort SKIP.
- 45 Sekunden nach seinem Signal stand OKCAT schon 33 % tiefer, HODL 56 % höher. Deshalb kauft der Papier-Test erst 45 Sekunden nach dem Signal, so lange wie du am Handy brauchst.
- 07:07 bis 07:19: 74 neue Coins, kein einziges BUY. Von 58 Coins, die sich verfolgen ließen, lagen 11 Minuten nach dem Start nur 8 im Plus.

## Woher die Daten kommen

| Quelle | wofür | offiziell? |
| --- | --- | --- |
| DexScreener API | Boosts, Profile, Takeovers, Ads; Preis, Liquidität, Volumen, Käufe/Verkäufe | ja, frei |
| GeckoTerminal | Trending und neue Pools; Kerzen für andere Chains | ja, frei, 30/min |
| Jupiter `datapi` | 1-Minuten-Kerzen per Mint (Solana); Token-Daten frischer Coins (Dev, Holder, Sniper, erste Trades) für den Radar | **inoffiziell** |
| Jupiter `lite-api` | SOL- und EUR-Kurs (EURC), Swap-Quotes zum Messen der echten Kosten (nur lesend) | ja, frei |
| PumpPortal Websocket | jeder neue pump.fun-Coin und jede Graduierung | Drittanbieter, frei (Trade-Streams kosten, nicht genutzt) |
| RugCheck | Token-Bericht Solana | ja, frei |
| GoPlus Security | Contract-Prüfung Solana, Base, BSC, Ethereum | ja, frei |
| Solana RPC | Wallet-Transaktionen | ja, öffentlich und knapp |
| RSS Cointelegraph, Decrypt, CoinDesk | Schlagzeilen | ja |
| Telegram `t.me/s/` | öffentliche Kanalvorschau | öffentlich |

X/Twitter wird nicht gelesen: Die offizielle API kostet seit 2026 etwa 0,005 $
pro gelesenem Post, und Scrapen verstößt gegen die Regeln.

## Die Tools

```bash
python3 meme-scanner/scan.py pairs                                  # Pool-Statistiken, Setups
python3 meme-scanner/scan.py range --edge                           # 1-Minuten-Ausbrüche, nach Edge sortiert
python3 meme-radar/radar.py --minutes 30 --quiet                    # neue pump.fun-Coins live: BUY oder SKIP
python3 meme-radar/radar.py test                                    # der Papier-Test bisher
python3 meme-analyst/report.py MINT --write                         # Rug-Check -> meme/safety.json
python3 meme-news/news.py --tokens MINT --telegram pumpfun          # Schlagzeilen, Telegram, Liquidität
python3 meme-entry/entry.py check MINT --from 21:42                 # building / waiting / triggered
python3 meme-exit/exit.py plan --write                              # -> meme/plan.json
python3 meme-timemachine/timemachine.py run --write                 # 10.000 Durchläufe + Historie
python3 meme-timemachine/timemachine.py compare                     # 180 Varianten, Gegenprobe
python3 meme-timemachine/timemachine.py multi                       # die Regel auf allen Coins der Watchlist
python3 meme-timemachine/timemachine.py ruin --from-multi           # was das für dein Konto heißt
python3 meme-budget/size.py --quote --write                         # -> meme/orders.json
python3 meme-risk/check.py                                          # PASS / BLOCK pro Order
python3 meme-broker/ticket.py show                                  # die Tickets, READY oder nicht
python3 meme-alerts/alerts.py add --from-plan                       # Stop, Ziel, Zeitstopp, Rug-Alarm
python3 meme-whales/whales.py import wallets.txt                    # Top-Trader-Liste beobachten
python3 meme-journal/journal.py                                     # deine Zahlen nach Gebühren
```

```bash
python3 -m unittest discover -s tests -v
```

Die Tests laufen komplett offline (ein Netzwerkzugriff lässt sie scheitern)
auf echten Daten jenes Abends:
- Scan-Antworten, GATOs Kerzen und die Kerzen von 11 Coins
- RugCheck-, GoPlus- und Jupiter-Antworten
- News-Feeds, ein Telegram-Kanal
- echte Wallet-Transaktionen und 16 Minuten Radar-Stream mit Jupiter-Daten

Sie reproduzieren jede Zahl oben.

## Kleingedrucktes

**Keine Finanzberatung.** Das ist Software, die öffentliche Daten liest und
rechnet. Sie kennt deine Situation nicht und kann nicht in die Zukunft sehen.

**Kein Trade ohne dein Ja.** Eine Order wird nur gezeigt, wenn `/meme-risk`
genau diese Order heute freigegeben hat, und gilt nur, wenn du im Chat
ausdrücklich "ja" oder "yes" zu genau dieser einen Order schreibst. Dann
tradest du selbst in deiner App (live) oder es wird simuliert (Paper).

**Nie deine Wallet.** Kein Tool verbindet sich mit einer Wallet, keins
signiert etwas, keins fragt nach Private Key oder Seed Phrase. Wenn dich
irgendwer danach fragt: nicht eingeben. Wenn du sie irgendwo eingefügt
hast: Guthaben sofort auf eine neue Wallet verschieben.

**Testphase statt Paper.** Wer gleich mit echtem Geld startet, startet klein:
Die ersten 20 echten Trades sind auf etwa 20 € begrenzt. Bestehen sie im
Journal nach Gebühren nicht, bleibt die Grenze.

**Die Time Machine ist eine Simulation, keine Vorhersage.** Sie ist aus den
letzten Tagen der Coins gebaut. Ein Rug, ein Dev-Verkauf oder ein Listing
können Dinge tun, die es in diesen Tagen nie gab.

**Ein Stop ist ein Plan, keine Garantie.** Ein Meme Coin kann durch den Stop
fallen oder dort keine Käufer haben. Im Handy-Modus ist dein Stop so schnell
wie deine Reaktion auf den Alarm.

**Die Daten sind kostenlos und teils inoffiziell.** Sie können verzögert,
falsch oder kurz weg sein. Prüf alles, was zählt, in deiner App. Kerzen sind
1-Minuten-Kerzen, nie Echtzeit.

**Fomo.** Fomo hat keine öffentliche Schnittstelle, und dieses Paket
verbindet sich nicht damit. Eine Stop-Loss-Funktion für normale Meme-Coin-
Trades war für Fomo nicht zu bestätigen; prüf es in der App.

**Steuern.** In Deutschland sind Gewinne aus Krypto, die du weniger als ein
Jahr hältst, als private Veräußerungsgeschäfte steuerpflichtig (Freigrenze
beachten). Das Journal exportiert deine Trades als CSV. Nichts hier ist
Steuerberatung.

## Dateien

```
meme-scanner/      SKILL.md, scan.py
meme-radar/        SKILL.md, radar.py
meme-analyst/      SKILL.md, report.py
meme-news/         SKILL.md, news.py
meme-entry/        SKILL.md, entry.py
meme-exit/         SKILL.md, exit.py
meme-timemachine/  SKILL.md, timemachine.py
meme-risk/         SKILL.md, check.py
meme-budget/       SKILL.md, size.py, config.example.json
meme-broker/       SKILL.md, ticket.py
meme-alerts/       SKILL.md, alerts.py, alerts.example.json
meme-whales/       SKILL.md, whales.py, wallets.example.json
meme-journal/      SKILL.md, journal.py
tests/             unittest-Suite + Offline-Fixtures
```

MIT. Aufgebaut auf dem Day Trader skill von [Jake Schincariol](https://opusjake.ai).
