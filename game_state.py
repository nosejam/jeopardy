from __future__ import annotations

import csv
import io
import random
import secrets
import socket
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


NORMAL_ROUNDS = ("Jeopardy", "Double Jeopardy")
FINAL_ROUND = "Final Jeopardy"
ROUND_ALIASES = {
    "J!": "Jeopardy",
    "JEOPARDY!": "Jeopardy",
    "JEOPARDY": "Jeopardy",
    "DJ!": "Double Jeopardy",
    "DOUBLE JEOPARDY!": "Double Jeopardy",
    "DOUBLE JEOPARDY": "Double Jeopardy",
    "FJ!": FINAL_ROUND,
    "FINAL JEOPARDY!": FINAL_ROUND,
    "FINAL JEOPARDY": FINAL_ROUND,
}
ROUND_VALUES = {
    "Jeopardy": (200, 400, 600, 800, 1000),
    "Double Jeopardy": (400, 800, 1200, 1600, 2000),
}


@dataclass
class Clue:
    id: str
    round: str
    category: str
    value: int
    clue: str
    answer: str
    accepted_answers: str
    daily_double: bool = False
    used: bool = False
    game_id: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "round": self.round,
            "category": self.category,
            "value": self.value,
            "clue": self.clue,
            "daily_double": self.daily_double,
            "used": self.used,
        }

    def host_dict(self) -> dict[str, Any]:
        data = self.public_dict()
        data.update({"answer": self.answer, "accepted_answers": self.accepted_answers})
        return data


@dataclass
class Player:
    id: str
    name: str
    score: int = 0
    connected: bool = False
    socket_count: int = 0

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "score": self.score,
            "connected": self.connected,
        }


@dataclass
class FinalEntry:
    wager: int | None = None
    answer: str | None = None
    locked_wager: bool = False
    locked_answer: bool = False
    revealed_wager: bool = False
    revealed_answer: bool = False
    judged: bool = False
    correct: bool | None = None


@dataclass
class GameState:
    title: str
    incorrect_subtracts_points: bool = True
    reopen_after_incorrect: bool = True
    maximum_players: int = 24
    sound_enabled: bool = True
    clues: dict[str, Clue] = field(default_factory=dict)
    source_clues: dict[str, Clue] = field(default_factory=dict)
    _game_options: list[str] = field(default_factory=list, init=False, repr=False)
    current_game_selection: str = "random"
    players: dict[str, Player] = field(default_factory=dict)
    status: str = "lobby"
    current_round: str = "Jeopardy"
    current_clue_id: str | None = None
    buzzer_open: bool = False
    first_buzzer: str | None = None
    current_respondent: str | None = None
    locked_out: set[str] = field(default_factory=set)
    judged_respondents: set[str] = field(default_factory=set)
    answer_revealed: bool = False
    daily_double_active: bool = False
    daily_double_player: str | None = None
    daily_double_wager: int | None = None
    final_phase: str = "idle"
    final_category: str | None = None
    final_clue_id: str | None = None
    final_entries: dict[str, FinalEntry] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_clues:
            self.source_clues = clone_clues(self.clues)
        self._game_options = collect_game_options(self.source_clues)
        if self.source_clues:
            try:
                self.clues = self.build_game_clues(self.current_game_selection)
            except ValueError:
                self.clues = clone_clues(self.source_clues)

    @property
    def game_options(self) -> list[str]:
        return list(self._game_options)

    def load_source(self, clues: dict[str, Clue]) -> None:
        if not clues:
            raise ValueError("A clue source must include at least one clue.")
        self.source_clues = clone_clues(clues)
        self._game_options = collect_game_options(self.source_clues)
        if self.current_game_selection != "random" and self.current_game_selection not in self.game_options:
            self.current_game_selection = "random"
        self.load_game(self.build_game_clues(self.current_game_selection))

    def load_game(self, clues: dict[str, Clue]) -> None:
        if not clues:
            raise ValueError("A game must include at least one clue.")
        self.clues = clone_clues(clues)
        self.reset()

    def set_game_selection(self, selection: str) -> None:
        clean_selection = selection.strip() or "random"
        if clean_selection != "random" and clean_selection not in self.game_options:
            raise ValueError("Unknown game ID.")
        self.current_game_selection = clean_selection
        self.load_game(self.build_game_clues(clean_selection))

    def build_game_clues(self, selection: str) -> dict[str, Clue]:
        if selection != "random":
            selected = {cid: clue for cid, clue in self.source_clues.items() if clue.game_id == selection}
            if not selected:
                raise ValueError("No clues found for that game ID.")
            return clone_clues(selected)
        return self.build_random_game()

    def build_random_game(self) -> dict[str, Clue]:
        selected: dict[str, Clue] = {}
        for round_name, values in ROUND_VALUES.items():
            selected.update(self.random_round_clues(round_name, values))
        final_clues = [clue for clue in self.source_clues.values() if clue.round == FINAL_ROUND]
        if final_clues:
            clue = replace(random.choice(final_clues), used=False)
            selected[clue.id] = clue
        if selected:
            return selected
        return clone_clues(self.source_clues)

    def random_round_clues(self, round_name: str, values: tuple[int, ...]) -> dict[str, Clue]:
        by_category: dict[str, dict[int, list[Clue]]] = {}
        for clue in self.source_clues.values():
            if clue.round != round_name:
                continue
            by_category.setdefault(clue.category, {}).setdefault(clue.value, []).append(clue)
        usable_categories = [
            category
            for category, by_value in by_category.items()
            if all(by_value.get(value) for value in values)
        ]
        if len(usable_categories) < 6:
            return {}

        selected: dict[str, Clue] = {}
        for category in random.sample(usable_categories, 6):
            for value in values:
                clue = replace(random.choice(by_category[category][value]), used=False)
                selected[clue.id] = clue
        return selected

    def add_or_update_player(self, player_id: str | None, name: str) -> Player:
        clean_name = (name or "Player").strip()[:32] or "Player"
        if player_id and player_id in self.players:
            player = self.players[player_id]
            player.name = clean_name
            return player
        if len(self.players) >= self.maximum_players:
            raise ValueError("The game is full.")
        new_id = player_id or secrets.token_urlsafe(12)
        while new_id in self.players:
            new_id = secrets.token_urlsafe(12)
        player = Player(id=new_id, name=clean_name)
        self.players[new_id] = player
        self.final_entries.setdefault(new_id, FinalEntry())
        return player

    def connect_player(self, player_id: str) -> None:
        if player_id in self.players:
            player = self.players[player_id]
            player.socket_count += 1
            player.connected = True

    def disconnect_player(self, player_id: str) -> None:
        if player_id in self.players:
            player = self.players[player_id]
            player.socket_count = max(0, player.socket_count - 1)
            player.connected = player.socket_count > 0

    def remove_player(self, player_id: str) -> None:
        self.players.pop(player_id, None)
        self.final_entries.pop(player_id, None)
        self.locked_out.discard(player_id)
        if self.first_buzzer == player_id:
            self.first_buzzer = None
        if self.current_respondent == player_id:
            self.current_respondent = None

    def board(self, round_name: str | None = None) -> dict[str, list[dict[str, Any]]]:
        target = round_name or self.current_round
        categories: dict[str, list[dict[str, Any]]] = {}
        for clue in self.clues.values():
            if clue.round != target or clue.round == FINAL_ROUND:
                continue
            categories.setdefault(clue.category, []).append(clue.public_dict())
        return {name: sorted(items, key=lambda c: c["value"]) for name, items in categories.items()}

    def start_game(self) -> None:
        self.clues = self.build_game_clues(self.current_game_selection)
        self.status = "board"
        self.current_round = "Jeopardy"
        self.current_clue_id = None
        self.buzzer_open = False
        self.first_buzzer = None
        self.current_respondent = None
        self.locked_out.clear()
        self.judged_respondents.clear()
        self.answer_revealed = False
        self.daily_double_active = False
        self.daily_double_player = None
        self.daily_double_wager = None
        self.final_phase = "idle"
        self.final_category = None
        self.final_clue_id = None
        self.final_entries = {pid: FinalEntry() for pid in self.players}

    def set_round(self, round_name: str) -> None:
        if round_name not in NORMAL_ROUNDS:
            raise ValueError("Unsupported board round.")
        self.current_round = round_name
        self.status = "board"
        self.current_clue_id = None
        self.close_buzzers()

    def select_clue(self, clue_id: str) -> Clue:
        clue = self.require_clue(clue_id)
        if clue.used:
            raise ValueError("That clue is already used.")
        self.current_clue_id = clue_id
        self.status = "daily_double_intro" if clue.daily_double else "clue"
        self.buzzer_open = False
        self.first_buzzer = None
        self.current_respondent = None
        self.locked_out.clear()
        self.judged_respondents.clear()
        self.answer_revealed = False
        self.daily_double_active = clue.daily_double
        self.daily_double_player = None
        self.daily_double_wager = clue.value if clue.daily_double else None
        return clue

    def reveal_daily_double(self) -> None:
        if not self.current_clue or not self.current_clue.daily_double:
            raise ValueError("Current clue is not a Daily Double.")
        self.status = "clue"

    @property
    def current_clue(self) -> Clue | None:
        return self.clues.get(self.current_clue_id) if self.current_clue_id else None

    def require_clue(self, clue_id: str) -> Clue:
        if clue_id not in self.clues:
            raise ValueError("Unknown clue.")
        return self.clues[clue_id]

    def open_buzzers(self) -> None:
        if not self.current_clue:
            raise ValueError("No clue is active.")
        if self.current_clue.used:
            raise ValueError("That clue is already complete.")
        if self.daily_double_active:
            raise ValueError("Daily Doubles are host-scored without open buzzers.")
        self.buzzer_open = True
        self.first_buzzer = None
        self.current_respondent = None

    def close_buzzers(self) -> None:
        self.buzzer_open = False

    def buzz(self, player_id: str) -> bool:
        if not self.buzzer_open or self.first_buzzer or player_id in self.locked_out:
            return False
        if player_id in self.judged_respondents:
            return False
        if player_id not in self.players:
            return False
        self.first_buzzer = player_id
        self.current_respondent = player_id
        self.buzzer_open = False
        return True

    def mark_correct(self, wager: int | None = None) -> None:
        player_id = self.daily_double_player if self.daily_double_active else self.current_respondent
        if not player_id:
            raise ValueError("No respondent selected.")
        clue = self.current_clue
        if not clue:
            raise ValueError("No clue is active.")
        self._ensure_not_judged(player_id)
        amount = self._score_amount(wager)
        self.players[player_id].score += amount
        self.judged_respondents.add(player_id)
        clue.used = True
        self.buzzer_open = False
        self.status = "clue_complete"

    def mark_incorrect(self, wager: int | None = None) -> None:
        player_id = self.daily_double_player if self.daily_double_active else self.current_respondent
        if not player_id:
            raise ValueError("No respondent selected.")
        self._ensure_not_judged(player_id)
        amount = self._score_amount(wager)
        if self.incorrect_subtracts_points:
            self.players[player_id].score -= amount
        self.judged_respondents.add(player_id)
        self.locked_out.add(player_id)
        self.buzzer_open = False
        self.first_buzzer = None
        self.current_respondent = None
        if self.daily_double_active:
            if self.current_clue:
                self.current_clue.used = True
            self.status = "clue_complete"

    def display_answer(self) -> None:
        if not self.current_clue:
            raise ValueError("No clue is active.")
        self.answer_revealed = True
        self.buzzer_open = False

    def close_clue(self, mark_used: bool = True) -> None:
        if self.current_clue and mark_used:
            self.current_clue.used = True
        self.buzzer_open = False
        self.status = "clue_complete"

    def return_to_board(self) -> None:
        self.current_clue_id = None
        self.buzzer_open = False
        self.first_buzzer = None
        self.current_respondent = None
        self.locked_out.clear()
        self.judged_respondents.clear()
        self.answer_revealed = False
        self.daily_double_active = False
        self.daily_double_player = None
        self.daily_double_wager = None
        self.status = "board"

    def adjust_score(self, player_id: str, delta: int) -> None:
        self.players[player_id].score += delta

    def set_score(self, player_id: str, score: int) -> None:
        self.players[player_id].score = score

    def set_daily_double(self, player_id: str | None, wager: int | None) -> None:
        self.daily_double_player = player_id
        self.daily_double_wager = wager

    def show_scoreboard(self, final: bool = False) -> None:
        self.status = "final_standings" if final else "scoreboard"
        self.close_buzzers()

    def reset(self) -> None:
        for player in self.players.values():
            player.score = 0
        for clue in self.clues.values():
            clue.used = False
        self.status = "lobby"
        self.current_round = "Jeopardy"
        self.current_clue_id = None
        self.buzzer_open = False
        self.first_buzzer = None
        self.current_respondent = None
        self.locked_out.clear()
        self.judged_respondents.clear()
        self.answer_revealed = False
        self.daily_double_active = False
        self.daily_double_player = None
        self.daily_double_wager = None
        self.final_phase = "idle"
        self.final_entries = {pid: FinalEntry() for pid in self.players}

    def start_final(self) -> None:
        final_clues = [c for c in self.clues.values() if c.round == FINAL_ROUND]
        if not final_clues:
            raise ValueError("No Final Jeopardy clue found.")
        clue = final_clues[0]
        self.current_clue_id = clue.id
        self.final_clue_id = clue.id
        self.final_category = clue.category
        self.status = "final"
        self.final_phase = "wagers"
        self.final_entries = {pid: self.final_entries.get(pid, FinalEntry()) for pid in self.players}

    def submit_final_wager(self, player_id: str, wager: int) -> None:
        entry = self.final_entries.setdefault(player_id, FinalEntry())
        if entry.locked_wager:
            raise ValueError("Final Jeopardy wager is already submitted.")
        entry.wager = max(0, int(wager))
        entry.locked_wager = True

    def reveal_final_clue(self) -> None:
        self.final_phase = "answers"

    def submit_final_answer(self, player_id: str, answer: str) -> None:
        entry = self.final_entries.setdefault(player_id, FinalEntry())
        if entry.locked_answer:
            raise ValueError("Final Jeopardy answer is already submitted.")
        entry.answer = answer.strip()[:500]
        entry.locked_answer = True

    def reveal_final_wager(self, player_id: str) -> None:
        entry = self.final_entries.setdefault(player_id, FinalEntry())
        if not entry.locked_wager:
            raise ValueError("Final Jeopardy wager has not been submitted.")
        entry.revealed_wager = True

    def reveal_final_answer(self, player_id: str) -> None:
        entry = self.final_entries.setdefault(player_id, FinalEntry())
        if not entry.locked_answer:
            raise ValueError("Final Jeopardy response has not been submitted.")
        entry.revealed_answer = True

    def judge_final(self, player_id: str, correct: bool) -> None:
        entry = self.final_entries.setdefault(player_id, FinalEntry())
        if entry.judged:
            raise ValueError("That Final Jeopardy answer has already been judged.")
        wager = entry.wager or 0
        self.players[player_id].score += wager if correct else -wager
        entry.judged = True
        entry.correct = correct

    def reset_final_player(self, player_id: str, field_name: str) -> None:
        entry = self.final_entries.setdefault(player_id, FinalEntry())
        if field_name == "wager":
            entry.wager = None
            entry.locked_wager = False
            entry.revealed_wager = False
        elif field_name == "answer":
            entry.answer = None
            entry.locked_answer = False
            entry.revealed_answer = False

    def _score_amount(self, wager: int | None = None) -> int:
        clue = self.current_clue
        if not clue:
            raise ValueError("No clue is active.")
        if self.daily_double_active:
            return int(wager if wager is not None else self.daily_double_wager or clue.value)
        return clue.value

    def _ensure_not_judged(self, player_id: str) -> None:
        if player_id in self.judged_respondents:
            raise ValueError("That player has already been marked for this clue.")

    def public_state(self, player_id: str | None = None) -> dict[str, Any]:
        clue = self.current_clue.public_dict() if self.current_clue and self.status not in {"board", "lobby"} else None
        my_final = self.final_entries.get(player_id, FinalEntry()) if player_id else FinalEntry()
        return {
            "title": self.title,
            "status": self.status,
            "current_round": self.current_round,
            "players": self.sorted_players(),
            "me": self.players[player_id].public_dict() if player_id in self.players else None,
            "board": self.board(),
            "current_clue": clue,
            "buzzer_open": self.buzzer_open,
            "first_buzzer": self.first_buzzer,
            "first_buzzer_name": self.player_name(self.first_buzzer),
            "current_respondent": self.current_respondent,
            "locked_out": list(self.locked_out),
            "judged_respondents": list(self.judged_respondents),
            "eligible_to_buzz": bool(
                player_id
                and self.buzzer_open
                and player_id not in self.locked_out
                and player_id not in self.judged_respondents
                and not self.first_buzzer
            ),
            "daily_double_active": self.daily_double_active,
            "daily_double_player": self.daily_double_player,
            "final_phase": self.final_phase,
            "final_category": self.final_category,
            "final_wager_submitted": my_final.locked_wager,
            "final_answer_submitted": my_final.locked_answer,
        }

    def display_state(self, join_url: str, qr_url: str) -> dict[str, Any]:
        state = self.public_state()
        state.update({"join_url": join_url, "qr_url": qr_url})
        state["answer_revealed"] = self.answer_revealed
        state["revealed_answer"] = self.current_clue.answer if self.answer_revealed and self.current_clue else None
        state["final_reveals"] = [
            {
                "player": self.players[pid].public_dict(),
                "wager": entry.wager if entry.revealed_wager else None,
                "answer": entry.answer if entry.revealed_answer else None,
                "revealed_wager": entry.revealed_wager,
                "revealed_answer": entry.revealed_answer,
                "correct": entry.correct,
                "judged": entry.judged,
            }
            for pid, entry in self.final_entries.items()
            if pid in self.players and (entry.revealed_wager or entry.revealed_answer)
        ]
        return state

    def host_state(self, join_url: str, qr_url: str) -> dict[str, Any]:
        state = self.display_state(join_url, qr_url)
        state["current_clue"] = self.current_clue.host_dict() if self.current_clue else None
        state["answers_visible"] = True
        state["game_selection"] = self.current_game_selection
        state["game_options"] = self.game_options
        state["source_clue_count"] = len(self.source_clues)
        state["final_entries"] = {
            pid: {
                "player": self.players[pid].public_dict(),
                "wager": entry.wager,
                "answer": entry.answer,
                "locked_wager": entry.locked_wager,
                "locked_answer": entry.locked_answer,
                "revealed_wager": entry.revealed_wager,
                "revealed_answer": entry.revealed_answer,
                "judged": entry.judged,
                "correct": entry.correct,
            }
            for pid, entry in self.final_entries.items()
            if pid in self.players
        }
        return state

    def sorted_players(self) -> list[dict[str, Any]]:
        return [p.public_dict() for p in sorted(self.players.values(), key=lambda p: (-p.score, p.name.lower()))]

    def player_name(self, player_id: str | None) -> str | None:
        return self.players[player_id].name if player_id in self.players else None


REQUIRED_CSV_COLUMNS = {"round", "category", "value", "clue"}


def load_clues(csv_path: str | Path) -> dict[str, Clue]:
    with Path(csv_path).open(newline="", encoding="utf-8-sig") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        return _load_clues_from_reader(csv.DictReader(handle, dialect=sniff_csv_dialect(sample)))


def load_clues_from_text(csv_text: str) -> dict[str, Clue]:
    return _load_clues_from_reader(csv.DictReader(io.StringIO(csv_text), dialect=sniff_csv_dialect(csv_text[:8192])))


def _load_clues_from_reader(reader: csv.DictReader) -> dict[str, Clue]:
    if not reader.fieldnames:
        raise ValueError("CSV file is empty.")
    missing = REQUIRED_CSV_COLUMNS - set(reader.fieldnames)
    if missing:
        raise ValueError(f"CSV is missing required column(s): {', '.join(sorted(missing))}.")
    if "answer" not in reader.fieldnames and "correct_response" not in reader.fieldnames:
        raise ValueError("CSV is missing required column: answer or correct_response.")

    clues: dict[str, Clue] = {}
    for index, row in enumerate(reader, start=1):
        round_name = normalize_round(row["round"])
        category = row["category"].strip()
        raw_value = (row.get("value") or "0").strip()
        try:
            value = int(raw_value) if raw_value else 0
        except ValueError as exc:
            raise ValueError(f"Row {index} has an invalid value: {raw_value}.") from exc
        clue_text = row["clue"].strip()
        answer = (row.get("answer") or row.get("correct_response") or "").strip()
        if not round_name or not category or not clue_text or not answer:
            raise ValueError(f"Row {index} is missing round, category, clue, or answer text.")
        source_clue_id = (row.get("clue_id") or "").strip()
        game_id = (row.get("game_id") or "").strip() or None
        clue_id = source_clue_id or f"{round_name}:{category}:{value}:{index}"
        if game_id:
            clue_id = f"{game_id}:{clue_id}"
        clues[clue_id] = Clue(
            id=clue_id,
            round=round_name,
            category=category,
            value=value,
            clue=clue_text,
            answer=answer,
            accepted_answers=(row.get("accepted_answers") or "").strip(),
            daily_double=(row.get("daily_double") or "").strip().lower() in {"true", "1", "yes", "y"},
            game_id=game_id,
        )
    if not clues:
        raise ValueError("CSV contains no clues.")
    return clues


def normalize_round(raw_round: str) -> str:
    value = (raw_round or "").strip()
    return ROUND_ALIASES.get(value.upper(), value)


def sniff_csv_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        return csv.excel


def game_id_sort_key(game_id: str) -> tuple[int, int | str]:
    return (0, int(game_id)) if game_id.isdigit() else (1, game_id.lower())


def collect_game_options(clues: dict[str, Clue]) -> list[str]:
    return sorted({clue.game_id for clue in clues.values() if clue.game_id}, key=game_id_sort_key)


def clone_clues(clues: dict[str, Clue]) -> dict[str, Clue]:
    return {clue_id: replace(clue, used=False) for clue_id, clue in clues.items()}


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
