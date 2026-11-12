"""
Бэкенд мини-аппа. Работает ВНУТРИ сервиса бота (bot.py) и использует ту же базу users.db
и ту же таблицу users(user_id, stars), поэтому баланс общий с ботом.
Запускается из bot.py (см. вставку в конце bot.py), отдельно запускать не нужно.
Также отдаёт index.html по адресу /index.html.
"""
import os, time, math, hmac, hashlib, json, secrets, sqlite3, asyncio
from urllib.parse import parse_qsl
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")  # bot.py подставляет свой токен: server.BOT_TOKEN = BOT_TOKEN
DB_PATH = os.environ.get("DB_PATH", "users.db")
DB = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False, isolation_level=None)
DB.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    stars REAL DEFAULT 0.0,
    referrer_id INTEGER DEFAULT NULL,
    ref_reward_given INTEGER DEFAULT 0
)""")
HERE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI()
# В проде замени "*" на домен, где лежит index.html
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
rnd = secrets.SystemRandom()


class Err(Exception):
    pass


@app.exception_handler(Err)
async def _err(_, e):
    return JSONResponse({"error": str(e)}, status_code=400)


# ---------- авторизация Telegram ----------
def auth(init_data: str) -> int:
    d = dict(parse_qsl(init_data, keep_blank_values=True))
    h = d.pop("hash", "")
    check = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    if not h or not hmac.compare_digest(hmac.new(key, check.encode(), hashlib.sha256).hexdigest(), h):
        raise Err("Неверная подпись Telegram")
    if time.time() - int(d.get("auth_date", 0)) > 86400:
        raise Err("Сессия устарела, перезапусти апп")
    return json.loads(d["user"])["id"]


# ---------- баланс ----------
def bal(uid):
    DB.execute("INSERT OR IGNORE INTO users(user_id, stars) VALUES(?, 0)", (uid,))
    return round(DB.execute("SELECT stars FROM users WHERE user_id=?", (uid,)).fetchone()[0], 2)


def take(uid, amount):
    if not isinstance(amount, int) or amount < 1:
        raise Err("Минимальная ставка 1 ⭐")
    bal(uid)
    if DB.execute("UPDATE users SET stars=stars-? WHERE user_id=? AND stars>=?", (amount, uid, amount)).rowcount == 0:
        raise Err("Недостаточно звёзд")


def give(uid, amount):
    if amount > 0:
        DB.execute("UPDATE users SET stars=stars+? WHERE user_id=?", (amount, uid))


# ---------- краш: общие раунды ----------
K = 0.00012
BET_MS, PAUSE_MS = 6000, 3500
R, HIST = {}, []


def growth(ms):
    return math.floor(100 * math.exp(K * ms)) / 100


def new_round():
    now = time.time() * 1000
    cp = min(1000, max(1, math.floor(97 / (1 - rnd.random())) / 100))
    bet_end = now + BET_MS
    crash_at = bet_end + math.log(cp) / K
    R.clear()
    R.update(cp=cp, bet_end=bet_end, crash_at=crash_at, next_at=crash_at + PAUSE_MS, bets={})


def phase_mult(now):
    if now < R["bet_end"]:
        return "bet", 1.0
    if now < R["crash_at"]:
        return "fly", growth(now - R["bet_end"])
    return "crash", R["cp"]


def crash_tick():
    now = time.time() * 1000
    if not R or now >= R["next_at"]:
        if R:
            HIST.append(R["cp"])
        new_round()
    ph, m = phase_mult(now)
    if ph != "bet":
        for uid, b in R["bets"].items():
            if b["win"] is None and b["auto"] and m >= b["auto"]:
                b["win"] = math.floor(b["amount"] * b["auto"])
                give(uid, b["win"])
    return ph, m, now


@app.on_event("startup")
async def _start():
    async def loop():
        while True:
            crash_tick()
            await asyncio.sleep(0.05)
    asyncio.create_task(loop())


# ---------- сапёр / рулетка ----------
MG = {}
RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


MINES_MAX_X = 20  # потолок множителя в сапёре


def mines_mult(n, o):
    m = 0.97
    for k in range(o):
        m *= (25 - k) / (25 - n - k)
    return min(MINES_MAX_X, math.floor(m * 100) / 100)


# ---------- сайт ----------
@app.get("/")
@app.get("/index.html")
async def index():
    return FileResponse(os.path.join(HERE, "index.html"))


# ---------- API ----------
@app.post("/{method}")
async def api(method: str, req: Request):
    uid = auth(req.headers.get("X-Init-Data", ""))
    try:
        p = await req.json()
    except Exception:
        p = {}

    if method == "balance":
        return {"balance": bal(uid)}

    if method == "crash_state":
        ph, m, now = crash_tick()
        return {"phase": ph, "mult": m, "left": max(0, R["bet_end"] - now), "hist": HIST[-10:],
                "bet": R["bets"].get(uid), "balance": bal(uid)}

    if method == "crash_bet":
        ph, _, _ = crash_tick()
        if ph != "bet":
            raise Err("Приём ставок закрыт")
        if uid in R["bets"]:
            raise Err("Ставка уже сделана")
        amount = p.get("bet")
        take(uid, amount)
        a = p.get("auto")
        R["bets"][uid] = {"amount": amount, "auto": float(a) if isinstance(a, (int, float)) and a >= 1.1 else None, "win": None}
        return {"balance": bal(uid)}

    if method == "crash_cashout":
        ph, m, _ = crash_tick()
        b = R["bets"].get(uid)
        if ph != "fly" or not b or b["win"] is not None:
            raise Err("Сейчас нельзя забрать")
        b["win"] = math.floor(b["amount"] * m)
        give(uid, b["win"])
        return {"win": b["win"], "balance": bal(uid)}

    if method == "mines_state":
        g = MG.get(uid)
        if not g or g["done"]:
            return {"active": False}
        o = len(g["open"])
        return {"active": True, "id": 1, "bet": g["bet"], "mines": g["n"], "opened": sorted(g["open"]),
                "mult": mines_mult(g["n"], o) if o else 1}

    if method == "mines_start":
        if uid in MG and not MG[uid]["done"]:
            raise Err("Игра уже идёт")
        n = p.get("mines")
        if n not in (1, 3, 5, 10, 24):
            raise Err("Неверное число мин")
        take(uid, p.get("bet"))
        MG[uid] = {"bet": p["bet"], "n": n, "set": set(rnd.sample(range(25), n)), "open": set(), "done": False}
        return {"id": 1, "balance": bal(uid)}

    if method in ("mines_open", "mines_cash"):
        g = MG.get(uid)
        if not g or g["done"]:
            raise Err("Нет активной игры")
        if method == "mines_cash":
            if not g["open"]:
                raise Err("Сначала открой клетку")
            g["done"] = True
            mult = mines_mult(g["n"], len(g["open"]))
            win = math.floor(g["bet"] * mult)
            give(uid, win)
            return {"win": win, "mult": mult, "mines": sorted(g["set"]), "balance": bal(uid)}
        i = p.get("i")
        if not isinstance(i, int) or not 0 <= i < 25 or i in g["open"]:
            raise Err("Недопустимый ход")
        if i in g["set"]:
            g["done"] = True
            return {"safe": False, "mines": sorted(g["set"]), "balance": bal(uid)}
        g["open"].add(i)
        mult = mines_mult(g["n"], len(g["open"]))
        if len(g["open"]) == 25 - g["n"] or mult >= MINES_MAX_X:
            g["done"] = True
            win = math.floor(g["bet"] * mult)
            give(uid, win)
            return {"safe": True, "mult": mult, "auto": True, "win": win, "mines": sorted(g["set"]), "balance": bal(uid)}
        return {"safe": True, "mult": mult}

    if method == "roul_spin":
        t, num = p.get("type"), p.get("num")
        if t not in ("red", "black", "even", "odd", "num"):
            raise Err("Неверная ставка")
        if t == "num" and not (isinstance(num, int) and 0 <= num <= 36):
            raise Err("Число от 0 до 36")
        take(uid, p.get("bet"))
        n = rnd.randrange(37)
        red = n in RED
        ok = {"red": red, "black": n != 0 and not red, "even": n != 0 and n % 2 == 0,
              "odd": n % 2 == 1, "num": n == num}[t]
        pay = p["bet"] * (36 if t == "num" else 2) if ok else 0
        give(uid, pay)
        return {"n": n, "color": "g" if n == 0 else "r" if red else "b", "pay": pay, "balance": bal(uid)}

    raise Err("Неизвестный метод")
