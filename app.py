from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
import io
import json
import os
from pathlib import Path
import secrets
from time import monotonic
from typing import Any

import qrcode
import uvicorn
from fastapi import Cookie, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from game_state import FINAL_ROUND, GameState, load_clues, load_clues_from_text, local_ip


ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.json"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


CONFIG = load_config()
DEFAULT_SOURCE_CLUES = load_clues(ROOT / CONFIG.get("question_csv", "data/jeopardy_clue_bank.csv"))
HOST_PIN = str(CONFIG.get("host_pin", "2468"))
HOST_COOKIE = "jeopardy_host_auth"
MAX_CLUE_UPLOAD_BYTES = 2_000_000

app = FastAPI(title=CONFIG.get("game_title", "Jeopardy Game"))
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


class ConnectionManager:
    def __init__(self, room: GameRoom) -> None:
        self.room = room
        self.hosts: set[WebSocket] = set()
        self.displays: set[WebSocket] = set()
        self.players: dict[str, set[WebSocket]] = {}
        self.lock = asyncio.Lock()
        self.broadcast_lock = asyncio.Lock()
        self.timer_handle: asyncio.TimerHandle | None = None
        self.scheduled_deadline: float | None = None

    async def add(self, role: str, websocket: WebSocket, player_id: str | None = None) -> None:
        await websocket.accept()
        async with self.lock:
            if role == "host":
                self.hosts.add(websocket)
            elif role == "display":
                self.displays.add(websocket)
            elif player_id:
                self.players.setdefault(player_id, set()).add(websocket)
                self.room.state.connect_player(player_id)

    async def remove(self, role: str, websocket: WebSocket, player_id: str | None = None) -> None:
        async with self.lock:
            if role == "host":
                self.hosts.discard(websocket)
            elif role == "display":
                self.displays.discard(websocket)
            elif player_id:
                sockets = self.players.get(player_id)
                if sockets:
                    sockets.discard(websocket)
                    if not sockets:
                        self.players.pop(player_id, None)
                self.room.state.disconnect_player(player_id)

    async def broadcast(self) -> None:
        self.schedule_timer()
        async with self.broadcast_lock:
            await self.send_state()

    def schedule_timer(self) -> None:
        deadline = self.room.state.timer_deadline
        if deadline == self.scheduled_deadline:
            return
        if self.timer_handle:
            self.timer_handle.cancel()
        self.timer_handle = None
        self.scheduled_deadline = deadline
        if deadline is not None:
            self.timer_handle = asyncio.get_running_loop().call_later(
                max(0, deadline - monotonic()), self.timer_elapsed
            )

    def timer_elapsed(self) -> None:
        self.scheduled_deadline = None
        self.timer_handle = None
        if self.room.state.expire_timer():
            asyncio.create_task(self.broadcast())
        else:
            self.schedule_timer()

    async def send_state(self) -> None:
        join_url = get_join_url(self.room.code)
        qr_url = f"/g/{self.room.code}/qr"
        messages: list[tuple[WebSocket, dict[str, Any]]] = []
        for ws in list(self.hosts):
            messages.append((ws, {"type": "state", "state": self.room.state.host_state(join_url, qr_url)}))
        for ws in list(self.displays):
            messages.append((ws, {"type": "state", "state": self.room.state.display_state(join_url, qr_url)}))
        for pid, sockets in list(self.players.items()):
            for ws in list(sockets):
                messages.append((ws, {"type": "state", "state": self.room.state.public_state(pid)}))
        stale: list[tuple[str, WebSocket, str | None]] = []
        for ws, payload in messages:
            try:
                await ws.send_json(payload)
            except RuntimeError:
                stale.append(("unknown", ws, None))
        for _, ws, _ in stale:
            self.hosts.discard(ws)
            self.displays.discard(ws)
            for sockets in self.players.values():
                sockets.discard(ws)


@dataclass
class GameRoom:
    code: str
    state: GameState
    host_token: str | None = None
    manager: ConnectionManager = field(init=False)

    def __post_init__(self) -> None:
        self.manager = ConnectionManager(self)


ROOMS: dict[str, GameRoom] = {}


def create_state() -> GameState:
    return GameState(
        title=CONFIG.get("game_title", "Jeopardy Game"),
        incorrect_subtracts_points=bool(CONFIG.get("incorrect_subtracts_points", True)),
        reopen_after_incorrect=bool(CONFIG.get("reopen_after_incorrect", True)),
        maximum_players=int(CONFIG.get("maximum_players", 24)),
        sound_enabled=bool(CONFIG.get("sound_enabled", True)),
        clues=DEFAULT_SOURCE_CLUES,
    )


def new_game_code() -> str:
    while True:
        code = secrets.token_urlsafe(5).replace("_", "").replace("-", "")[:7]
        if code and code not in ROOMS:
            return code


def create_room() -> GameRoom:
    code = new_game_code()
    room = GameRoom(code=code, state=create_state())
    ROOMS[code] = room
    return room


def get_room(game_code: str) -> GameRoom:
    room = ROOMS.get(game_code)
    if not room:
        raise HTTPException(status_code=404, detail="Unknown game.")
    return room


DEFAULT_ROOM = create_room()
STATE = DEFAULT_ROOM.state
MANAGER = DEFAULT_ROOM.manager


def get_join_url(game_code: str) -> str:
    base_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        base_url = f"http://{local_ip()}:8000"
    return f"{base_url}/g/{game_code}"


def host_cookie_name(game_code: str) -> str:
    return f"{HOST_COOKIE}_{game_code}"


def check_host(request: Request, room: GameRoom) -> bool:
    return bool(room.host_token and request.cookies.get(host_cookie_name(room.code)) == room.host_token)


def require_host_cookie(request: Request, room: GameRoom) -> None:
    if not check_host(request, room):
        raise HTTPException(status_code=403, detail="Host PIN required.")


@app.get("/", response_class=HTMLResponse)
async def index() -> RedirectResponse:
    return RedirectResponse("/display", status_code=303)


@app.get("/display", response_class=HTMLResponse)
async def legacy_display_page() -> RedirectResponse:
    return RedirectResponse(f"/g/{create_room().code}/display", status_code=303)


@app.get("/host", response_class=HTMLResponse)
async def legacy_host_page() -> RedirectResponse:
    return RedirectResponse(f"/g/{DEFAULT_ROOM.code}/host", status_code=303)


@app.get("/g/{game_code}", response_class=HTMLResponse)
async def game_landing(request: Request, game_code: str) -> HTMLResponse:
    room = get_room(game_code)
    return templates.TemplateResponse(
        "landing.html",
        {"request": request, "title": room.state.title, "game_code": game_code},
    )


@app.get("/g/{game_code}/player", response_class=HTMLResponse)
async def player_page(request: Request, game_code: str) -> HTMLResponse:
    room = get_room(game_code)
    return templates.TemplateResponse(
        "player.html",
        {"request": request, "title": room.state.title, "game_code": game_code},
    )


@app.get("/g/{game_code}/display", response_class=HTMLResponse)
async def display_page(request: Request, game_code: str) -> HTMLResponse:
    room = get_room(game_code)
    return templates.TemplateResponse(
        "display.html",
        {
            "request": request,
            "title": room.state.title,
            "join_url": get_join_url(game_code),
            "game_code": game_code,
        },
    )


@app.get("/g/{game_code}/host", response_class=HTMLResponse)
async def host_page(request: Request, game_code: str) -> HTMLResponse:
    room = get_room(game_code)
    return templates.TemplateResponse(
        "host.html",
        {
            "request": request,
            "title": room.state.title,
            "authenticated": check_host(request, room),
            "game_code": game_code,
            "host_claimed": bool(room.host_token),
            "game_selection": room.state.current_game_selection,
            "game_options": room.state.game_options,
        },
    )


@app.post("/g/{game_code}/host/login")
async def host_login(request: Request, game_code: str) -> Response:
    room = get_room(game_code)
    form = await request.form()
    if str(form.get("pin", "")) != HOST_PIN:
        return templates.TemplateResponse(
            "host.html",
            {
                "request": request,
                "title": room.state.title,
                "authenticated": False,
                "host_claimed": bool(room.host_token),
                "game_code": game_code,
                "game_selection": room.state.current_game_selection,
                "game_options": room.state.game_options,
                "error": "Incorrect PIN.",
            },
            status_code=401,
        )
    if room.host_token and not check_host(request, room):
        return templates.TemplateResponse(
            "host.html",
            {
                "request": request,
                "title": room.state.title,
                "authenticated": False,
                "host_claimed": True,
                "game_code": game_code,
                "game_selection": room.state.current_game_selection,
                "game_options": room.state.game_options,
                "error": "This game already has a host.",
            },
            status_code=409,
        )
    room.host_token = room.host_token or secrets.token_urlsafe(24)
    response = RedirectResponse(f"/g/{game_code}/host", status_code=303)
    response.set_cookie(host_cookie_name(game_code), room.host_token, httponly=True, samesite="strict")
    return response


@app.get("/qr")
async def legacy_qr() -> Response:
    return await qr(DEFAULT_ROOM.code)


@app.get("/g/{game_code}/qr")
async def qr(game_code: str) -> Response:
    get_room(game_code)
    image = qrcode.make(get_join_url(game_code))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png")


@app.get("/api/state")
async def legacy_api_state() -> JSONResponse:
    return await api_state(DEFAULT_ROOM.code)


@app.post("/host/clues")
async def legacy_host_clue_upload(request: Request) -> Response:
    return await host_clue_upload(DEFAULT_ROOM.code, request)


@app.get("/g/{game_code}/api/state")
async def api_state(game_code: str) -> JSONResponse:
    room = get_room(game_code)
    return JSONResponse(room.state.display_state(get_join_url(game_code), f"/g/{game_code}/qr"))


@app.post("/g/{game_code}/host/clues")
async def host_clue_upload(
    game_code: str,
    request: Request,
) -> Response:
    room = get_room(game_code)
    require_host_cookie(request, room)
    raw_content_length = request.headers.get("content-length")
    try:
        content_length = int(raw_content_length) if raw_content_length else 0
    except ValueError:
        content_length = 0
    if content_length > MAX_CLUE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="CSV file is too large.")
    contents = await request.body()
    if len(contents) > MAX_CLUE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="CSV file is too large.")
    try:
        csv_text = csv_text_from_upload(contents, request.headers.get("content-type", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        clues = load_clues_from_text(csv_text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    room.state.load_source(clues)
    await room.manager.broadcast()
    if "text/html" in request.headers.get("accept", ""):
        return RedirectResponse(f"/g/{game_code}/host", status_code=303)
    return JSONResponse({
        "clue_count": len(clues),
        "board_clue_count": sum(1 for clue in clues.values() if clue.round != FINAL_ROUND),
        "final_clue_count": sum(1 for clue in clues.values() if clue.round == FINAL_ROUND),
    })


def csv_text_from_upload(contents: bytes, content_type: str) -> str:
    if content_type.lower().startswith("multipart/form-data"):
        return csv_text_from_multipart(contents, content_type)
    try:
        return contents.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV file must be UTF-8 text.") from exc


def csv_text_from_multipart(contents: bytes, content_type: str) -> str:
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii") + contents
    )
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        if disposition != "form-data":
            continue
        if part.get_param("name", header="content-disposition") != "file":
            continue
        payload = part.get_payload(decode=True) or b""
        try:
            return payload.decode(part.get_content_charset() or "utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV file must be UTF-8 text.") from exc
    raise ValueError("CSV upload did not include a file.")


async def websocket_room(websocket: WebSocket, game_code: str) -> GameRoom | None:
    room = ROOMS.get(game_code)
    if room is None:
        # A browser cannot read the status of a rejected WebSocket handshake.
        await websocket.accept()
        await websocket.close(code=4004, reason="Game expired")
    return room


@app.websocket("/g/{game_code}/ws/player")
async def ws_player(websocket: WebSocket, game_code: str) -> None:
    room = await websocket_room(websocket, game_code)
    if room is None:
        return
    player_id = websocket.query_params.get("player_id")
    name = websocket.query_params.get("name", "")
    try:
        player = room.state.add_or_update_player(player_id, name)
    except ValueError as exc:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1008)
        return
    await room.manager.add("player", websocket, player.id)
    await websocket.send_json({"type": "joined", "player_id": player.id})
    await room.manager.broadcast()
    try:
        while True:
            message = await websocket.receive_json()
            await handle_player_message(room, player.id, message)
    except WebSocketDisconnect:
        await room.manager.remove("player", websocket, player.id)
        await room.manager.broadcast()


@app.websocket("/g/{game_code}/ws/display")
async def ws_display(websocket: WebSocket, game_code: str) -> None:
    room = await websocket_room(websocket, game_code)
    if room is None:
        return
    await room.manager.add("display", websocket)
    await room.manager.broadcast()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await room.manager.remove("display", websocket)


@app.websocket("/g/{game_code}/ws/host")
async def ws_host(websocket: WebSocket, game_code: str) -> None:
    room = await websocket_room(websocket, game_code)
    if room is None:
        return
    if not room.host_token or websocket.cookies.get(host_cookie_name(game_code)) != room.host_token:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "Host PIN required."})
        await websocket.close(code=1008)
        return
    await room.manager.add("host", websocket)
    await room.manager.broadcast()
    try:
        while True:
            message = await websocket.receive_json()
            await handle_host_message(room, message)
    except WebSocketDisconnect:
        await room.manager.remove("host", websocket)


async def handle_player_message(room: GameRoom, player_id: str, message: dict[str, Any]) -> None:
    action = message.get("action")
    try:
        if action == "buzz":
            room.state.buzz(player_id)
        elif action == "select_clue":
            room.state.pick_clue(str(message.get("clue_id")), message.get("board_number"), player_id)
        elif action == "final_wager":
            room.state.submit_final_wager(player_id, int(message.get("wager", 0)))
        elif action == "final_answer":
            room.state.submit_final_answer(player_id, str(message.get("answer", "")))
    except ValueError:
        pass
    await room.manager.broadcast()


async def handle_host_message(room: GameRoom, message: dict[str, Any]) -> None:
    action = message.get("action")
    try:
        if action == "start":
            room.state.start_game()
        elif action == "set_game_selection":
            room.state.set_game_selection(str(message.get("selection", "random")))
        elif action == "set_round":
            room.state.set_round(str(message.get("round")))
        elif action == "select_clue":
            room.state.pick_clue(str(message.get("clue_id")), message.get("board_number"))
        elif action == "reveal_daily_double":
            room.state.reveal_daily_double()
        elif action == "daily_double_setup":
            player_id = message.get("player_id") or None
            wager = int(message.get("wager", 0)) if str(message.get("wager", "")).strip() else None
            room.state.set_daily_double(player_id, wager)
        elif action == "open_buzzers":
            room.state.open_buzzers()
        elif action == "close_buzzers":
            room.state.close_buzzers()
        elif action in {"correct", "incorrect"}:
            if not room.state.daily_double_active and message.get("response_number") != room.state.response_number:
                raise ValueError("This response is no longer active.")
            mark = room.state.mark_correct if action == "correct" else room.state.mark_incorrect
            mark(_optional_int(message.get("wager")))
        elif action == "display_answer":
            room.state.display_answer()
        elif action == "close_clue":
            room.state.close_clue(mark_used=bool(message.get("mark_used", True)))
        elif action == "return_board":
            room.state.return_to_board()
        elif action == "scoreboard":
            room.state.show_scoreboard()
        elif action == "end":
            room.state.show_scoreboard(final=True)
        elif action == "reset":
            room.state.reset()
        elif action == "adjust_score":
            room.state.adjust_score(str(message.get("player_id")), int(message.get("delta", 0)))
        elif action == "set_score":
            room.state.set_score(str(message.get("player_id")), int(message.get("score", 0)))
        elif action == "remove_player":
            room.state.remove_player(str(message.get("player_id")))
        elif action == "start_final":
            room.state.start_final()
        elif action == "reveal_final":
            room.state.reveal_final_clue()
        elif action == "judge_final":
            room.state.judge_final(str(message.get("player_id")), bool(message.get("correct")))
        elif action == "reveal_final_wager":
            room.state.reveal_final_wager(str(message.get("player_id")))
        elif action == "reveal_final_answer":
            room.state.reveal_final_answer(str(message.get("player_id")))
        elif action == "reset_final_player":
            room.state.reset_final_player(str(message.get("player_id")), str(message.get("field")))
    except (KeyError, TypeError, ValueError) as exc:
        for ws in list(room.manager.hosts):
            await ws.send_json({"type": "error", "message": str(exc)})
    await room.manager.broadcast()


def _optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


if __name__ == "__main__":
    url = get_join_url(DEFAULT_ROOM.code)
    print(f"\n{STATE.title}")
    print(f"Player join URL: {url}")
    print(f"Host controls:    {url}/host")
    print(f"Main display:     {url}/display")
    print("New game display: http://127.0.0.1:8000/display\n")
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
