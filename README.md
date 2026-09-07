# Jeopardy Game

A local-network Jeopardy-style game for a laptop host, projector display, and phones on the same Wi-Fi network. It uses FastAPI, WebSockets, plain HTML/CSS/JavaScript, and CSV clue data. Gameplay does not require Internet access or external services.

## Setup

1. Install Python dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. The default clue source is `data/jeopardy_clue_bank.csv`. You can also put another clue CSV in `data/` and point `config.json` at it. The configured file is the server startup default; an authenticated host can also load a different CSV from the host page for the current session.

3. Edit `config.json` if needed:

   ```json
   {
     "game_title": "Jeopardy Game",
     "host_pin": "2468",
     "question_csv": "data/jeopardy_clue_bank.csv"
   }
   ```

4. Start the server:

   ```bash
   python app.py
   ```

5. Open the printed URLs:

   - New projector or TV display: `http://YOUR_LOCAL_IP:8000/display`
   - Game-specific host controls: `http://YOUR_LOCAL_IP:8000/g/GAME_CODE/host`
   - Game-specific join page: `http://YOUR_LOCAL_IP:8000/g/GAME_CODE`

Opening `/display` creates a unique in-memory game room and redirects to `/g/GAME_CODE/display`. The display page shows a QR code for `/g/GAME_CODE`, where phones can choose to host or join as players. Only one host can claim each game.

## Finding The Local IP

The app prints the detected local URL when it starts. If that address does not work, find the laptop IP manually:

```bash
hostname -I
```

Use the address on the same Wi-Fi network as the phones, usually something like `192.168.x.x` or `10.x.x.x`.

## Clue CSV Format

The legacy sample CSV header is:

```csv
round,category,value,clue,answer,accepted_answers,daily_double
```

The clue bank format is also supported:

```csv
category,clue,correct_response,value,round,daily_double,game_id,clue_id
```

Supported rounds are:

- `Jeopardy`
- `Double Jeopardy`
- `Final Jeopardy`
- `J!`
- `DJ!`
- `FJ!`

Normal boards expect six categories with five clues each. Correct responses are only sent to the authenticated host page.

When the host selects `Random`, the app groups the loaded clue source by category, excludes categories without a full set of values, randomly chooses six categories, and randomly chooses one clue at each value. Fixed `game_id` selections use the clues from that game ID instead.

Host-uploaded CSVs are parsed in memory for that game room and are not written to disk. Restarting the server returns new games to the configured default clue source.

## Teams

The first person on a team enters a display name to create it. Additional phones can join that same team from the join page by tapping the existing team name. Every phone on a team can buzz for the team. In Final Jeopardy, the first wager or response submitted by any team member locks that team’s entry.

## Running Tests

```bash
pytest
```

The tests cover CSV parsing, buzzer locking, buzz eligibility, scoring, reconnection, Daily Double scoring, and Final Jeopardy wagers.

## Development Simulation

You can simulate multiple players from one computer by opening several browser tabs or private/incognito windows at a game-specific join URL such as `/g/GAME_CODE`. Each browser profile gets its own stored team membership for that game.
