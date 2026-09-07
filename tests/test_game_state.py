from pathlib import Path

import pytest

from game_state import GameState, load_clues, load_clues_from_text


CSV = Path(__file__).resolve().parents[1] / "data" / "jeopardy_practice_questions.csv"


def make_state() -> GameState:
    return GameState(
        title="Test",
        clues=load_clues(CSV),
        incorrect_subtracts_points=True,
        reopen_after_incorrect=True,
    )


def first_regular_clue(state: GameState):
    return next(c for c in state.clues.values() if c.round == "Jeopardy" and not c.daily_double)


def first_daily_double(state: GameState):
    return next(c for c in state.clues.values() if c.daily_double)


def test_csv_parsing_loads_rounds_and_daily_double():
    clues = load_clues(CSV)
    assert len(clues) >= 30
    assert any(c.round == "Jeopardy" for c in clues.values())
    assert any(c.round == "Double Jeopardy" for c in clues.values())
    assert any(c.round == "Final Jeopardy" for c in clues.values())
    assert any(c.daily_double for c in clues.values())


def test_load_clues_from_text_parses_uploaded_csv_in_memory():
    clues = load_clues_from_text(
        "round,category,value,clue,answer,accepted_answers,daily_double\n"
        "Jeopardy,Family,200,This person hosts dinner,Who is Pat?,Pat,false\n"
        "Final Jeopardy,Milestones,0,This was the big year,What is 1999?,,false\n"
    )

    assert len(clues) == 2
    assert any(c.clue == "This person hosts dinner" for c in clues.values())
    assert any(c.round == "Final Jeopardy" for c in clues.values())


def test_load_clues_from_text_parses_clue_bank_format():
    clues = load_clues_from_text(
        "category,clue,correct_response,value,round,daily_double,game_id,clue_id\n"
        "Family,This person hosts dinner,Pat,200,J!,false,42,abc\n"
    )

    clue = next(iter(clues.values()))
    assert clue.round == "Jeopardy"
    assert clue.answer == "Pat"
    assert clue.game_id == "42"


def test_load_clues_from_text_parses_fj_clue_bank_rows():
    clues = load_clues_from_text(
        "category,clue,correct_response,value,round,daily_double,game_id,clue_id\n"
        "FAMILY HISTORY,Year of the land run when the McGee family claimed land,1893,,FJ!,false,1,155\n"
    )

    clue = next(iter(clues.values()))
    assert clue.round == "Final Jeopardy"
    assert clue.category == "FAMILY HISTORY"
    assert clue.value == 0
    assert clue.answer == "1893"
    assert clue.game_id == "1"


def test_load_clues_from_text_parses_tab_delimited_fj_rows():
    clues = load_clues_from_text(
        "category\tclue\tcorrect_response\tvalue\tround\tdaily_double\tgame_id\tclue_id\n"
        "FAMILY HISTORY\tYear of the land run when the Port family claimed land\t1889\t\tFJ!\tfalse\t\t154\n"
    )

    clue = next(iter(clues.values()))
    assert clue.round == "Final Jeopardy"
    assert clue.value == 0
    assert clue.answer == "1889"


def test_load_game_replaces_clues_and_resets_current_game_only():
    state = make_state()
    player = state.add_or_update_player("p1", "Sarah")
    player.score = 1200
    old_clue = first_regular_clue(state)
    state.select_clue(old_clue.id)
    state.open_buzzers()

    new_clues = load_clues_from_text(
        "round,category,value,clue,answer,accepted_answers,daily_double\n"
        "Jeopardy,New,100,New clue,New response,,false\n"
    )
    state.load_game(new_clues)

    assert state.clues == new_clues
    assert old_clue.id not in state.clues
    assert state.players[player.id].score == 0
    assert state.status == "lobby"
    assert state.current_clue is None
    assert state.buzzer_open is False


def test_game_selection_loads_specific_game_id():
    clues = load_clues_from_text(
        "category,clue,correct_response,value,round,daily_double,game_id,clue_id\n"
        "Game One,One,One,200,J!,false,1,1\n"
        "Game Two,Two,Two,200,J!,false,2,1\n"
    )
    state = GameState(title="Test", clues=clues)

    state.set_game_selection("2")

    assert state.game_options == ["1", "2"]
    assert list(state.board()) == ["Game Two"]


def test_random_game_selects_six_complete_categories():
    rows = ["category,clue,correct_response,value,round,daily_double,game_id,clue_id"]
    for category_index in range(7):
        for value in (200, 400, 600, 800, 1000):
            rows.append(f"Cat {category_index},Clue {category_index}-{value},Response,{value},J!,false,,{category_index}-{value}")
    rows.append("Too Small,Only clue,Response,200,J!,false,,small")
    state = GameState(title="Test", clues=load_clues_from_text("\n".join(rows)))

    board = state.board("Jeopardy")

    assert len(board) == 6
    assert "Too Small" not in board
    assert all([200, 400, 600, 800, 1000] == [clue["value"] for clue in clues] for clues in board.values())


def test_first_buzz_locks_buzzer():
    state = make_state()
    p1 = state.add_or_update_player("p1", "Sarah")
    p2 = state.add_or_update_player("p2", "Tom")
    state.select_clue(first_regular_clue(state).id)
    state.open_buzzers()

    assert state.buzz(p1.id) is True
    assert state.buzz(p2.id) is False
    assert state.first_buzzer == p1.id
    assert state.buzzer_open is False


def test_multiple_devices_on_same_team_buzz_for_one_player():
    state = make_state()
    team = state.add_or_update_player("team1", "Blue Team")
    state.connect_player(team.id)
    state.connect_player(team.id)
    state.select_clue(first_regular_clue(state).id)
    state.open_buzzers()

    assert state.buzz(team.id) is True
    assert state.first_buzzer == team.id
    assert state.players[team.id].socket_count == 2


def test_buzz_attempt_while_closed_is_ignored():
    state = make_state()
    player = state.add_or_update_player("p1", "Sarah")
    state.select_clue(first_regular_clue(state).id)

    assert state.buzz(player.id) is False
    assert state.first_buzzer is None


def test_incorrect_player_cannot_buzz_same_clue_after_reopen():
    state = make_state()
    p1 = state.add_or_update_player("p1", "Sarah")
    p2 = state.add_or_update_player("p2", "Tom")
    state.select_clue(first_regular_clue(state).id)
    state.open_buzzers()
    state.buzz(p1.id)
    state.mark_incorrect()
    state.open_buzzers()

    assert state.buzz(p1.id) is False
    assert state.buzz(p2.id) is True


def test_incorrect_subtracts_points_and_correct_marks_clue_used():
    state = make_state()
    clue = first_regular_clue(state)
    p1 = state.add_or_update_player("p1", "Sarah")
    p2 = state.add_or_update_player("p2", "Tom")
    state.select_clue(clue.id)
    state.open_buzzers()
    state.buzz(p1.id)
    state.mark_incorrect()
    assert state.players[p1.id].score == -clue.value

    state.open_buzzers()
    state.buzz(p2.id)
    state.mark_correct()
    assert state.players[p2.id].score == clue.value
    assert state.clues[clue.id].used is True


def test_correct_cannot_be_applied_twice_to_same_player():
    state = make_state()
    clue = first_regular_clue(state)
    player = state.add_or_update_player("p1", "Sarah")
    state.select_clue(clue.id)
    state.open_buzzers()
    state.buzz(player.id)
    state.mark_correct()

    with pytest.raises(ValueError):
        state.mark_correct()
    assert state.players[player.id].score == clue.value


def test_incorrect_cannot_be_applied_twice_to_same_player():
    state = make_state()
    clue = first_daily_double(state)
    player = state.add_or_update_player("p1", "Sarah")
    state.select_clue(clue.id)
    state.set_daily_double(player.id, 500)
    state.mark_incorrect()

    with pytest.raises(ValueError):
        state.mark_incorrect()
    assert state.players[player.id].score == -500


def test_player_reconnection_uses_same_id_and_score():
    state = make_state()
    player = state.add_or_update_player("p1", "Sarah")
    state.players[player.id].score = 1200

    same = state.add_or_update_player("p1", "Sarah M")
    assert same.id == player.id
    assert same.score == 1200
    assert same.name == "Sarah M"


def test_daily_double_scoring_uses_wager():
    state = make_state()
    clue = first_daily_double(state)
    player = state.add_or_update_player("p1", "Sarah")
    state.select_clue(clue.id)
    state.set_daily_double(player.id, 1500)
    state.mark_correct()

    assert state.players[player.id].score == 1500
    assert state.clues[clue.id].used is True


def test_daily_double_incorrect_subtracts_wager():
    state = make_state()
    clue = first_daily_double(state)
    player = state.add_or_update_player("p1", "Sarah")
    state.select_clue(clue.id)
    state.set_daily_double(player.id, 700)
    state.mark_incorrect()

    assert state.players[player.id].score == -700
    assert state.clues[clue.id].used is True


def test_final_jeopardy_wager_calculations_and_locks():
    state = make_state()
    p1 = state.add_or_update_player("p1", "Sarah")
    p2 = state.add_or_update_player("p2", "Tom")
    state.players[p1.id].score = 3000
    state.players[p2.id].score = 2500
    state.start_final()
    state.submit_final_wager(p1.id, 1000)
    state.submit_final_wager(p2.id, 500)

    with pytest.raises(ValueError):
        state.submit_final_wager(p1.id, 1200)

    state.reveal_final_clue()
    state.submit_final_answer(p1.id, "Arizona")
    state.submit_final_answer(p2.id, "Nevada")
    state.judge_final(p1.id, True)
    state.judge_final(p2.id, False)

    assert state.players[p1.id].score == 4000
    assert state.players[p2.id].score == 2000

    with pytest.raises(ValueError):
        state.judge_final(p1.id, True)
    assert state.players[p1.id].score == 4000


def test_final_jeopardy_starts_with_category_and_wagers_before_clue_reveal():
    state = make_state()
    player = state.add_or_update_player("p1", "Sarah")

    state.start_final()

    public = state.public_state(player.id)
    assert public["status"] == "final"
    assert public["final_phase"] == "wagers"
    assert public["final_category"]
    assert public["final_wager_submitted"] is False
    assert public["final_answer_submitted"] is False

    state.submit_final_wager(player.id, 500)
    public = state.public_state(player.id)
    assert public["final_wager_submitted"] is True
    assert public["final_phase"] == "wagers"

    state.reveal_final_clue()
    state.submit_final_answer(player.id, "A response")

    public = state.public_state(player.id)
    assert public["final_phase"] == "answers"
    assert public["final_answer_submitted"] is True


def test_final_jeopardy_team_submission_locks_wager_and_response():
    state = make_state()
    team = state.add_or_update_player("team1", "Blue Team")
    state.start_final()

    state.submit_final_wager(team.id, 600)
    with pytest.raises(ValueError):
        state.submit_final_wager(team.id, 800)

    state.reveal_final_clue()
    state.submit_final_answer(team.id, "First response")
    with pytest.raises(ValueError):
        state.submit_final_answer(team.id, "Second response")


def test_final_reveals_only_show_selected_wagers_and_responses_to_display():
    state = make_state()
    player = state.add_or_update_player("p1", "Sarah")
    state.start_final()
    state.submit_final_wager(player.id, 700)
    state.reveal_final_clue()
    state.submit_final_answer(player.id, "A response")

    display = state.display_state("http://127.0.0.1:8000", "/qr")
    assert display["final_reveals"] == []

    state.reveal_final_wager(player.id)
    display = state.display_state("http://127.0.0.1:8000", "/qr")
    assert display["final_reveals"][0]["player"]["name"] == "Sarah"
    assert display["final_reveals"][0]["wager"] == 700
    assert display["final_reveals"][0]["answer"] is None

    state.reveal_final_answer(player.id)
    display = state.display_state("http://127.0.0.1:8000", "/qr")
    assert display["final_reveals"][0]["answer"] == "A response"


def test_player_public_state_does_not_include_answers():
    state = make_state()
    player = state.add_or_update_player("p1", "Sarah")
    clue = first_regular_clue(state)
    state.select_clue(clue.id)

    public = state.public_state(player.id)
    assert "answer" not in public["current_clue"]
    assert "accepted_answers" not in public["current_clue"]
    host = state.host_state("http://127.0.0.1:8000", "/qr")
    assert host["current_clue"]["answer"] == clue.answer


def test_display_answer_only_reveals_to_display_and_host_payloads():
    state = make_state()
    player = state.add_or_update_player("p1", "Sarah")
    clue = first_regular_clue(state)
    state.select_clue(clue.id)
    state.display_answer()

    public = state.public_state(player.id)
    display = state.display_state("http://127.0.0.1:8000", "/qr")
    host = state.host_state("http://127.0.0.1:8000", "/qr")

    assert "revealed_answer" not in public
    assert display["revealed_answer"] == clue.answer
    assert host["revealed_answer"] == clue.answer
