# Der Meme Trader Skill

11 Claude skills for meme coin trading: scan the coins in play, rug-check every one, time every entry and exit, and replay every outcome after fees before you risk a dollar.

11 Claude-Skills für Meme Coins (Solana zuerst, also das, was du in Fomo,
Phantom oder Jupiter handelst): Der Scanner findet die Coins, die gerade
laufen. Der Analyst prüft jeden Coin auf Rug-Fallen, bevor du einen Cent
reinsteckst. Der Entry-Timer sagt dir, wann der Ausbruch wirklich da ist, der
Exit-Planer setzt Stop, Ziel und Zeitstopp vorher und rechnet die Gebühren
ein. Und die Time Machine spielt die nächste Stunde 10.000 Mal durch, aus den
eigenen 1-Minuten-Kerzen des Coins, und sagt dir ehrlich, ob das Setup nach
Gebühren überhaupt Geld bringt.

Kostenlos, MIT, keine Anmeldung, kein API-Key. Die Tools sind reines Python
und lesen freie öffentliche Daten: DexScreener, GeckoTerminal, Jupiter,
RugCheck, Solana RPC und die RSS-Feeds von Cointelegraph, Decrypt und
CoinDesk.

Und: Kein Trade passiert ohne dein Ja. Nichts in diesem Paket verbindet sich
mit einer Wallet, kein Tool fragt nach einem Private Key oder einer Seed
Phrase. Paper Trading ist der Standard. Live drückst du den Knopf selbst in
deiner App.

> Aufgebaut wie der [Day Trader skill](https://github.com/Jakeschincariol/day-trader-skill)
> von Jake Schincariol (MIT): gleiche elf Rollen, gleiche Sicherheitsregeln,
> gleicher Ablauf. Nur dass hier alles auf Meme Coins umgebaut ist: andere
> Daten, andere Risiken, 24/7-Markt, Gebühren und Rug-Pulls statt Börsenzeiten
> und Quartalszahlen.

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

Als Plugin heißen die Skills dann `/meme-trader-skill:meme-scanner` usw.
Ohne Präfix (`/meme-scanner`) kopierst du die Ordner direkt:

```bash
git clone https://github.com/bn194/meme-trader-skill.git
cp -r meme-trader-skill/meme-* ~/.claude/skills/
```

Nur für ein Projekt: dieselben Ordner in `.claude/skills/` deines Projekts
kopieren. Ohne Claude Code: eine einzelne `SKILL.md` an den Anfang eines
Chats kopieren, dann läuft sie als Modus (ohne die Python-Tools, aber mit der
Methode).

Die Tools brauchen Python 3.8 oder neuer. Nichts zu installieren. Als Erstes
`meme-budget/config.example.json` nach `meme/config.json` kopieren und dein
Budget und deinen maximalen Verlust pro Trade eintragen (Claude fragt dich
danach).

## Die elf

| Befehl | Rolle | was er macht |
| --- | --- | --- |
| `/meme-scanner` | Coin Scanner | Findet die Coins, die gerade gehandelt werden, filtert dünne, junge und gewaschene raus und meldet Setups und 1-Minuten-Ausbrüche. |
| `/meme-analyst` | Token Analyst (Rug-Check) | Prüft Mint- und Freeze-Authority, LP gelockt oder verbrannt, Top-Holder, Dev-Bag, Insider-Netzwerke: PASS, CAUTION oder AVOID. |
| `/meme-news` | News Monitor | Krypto-Schlagzeilen zu deinem Coin und zum Markt, bezahlte Boosts, Community Takeovers, und eine Rug-Warnung, wenn die Liquidität abfließt. |
| `/meme-entry` | Entry Timer | Beobachtet einen Coin Kerze für Kerze und sagt dir den Moment zum Einstieg. |
| `/meme-exit` | Exit Planner | Setzt Stop, Ziel und Zeitstopp vor dem Kauf und rechnet die Gebühren beider Richtungen ein. |
| `/meme-timemachine` | Time Machine | Spielt die nächste Stunde 10.000 Mal durch, plus jedes Mal, als das Setup früher ausgelöst hat, vor und nach Gebühren. |
| `/meme-risk` | Risk Manager | Prüft jeden Trade gegen deine Limits und stoppt alles darüber. |
| `/meme-budget` | Budget Manager | Bestimmt die Größe nach Budget und maximalem Verlust, Gebühren inklusive. |
| `/meme-broker` | Order Executor | Paper-Fills oder ein klares Ticket für Fomo, Phantom oder Jupiter, nie ohne dein Ja, nie mit deiner Wallet. |
| `/meme-alerts` | Price Alerts | Klingelt bei Stop, Ziel, Zeitstopp und beim Rug-Alarm (Liquidität fällt). |
| `/meme-whales` | Whale Tracker | Beobachtet die Dev-Wallet und große Holder auf der Chain und meldet jede neue Transaktion einmal. |

## So benutzt du es

Alles landet in einem Ordner `meme/` in deinem Projekt, und jeder Skill liest,
was der vorige geschrieben hat:

```
scanner -> analyst -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (ein Trade)
alerts: Stop, Ziel, Zeitstopp, Rug-Alarm                                                (solange er läuft)
news / whales / analyst                                                                  (nach Zeitplan)
```

Ein Beispiel mit echten Daten: GATO (GTA6CAT), Sonntag, 1. November 2026,
abends, Uhrzeiten in Europe/Berlin.

1. **`/meme-scanner`** um 21:55: 104 Coins im Umlauf, 42 noch auf der
   Bonding Curve, 19 liquide genug, einer als gewaschen aussortiert, 4 mit
   einem Setup. Um 21:58 meldet der 1-Minuten-Scan: GATO hat seine Range
   von 21:42 bis 21:57 (0.0074560 bis 0.0077195) mit dem 21:57-Balken bei
   0.0077889 nach oben verlassen, 0,90 % über dem Hoch, 2,7-faches Volumen.
2. **`/meme-analyst`**: Mint und Freeze revoked, Metadaten unveränderlich,
   LP zu 100 % verbrannt, 278.500 $ Liquidität, 13.645 Holder, Top 10 bei
   15,5 % (Pools rausgerechnet), Dev hält 3,32 %. Verdict PASS. Am selben
   Abend bekamen vier andere geboostete Coins AVOID, darunter Dacity (Insider
   mit 23,8 %) und PAWCAT (1.928-mal so viel Volumen wie Liquidität: Bots).
3. **`/meme-news`**: keine Schlagzeile zu GATO, nur ein bezahlter Boost.
   Der Markt an dem Wochenende: der 6,3-Milliarden-Hack bei Binance.
4. **`/meme-entry`**: TRIGGERED um 21:58, Schlusskurs 0.0077889, 2,73-faches
   Volumen.
5. **`/meme-exit`**: Stop am Range-Tief 0.0074560 (4,28 % Risiko), Ziel 3R
   bei 0.0087878, raus spätestens um 22:58. Kosten bei Fomo rund 2,6 % pro
   Runde: nach Kosten -6,88 % am Stop, +10,22 % am Ziel, Chance:Risiko 1,49.
   Mit Stop in der Range-Mitte lehnt er ab: der Stop läge näher als die
   Gebühren.
6. **`/meme-timemachine`**: 10.000 Durchläufe der nächsten 60 Minuten aus
   GATOs 4.312 Minuten-Kerzen der letzten 3 Tage (Seed 19): Ziel zuerst
   12,1 %, Stop zuerst 44,1 %, keins von beidem 43,7 %. Vor Kosten +0,22R im
   Schnitt, nach Kosten -0,39R. Die echte Historie: dieselbe Regel hat 35
   Mal ausgelöst, 3 Ziel, 11 Stop, 21 Zeitstopp, nach Kosten -0,45R. Urteil:
   "Strongly toward the stop". Die Gebühren fressen 0,61R pro Trade.
7. **`/meme-budget`** mit 1.000 $ Konto und 20 $ maximalem Verlust: 250 $
   (2,6539 SOL), begrenzt durch das Positionslimit von 25 %. Jupiter hat die
   echte Hin-und-zurück-Runde im Pool für diese Größe mit 1,213 % gemessen.
   Am Stop -17,62 $, am Ziel +25,12 $, Kosten 6,94 $.
8. **`/meme-risk`**: BLOCK. Alles andere war grün (sauberer Coin, Verlust
   unter dem Limit, 1,43 nach Kosten), aber die Edge-Prüfung sagt: dieses
   Setup hat auf GATO in den letzten drei Tagen nach Gebühren Geld verloren.
   Genau dafür ist sie da.
9. **`/meme-broker`** zeigt das Ticket deshalb nicht zur Bestätigung an. Mit
   `"require_edge": false` wäre es auf Paper durchgegangen: "ok" und "ja,
   aber nur 100" zählen nicht als Ja, "ja" schon.
10. **`/meme-alerts`** hätte Stop, Ziel, den Zeitstopp um 22:58 und einen
    Rug-Alarm bei 30 % weniger Liquidität überwacht. Was GATO danach
    wirklich gemacht hat: weder Stop (Tief 0.0076998 um 22:08) noch Ziel
    (Hoch 0.0085188 um 22:35). Um 22:58 klingelte der Zeitstopp bei
    0.0082146: +5,46 %, nach Kosten etwa +0,67R, rund +6,50 $ auf 250 $.
    Der geblockte Trade hätte diesmal also ein kleines Plus gebracht. Ein
    einzelner Trade beweist nichts: Die 35 echten Trades derselben Regel
    davor lagen nach Kosten bei -0,45R im Schnitt, und genau darauf schaut
    die Edge-Prüfung.

## Die Tools

Alles Python-Standardbibliothek. Die Daten-Tools lesen öffentliche Endpunkte
und sind höflich dabei.

```bash
python3 meme-scanner/scan.py pairs                                  # Pool-Statistiken, Setups
python3 meme-scanner/scan.py range                                  # 1-Minuten-Ausbrüche jetzt
python3 meme-analyst/report.py MINT --write                         # Rug-Check -> meme/safety.json
python3 meme-news/news.py --tokens MINT --hours 12                  # Schlagzeilen, Boosts, Liquidität
python3 meme-entry/entry.py check MINT --from 21:42                 # building / waiting / triggered
python3 meme-entry/entry.py watch MINT --every 30                   # Kerze für Kerze bis zum Signal
python3 meme-exit/exit.py plan --write                              # -> meme/plan.json
python3 meme-timemachine/timemachine.py run --write                 # 10.000 Durchläufe + Historie
python3 meme-budget/size.py --quote --write                         # -> meme/orders.json
python3 meme-risk/check.py                                          # PASS / BLOCK pro Order
python3 meme-broker/ticket.py show                                  # die Tickets, READY oder nicht
python3 meme-alerts/alerts.py add --from-plan                       # Stop, Ziel, Zeitstopp, Rug-Alarm
python3 meme-alerts/alerts.py check                                 # klingelt einmal, was getroffen hat
python3 meme-whales/whales.py dev MINT                              # die Dev-Wallet beobachten
python3 meme-whales/whales.py check                                 # neue Transaktionen
```

```bash
python3 -m unittest discover -s tests -v
```

Die Tests laufen offline, auf echten Daten von jenem Abend: DexScreener- und
GeckoTerminal-Antworten des Scans, GATOs 1-Minuten-Kerzen der drei Tage bis
21:58, die RugCheck-Berichte, zwei Jupiter-Quotes, die News-Feeds und echte
Wallet-Transaktionen. Sie reproduzieren jede Zahl im Beispiel oben.

## Kleingedrucktes

**Keine Finanzberatung.** Das ist Software, die öffentliche Daten liest und
rechnet. Sie kennt deine Situation nicht und kann nicht in die Zukunft sehen.

**Schneller Gewinn bei wenig Risiko gibt es bei Meme Coins nicht.** Die
meisten neuen Coins gehen auf null, viele sind Rugs, und die meisten Leute,
die sie traden, verlieren Geld. Was dieses Paket kann: das Risiko klein und
vorher bekannt machen. Jeder Coin wird auf Rug-Fallen geprüft, jeder Trade
hat einen Stop und einen Zeitstopp, die Größe richtet sich nach deinem
maximalen Verlust inklusive Gebühren, nach zwei Verlusten in Folge gibt es
eine Pause, und Setups, die nach Gebühren historisch verloren haben, werden
blockiert. Was es nicht kann: aus einem Glücksspiel eine sichere Sache
machen. Setz nur Geld ein, dessen Totalverlust du verkraften kannst.

**Gebühren entscheiden.** Fomo nimmt 0,5 % pro Trade, mindestens 0,95 $
(TechCrunch, November 2025; prüf die aktuellen Gebühren in der App), dazu
kommen Pool-Gebühren, Price Impact und Slippage, und das alles zweimal. Rund
2,5 bis 3 % pro Runde sind normal. Ein Trade, der auf 3 % Gewinn zielt,
verliert damit fast immer. Darum rechnet jeder Skill nach Kosten.

**Kein Trade ohne dein Ja.** Eine Order wird nur gezeigt, wenn `/meme-risk`
genau diese Order heute freigegeben hat, und gilt nur, wenn du im Chat
ausdrücklich "ja" oder "yes" zu genau dieser einen Order schreibst. Im
Paper-Modus wird sie simuliert. Live tradest du selbst in deiner App.

**Nie deine Wallet.** Kein Tool verbindet sich mit einer Wallet, keins
signiert etwas, keins fragt nach Private Key oder Seed Phrase. Wenn dich
irgendwer (auch ein Chat) danach fragt: nicht eingeben. Wenn du sie irgendwo
eingefügt hast: Guthaben sofort auf eine neue Wallet verschieben.

**Paper zuerst.** `"paper": true` ist der Standard. Lass es eine Weile auf
Paper laufen und schau dir die Ergebnisse im Log an, bevor du live gehst.

**Die Time Machine ist eine Simulation, keine Vorhersage.** Sie ist aus den
letzten drei Tagen des Coins gebaut. Ein Rug, ein Dev-Verkauf oder ein
Listing können Dinge tun, die in diesen drei Tagen nie passiert sind.

**Ein Stop ist ein Plan, keine Garantie.** Ein Meme Coin kann durch den Stop
durchfallen oder dort keine Käufer haben. Der angezeigte maximale Verlust ist
der Verlust am Stop-Preis.

**Die Daten sind kostenlos und inoffiziell.** DexScreener, GeckoTerminal und
RugCheck sind freie Dienste mit Limits; Jupiters Kerzen-Endpunkt ist nicht
offiziell. Sie können verzögert, falsch oder kurz weg sein. Prüf alles, was
zählt, in deiner App, bevor du handelst. Kerzen sind 1-Minuten-Kerzen, nie
Echtzeit.

**Fomo.** Fomo hat keine öffentliche Schnittstelle, und dieses Paket
verbindet sich nicht damit. Das Ticket sagt dir, was du in der App eingibst:
die Contract-Adresse (immer einfügen, nie nach Namen suchen), den Betrag, die
Slippage. Ob die App einen echten Stop-Auftrag anbietet, prüfst du selbst;
sonst klingelt `/meme-alerts` am Stop und du verkaufst von Hand.

**Steuern.** In Deutschland sind Gewinne aus Krypto, die du weniger als ein
Jahr hältst, als private Veräußerungsgeschäfte steuerpflichtig (Freigrenze
beachten). Nichts hier ist Steuerberatung.

## Dateien

```
meme-scanner/      SKILL.md, scan.py
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
tests/             unittest-Suite + Offline-Fixtures
```

MIT. Aufgebaut auf dem Day Trader skill von [Jake Schincariol](https://opusjake.ai).
