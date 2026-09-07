from fastapi.testclient import TestClient

import app


CUSTOM_CSV = (
    "round,category,value,clue,answer,accepted_answers,daily_double\n"
    "Jeopardy,Custom Cat,100,Custom clue?,Custom response,,false\n"
)
GAME_ID_CSV = (
    "category,clue,correct_response,value,round,daily_double,game_id,clue_id\n"
    "Game One,One,One,200,J!,false,1,1\n"
    "Game Two,Two,Two,200,J!,false,2,1\n"
)


def authenticated_client() -> TestClient:
    client = TestClient(app.app)
    return client


def create_authenticated_room(client: TestClient) -> str:
    response = client.get("/display", follow_redirects=False)
    game_code = response.headers["location"].split("/")[2]
    login = client.post(
        f"/g/{game_code}/host/login",
        data={"pin": app.HOST_PIN},
        follow_redirects=False,
    )
    assert login.status_code == 303
    return game_code


def test_host_clue_upload_accepts_raw_csv_body():
    client = authenticated_client()
    game_code = create_authenticated_room(client)

    response = client.post(f"/g/{game_code}/host/clues", content=CUSTOM_CSV, headers={"content-type": "text/csv"})

    assert response.status_code == 200
    assert response.json()["clue_count"] == 1
    assert list(client.get(f"/g/{game_code}/api/state").json()["board"]) == ["Custom Cat"]


def test_host_clue_upload_accepts_multipart_csv_body():
    client = authenticated_client()
    game_code = create_authenticated_room(client)

    response = client.post(f"/g/{game_code}/host/clues", files={"file": ("custom.csv", CUSTOM_CSV, "text/csv")})

    assert response.status_code == 200
    assert response.json()["clue_count"] == 1
    assert list(client.get(f"/g/{game_code}/api/state").json()["board"]) == ["Custom Cat"]


def test_host_clue_upload_redirects_for_plain_html_form_submission():
    client = authenticated_client()
    game_code = create_authenticated_room(client)

    response = client.post(
        f"/g/{game_code}/host/clues",
        files={"file": ("custom.csv", CUSTOM_CSV, "text/csv")},
        headers={"accept": "text/html"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/g/{game_code}/host"
    assert list(client.get(f"/g/{game_code}/api/state").json()["board"]) == ["Custom Cat"]


def test_host_page_renders_loaded_game_id_options():
    client = authenticated_client()
    game_code = create_authenticated_room(client)
    client.post(f"/g/{game_code}/host/clues", content=GAME_ID_CSV, headers={"content-type": "text/csv"})

    response = client.get(f"/g/{game_code}/host")

    assert response.status_code == 200
    assert '<option value="1"' in response.text
    assert '<option value="2"' in response.text


def test_display_creates_unique_game_rooms_and_landing_has_role_choices():
    client = authenticated_client()

    first = client.get("/display", follow_redirects=False).headers["location"]
    second = client.get("/display", follow_redirects=False).headers["location"]

    assert first != second
    assert first.startswith("/g/")
    response = client.get(first.removesuffix("/display"))
    assert response.status_code == 200
    assert "Join as Player" in response.text
    assert "Host This Game" in response.text


def test_root_redirects_to_display():
    client = authenticated_client()

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/display"


def test_public_base_url_is_used_for_join_urls(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://jeopardy.example.com/")

    assert app.get_join_url("ABC123") == "https://jeopardy.example.com/g/ABC123"


def test_only_one_host_can_claim_a_game():
    first_client = authenticated_client()
    game_code = create_authenticated_room(first_client)
    second_client = authenticated_client()

    response = second_client.post(
        f"/g/{game_code}/host/login",
        data={"pin": app.HOST_PIN},
        follow_redirects=False,
    )

    assert response.status_code == 409
