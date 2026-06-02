import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import psycopg2
import os
import json
from datetime import date, datetime

TOKEN = "vk1.a.HC0dIDDvX_S11Rvu0v_z8XIuv9uzPIPqS_O9Xu4dMF_T_6FEYBqvkK7jqFiNrntG65esMnAzvdgNa08eJ3Cqp2e3BMmFXzVjrmjwoTvtCou-1XZCPaaE46giu1s1QPz7iRHbfjdAYtdrDkFFA6X1RGHZcbjlhMdrethcP4INDYkw6hd_ryR0l-PjnlTwGKQJARfm0jdJX9_VT2KiWAGYfA"

GROUP_ID = 239267601

# ─── Состояния ожидания ввода ──────────────────────────────
# { uid: { "target_id": ..., "field": ..., "nick": ... } }
pending = {}

# ─── Проверка владельца группы ────────────────────────────
def is_group_creator(vk, user_id):
    try:
        members = vk.groups.getMembers(group_id=GROUP_ID, filter="managers", fields="role")
        for m in members.get("items", []):
            if m["id"] == user_id and m.get("role") in ("creator", "owner"):
                return True
    except Exception as e:
        print(f"[is_group_creator] ошибка: {e}")
    return False

# ─── База данных ───────────────────────────────────────────
def get_conn():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise Exception("DATABASE_URL не найден в переменных окружения")
    return psycopg2.connect(db_url)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        vk_id BIGINT PRIMARY KEY,
        nick TEXT,
        rank TEXT DEFAULT 'Участник',
        admin_level REAL DEFAULT 0,
        warns INTEGER DEFAULT 0,
        max_warns INTEGER DEFAULT 3,
        reprimands INTEGER DEFAULT 0,
        max_reprimands INTEGER DEFAULT 2,
        date_appointed TEXT,
        date_promoted TEXT,
        points INTEGER DEFAULT 0,
        inactives INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        vk_id BIGINT PRIMARY KEY
    )''')
    conn.commit()
    conn.close()

def get_admins():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT vk_id FROM admins")
    rows = c.fetchall()
    conn.close()
    return {row[0] for row in rows}

def add_admin_db(vk_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO admins (vk_id) VALUES (%s) ON CONFLICT DO NOTHING", (vk_id,))
    conn.commit()
    conn.close()

def remove_admin_db(vk_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE vk_id=%s", (vk_id,))
    conn.commit()
    conn.close()

def get_user(vk_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE vk_id=%s", (vk_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_user_by_nick(nick):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE LOWER(nick)=LOWER(%s)", (nick,))
    row = c.fetchone()
    conn.close()
    return row

def add_user(vk_id, nick, date_app=None, date_prom=None):
    conn = get_conn()
    c = conn.cursor()
    today = date.today().strftime("%d.%m.%Y")
    app = date_app if date_app else today
    prom = date_prom if date_prom else today
    c.execute("""INSERT INTO users (vk_id, nick, date_appointed, date_promoted)
                 VALUES (%s, %s, %s, %s)
                 ON CONFLICT (vk_id) DO NOTHING""",
              (vk_id, nick, app, prom))
    conn.commit()
    conn.close()

def update_field(vk_id, field, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field}=%s WHERE vk_id=%s", (value, vk_id))
    conn.commit()
    conn.close()

def get_all_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT vk_id, nick, rank, admin_level, warns, reprimands, points FROM users ORDER BY points DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def resolve_target(vk, target_raw):
    if target_raw.startswith("@") or target_raw.startswith("["):
        screen_name = target_raw.strip("@[]").split("|")[0]
        try:
            result = vk.utils.resolveScreenName(screen_name=screen_name)
            if not result or result.get("type") != "user":
                return None
            return result["object_id"]
        except:
            return None
    else:
        try:
            return int(target_raw)
        except ValueError:
            return None

def find_user(vk, query):
    if not query.startswith("@") and not query.startswith("["):
        try:
            int(query)
        except ValueError:
            row = get_user_by_nick(query)
            if row:
                return row
    target_id = resolve_target(vk, query)
    if target_id:
        return get_user(target_id)
    return None

# ─── Форматирование статистики ─────────────────────────────
def format_stats(row):
    (vk_id, nick, rank, admin_level, warns, max_warns,
     reprimands, max_reprimands, date_app, date_prom, points, inactives) = row

    try:
        d = datetime.strptime(date_prom, "%d.%m.%Y")
        total_days = (datetime.today() - d).days - 1
        clean_days = total_days - inactives
        if total_days < 0: total_days = 0
        if clean_days < 0: clean_days = 0
        days_str = f"{clean_days} ({total_days})"
    except:
        days_str = "0 (0)"

    return (
        f"📊 Статистика сотрудника:\n\n"
        f"👤 Ник: [id{vk_id}|{nick}]\n"
        f"🎖 Должность: {rank}\n"
        f"⭐ Уровень прав: {admin_level}\n\n"
        f"⚠️ Выговоры: {warns}/{max_warns}\n"
        f"🔔 Предупреждения: {reprimands}/{max_reprimands}\n\n"
        f"📅 Дата назначения: {date_app}\n"
        f"📅 Дата повышения: {date_prom}\n"
        f"⏳ Дней после повышения: {days_str}\n\n"
        f"🏆 Баллы: {points} баллов\n"
        f"😴 Неактивы: {inactives}"
    )

# ─── Клавиатура редактирования ─────────────────────────────
def make_edit_keyboard(target_id, row):
    (vk_id, nick, rank, admin_level, warns, max_warns,
     reprimands, max_reprimands, date_app, date_prom, points, inactives) = row

    def btn(label, payload, color="secondary"):
        return {
            "action": {
                "type": "text",
                "label": label,
                "payload": json.dumps(payload)
            },
            "color": color
        }

    keyboard = {
        "one_time": False,
        "inline": False,
        "buttons": [
            # Ряд 1 — Выговоры
            [
                btn(f"⚠️ Выговор +1 ({warns}/{max_warns})", {"action": "inc", "field": "warns", "target": target_id}, "negative"),
                btn(f"⚠️ Выговор -1", {"action": "dec", "field": "warns", "target": target_id}, "positive"),
            ],
            # Ряд 2 — Предупреждения
            [
                btn(f"🔔 Предупр. +1 ({reprimands}/{max_reprimands})", {"action": "inc", "field": "reprimands", "target": target_id}, "negative"),
                btn(f"🔔 Предупр. -1", {"action": "dec", "field": "reprimands", "target": target_id}, "positive"),
            ],
            # Ряд 3 — Баллы
            [
                btn(f"🏆 Балл +1 ({points})", {"action": "inc", "field": "points", "target": target_id}, "positive"),
                btn(f"🏆 Балл -1", {"action": "dec", "field": "points", "target": target_id}, "negative"),
            ],
            # Ряд 4 — Неактивы
            [
                btn(f"😴 Неактив +1 ({inactives})", {"action": "inc", "field": "inactives", "target": target_id}, "negative"),
                btn(f"😴 Неактив -1", {"action": "dec", "field": "inactives", "target": target_id}, "positive"),
            ],
            # Ряд 5 — Дата повышения + Закрыть
            [
                btn("📅 Повышение = сегодня", {"action": "promote", "target": target_id}, "primary"),
                btn("❌ Закрыть меню", {"action": "close"}, "secondary"),
            ],
            # Ряд 6 — Ввод вручную
            [
                btn("✏️ Ввести значение вручную", {"action": "manual", "target": target_id}, "primary"),
            ],
        ]
    }
    return json.dumps(keyboard, ensure_ascii=False)

def make_manual_keyboard(target_id):
    """Клавиатура выбора поля для ручного ввода"""
    def btn(label, field):
        return {
            "action": {
                "type": "text",
                "label": label,
                "payload": json.dumps({"action": "set_field", "field": field, "target": target_id})
            },
            "color": "primary"
        }

    keyboard = {
        "one_time": False,
        "inline": False,
        "buttons": [
            [btn("⚠️ Выговоры", "warns"), btn("🔔 Предупреждения", "reprimands")],
            [btn("🏆 Баллы", "points"), btn("😴 Неактивы", "inactives")],
            [btn("⭐ Уровень прав", "admin_level"), btn("🎖 Должность", "rank")],
            [btn("📅 Дата повышения", "date_promoted"), btn("📅 Дата назначения", "date_appointed")],
            [{
                "action": {
                    "type": "text",
                    "label": "◀️ Назад",
                    "payload": json.dumps({"action": "back", "target": target_id})
                },
                "color": "secondary"
            }]
        ]
    }
    return json.dumps(keyboard, ensure_ascii=False)

def empty_keyboard():
    return json.dumps({"buttons": [], "one_time": True})

# ─── Отправка сообщений ────────────────────────────────────
def send(vk, user_id, message, keyboard=None):
    params = {
        "user_id": user_id,
        "message": message,
        "random_id": 0
    }
    if keyboard:
        params["keyboard"] = keyboard
    vk.messages.send(**params)

def send_edit_menu(vk, uid, target_id):
    row = get_user(target_id)
    if not row:
        send(vk, uid, "❌ Пользователь не найден в базе")
        return
    kb = make_edit_keyboard(target_id, row)
    send(vk, uid, format_stats(row) + "\n\n👇 Управление:", keyboard=kb)

# ─── Обработка payload (кнопок) ───────────────────────────
def handle_payload(vk, uid, payload_str):
    try:
        p = json.loads(payload_str)
    except:
        return False

    action = p.get("action")
    target_id = p.get("target")

    # +1 к полю
    if action == "inc" and target_id:
        field = p["field"]
        row = get_user(target_id)
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return True
        idx = {"warns": 4, "reprimands": 6, "points": 10, "inactives": 11}
        current = row[idx[field]]
        update_field(target_id, field, current + 1)
        send_edit_menu(vk, uid, target_id)
        return True

    # -1 к полю
    if action == "dec" and target_id:
        field = p["field"]
        row = get_user(target_id)
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return True
        idx = {"warns": 4, "reprimands": 6, "points": 10, "inactives": 11}
        current = row[idx[field]]
        new_val = max(0, current - 1)
        update_field(target_id, field, new_val)
        send_edit_menu(vk, uid, target_id)
        return True

    # Повышение сегодня
    if action == "promote" and target_id:
        today = date.today().strftime("%d.%m.%Y")
        update_field(target_id, "date_promoted", today)
        send_edit_menu(vk, uid, target_id)
        return True

    # Закрыть меню
    if action == "close":
        send(vk, uid, "✅ Меню закрыто", keyboard=empty_keyboard())
        return True

    # Открыть ручной ввод
    if action == "manual" and target_id:
        kb = make_manual_keyboard(target_id)
        send(vk, uid, "✏️ Выбери поле для изменения:", keyboard=kb)
        return True

    # Выбрано поле для ручного ввода
    if action == "set_field" and target_id:
        field = p["field"]
        row = get_user(target_id)
        nick = row[1] if row else str(target_id)
        pending[uid] = {"target_id": target_id, "field": field, "nick": nick}
        field_names = {
            "warns": "выговоры",
            "reprimands": "предупреждения",
            "points": "баллы",
            "inactives": "неактивы",
            "admin_level": "уровень прав",
            "rank": "должность",
            "date_promoted": "дату повышения (дд.мм.гггг)",
            "date_appointed": "дату назначения (дд.мм.гггг)"
        }
        fname = field_names.get(field, field)
        send(vk, uid, f"✏️ Введи новое значение для «{fname}» ({nick}):", keyboard=empty_keyboard())
        return True

    # Назад в меню редактирования
    if action == "back" and target_id:
        send_edit_menu(vk, uid, target_id)
        return True

    return False

# ─── Обработка команд ──────────────────────────────────────
def handle(vk, event):
    uid = event.user_id
    text = event.text.strip()
    parts = text.split()
    cmd = parts[0].lower() if parts else ""

    ADMINS = get_admins()
    is_admin = uid in ADMINS
    is_creator = is_group_creator(vk, uid)

    # ── Сначала проверяем payload кнопок ──────────────────
    if hasattr(event, "payload") and event.payload and (is_admin or is_creator):
        handled = handle_payload(vk, uid, event.payload)
        if handled:
            return

    # ── Проверяем ожидание ручного ввода ──────────────────
    if uid in pending and (is_admin or is_creator):
        state = pending.pop(uid)
        target_id = state["target_id"]
        field = state["field"]
        nick = state["nick"]

        # Числовые поля
        if field in ("warns", "reprimands", "points", "inactives"):
            try:
                val = int(text)
                update_field(target_id, field, val)
                send_edit_menu(vk, uid, target_id)
            except ValueError:
                send(vk, uid, "❌ Введи целое число")
                pending[uid] = state
            return

        # Дробные поля
        if field == "admin_level":
            try:
                val = float(text)
                update_field(target_id, field, val)
                send_edit_menu(vk, uid, target_id)
            except ValueError:
                send(vk, uid, "❌ Введи число (например: 1 или 1.5)")
                pending[uid] = state
            return

        # Текстовые поля
        if field == "rank":
            update_field(target_id, field, text)
            send_edit_menu(vk, uid, target_id)
            return

        # Даты
        if field in ("date_promoted", "date_appointed"):
            try:
                datetime.strptime(text, "%d.%m.%Y")
                update_field(target_id, field, text)
                send_edit_menu(vk, uid, target_id)
            except ValueError:
                send(vk, uid, "❌ Неверный формат. Используй: дд.мм.гггг")
                pending[uid] = state
            return

    # ── Команды для всех ──────────────────────────────────
    if cmd == "/stats":
        row = get_user(uid)
        if not row:
            send(vk, uid, "❌ Вас нет в базе данных. Обратитесь к администратору.")
            return
        send(vk, uid, format_stats(row))

    # ── Команды администратора ────────────────────────────
    elif cmd == "/edit" and (is_admin or is_creator):
        if len(parts) < 2:
            send(vk, uid, "❌ Используй: /edit [ник, id или @ник]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден в базе")
            return
        send_edit_menu(vk, uid, row[0])

    elif cmd == "/statsof" and (is_admin or is_creator):
        if len(parts) < 2:
            send(vk, uid, "❌ Используй: /statsof [id, @ник или ник из базы]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден в базе")
        else:
            send(vk, uid, format_stats(row))

    elif cmd == "/list" and (is_admin or is_creator):
        rows = get_all_users()
        if not rows:
            send(vk, uid, "📭 База данных пуста")
            return
        lines = ["📋 Все сотрудники:\n"]
        for i, row in enumerate(rows, 1):
            vk_id, nick, rank, admin_level, warns, reprimands, points = row
            lines.append(
                f"{i}. {nick} (id{vk_id})\n"
                f"   📌 {rank} | ⭐ {admin_level} | "
                f"⚠️ {warns} | 🔔 {reprimands} | 🏆 {points} баллов"
            )
        current = ""
        for line in lines:
            if len(current) + len(line) > 3800:
                send(vk, uid, current)
                current = line
            else:
                current += "\n" + line
        if current:
            send(vk, uid, current)

    elif cmd == "/adduser" and (is_admin or is_creator):
        if len(parts) < 3:
            send(vk, uid, "❌ Используй: /adduser [id или @ник] [ник]")
            return
        target_id = resolve_target(vk, parts[1])
        if not target_id:
            send(vk, uid, "❌ Пользователь не найден")
            return
        nick = " ".join(parts[2:])
        add_user(target_id, nick)
        send(vk, uid, f"✅ Пользователь {nick} (id{target_id}) добавлен в базу")

    elif cmd == "/setnick" and (is_admin or is_creator):
        if len(parts) < 3:
            send(vk, uid, "❌ Используй: /setnick [id или ник] [новый_ник]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return
        nick = " ".join(parts[2:])
        update_field(row[0], "nick", nick)
        send(vk, uid, f"✅ Ник установлен: {nick}")

    elif cmd == "/warn" and (is_admin or is_creator):
        if len(parts) < 3:
            send(vk, uid, "❌ Используй: /warn [id или ник] [кол-во]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return
        val = int(parts[2])
        update_field(row[0], "warns", val)
        send(vk, uid, f"✅ Выговоры обновлены: {val}")

    elif cmd == "/reprimand" and (is_admin or is_creator):
        if len(parts) < 3:
            send(vk, uid, "❌ Используй: /reprimand [id или ник] [кол-во]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return
        val = int(parts[2])
        update_field(row[0], "reprimands", val)
        send(vk, uid, f"✅ Предупреждения обновлены: {val}")

    elif cmd == "/inactive" and (is_admin or is_creator):
        if len(parts) < 3:
            send(vk, uid, "❌ Используй: /inactive [id или ник] [кол-во]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return
        val = int(parts[2])
        update_field(row[0], "inactives", val)
        send(vk, uid, f"✅ Неактивы обновлены: {val}")

    elif cmd == "/points" and (is_admin or is_creator):
        if len(parts) < 3:
            send(vk, uid, "❌ Используй: /points [id или ник] [кол-во]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return
        val = int(parts[2])
        update_field(row[0], "points", val)
        send(vk, uid, f"✅ Баллы обновлены: {val}")

    elif cmd == "/setrank" and (is_admin or is_creator):
        if len(parts) < 3:
            send(vk, uid, "❌ Используй: /setrank [id или ник] [должность]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return
        rank = " ".join(parts[2:])
        update_field(row[0], "rank", rank)
        send(vk, uid, f"✅ Должность обновлена: {rank}")

    elif cmd == "/setadmin" and (is_admin or is_creator):
        if len(parts) < 3:
            send(vk, uid, "❌ Используй: /setadmin [id или ник] [уровень]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return
        val = float(parts[2])
        update_field(row[0], "admin_level", val)
        send(vk, uid, f"✅ Уровень прав обновлён: {val}")

    elif cmd == "/promote" and (is_admin or is_creator):
        if len(parts) < 2:
            send(vk, uid, "❌ Используй: /promote [id или ник]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return
        today = date.today().strftime("%d.%m.%Y")
        update_field(row[0], "date_promoted", today)
        send(vk, uid, f"✅ Дата повышения обновлена на сегодня")

    elif cmd == "/setpromote" and (is_admin or is_creator):
        if len(parts) < 3:
            send(vk, uid, "❌ Используй: /setpromote [id или ник] [дд.мм.гггг]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return
        new_date = parts[2]
        try:
            datetime.strptime(new_date, "%d.%m.%Y")
            update_field(row[0], "date_promoted", new_date)
            send(vk, uid, f"✅ Дата повышения обновлена: {new_date}")
        except ValueError:
            send(vk, uid, "❌ Неверный формат даты. Используй: дд.мм.гггг")

    elif cmd == "/setappointed" and (is_admin or is_creator):
        if len(parts) < 3:
            send(vk, uid, "❌ Используй: /setappointed [id или ник] [дд.мм.гггг]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден")
            return
        new_date = parts[2]
        try:
            datetime.strptime(new_date, "%d.%m.%Y")
            update_field(row[0], "date_appointed", new_date)
            send(vk, uid, f"✅ Дата назначения обновлена: {new_date}")
        except ValueError:
            send(vk, uid, "❌ Неверный формат даты. Используй: дд.мм.гггг")

    # ── Команды создателя группы ──────────────────────────
    elif cmd == "/addadmin" and is_creator:
        if len(parts) < 2:
            send(vk, uid, "❌ Используй: /addadmin [id или @ник]")
            return
        target_id = resolve_target(vk, parts[1])
        if not target_id:
            send(vk, uid, "❌ Пользователь не найден")
            return
        add_admin_db(target_id)
        send(vk, uid, f"✅ id{target_id} теперь администратор бота")

    elif cmd == "/removeadmin" and is_creator:
        if len(parts) < 2:
            send(vk, uid, "❌ Используй: /removeadmin [id или @ник]")
            return
        target_id = resolve_target(vk, parts[1])
        if not target_id:
            send(vk, uid, "❌ Пользователь не найден")
            return
        remove_admin_db(target_id)
        send(vk, uid, f"✅ id{target_id} больше не администратор бота")

    elif cmd == "/listadmins" and is_creator:
        admins = get_admins()
        if not admins:
            send(vk, uid, "📭 Список администраторов пуст")
            return
        lines = ["👮 Администраторы бота:\n"]
        for i, a_id in enumerate(admins, 1):
            lines.append(f"{i}. id{a_id}")
        send(vk, uid, "\n".join(lines))

    # ── /help ─────────────────────────────────────────────
    elif cmd == "/help":
        msg = (
            "📋 Команды для участников:\n"
            "/stats — твоя статистика\n"
            "/help — список команд"
        )
        if is_admin or is_creator:
            msg += (
                "\n\n🔧 Команды администратора:\n"
                "/edit [ник] — редактировать через кнопки ✨\n"
                "/statsof [id или ник] — статистика сотрудника\n"
                "/list — список всех сотрудников\n"
                "/adduser [id или @ник] [ник] — добавить в базу\n"
                "/setnick [id или ник] [новый_ник] — изменить ник\n"
                "/warn [id или ник] [кол-во] — выговоры\n"
                "/reprimand [id или ник] [кол-во] — предупреждения\n"
                "/inactive [id или ник] [кол-во] — неактивы\n"
                "/points [id или ник] [кол-во] — баллы\n"
                "/setrank [id или ник] [должность] — должность\n"
                "/setadmin [id или ник] [уровень] — уровень прав\n"
                "/promote [id или ник] — дата повышения = сегодня\n"
                "/setpromote [id или ник] [дд.мм.гггг] — дата повышения\n"
                "/setappointed [id или ник] [дд.мм.гггг] — дата назначения"
            )
        if is_creator:
            msg += (
                "\n\n👑 Команды Спец Администратора:\n"
                "/addadmin [id или @ник] — выдать права администратора\n"
                "/removeadmin [id или @ник] — забрать права администратора\n"
                "/listadmins — список всех администраторов бота"
            )
        send(vk, uid, msg)

    elif cmd.startswith("/") and not is_admin and not is_creator:
        send(vk, uid, "❌ У вас нет прав для этой команды")

# ─── Запуск ────────────────────────────────────────────────
init_db()
vk_session = vk_api.VkApi(token=TOKEN)
vk = vk_session.get_api()
longpoll = VkLongPoll(vk_session)

print("Бот запущен...")
for event in longpoll.listen():
    if event.type == VkEventType.MESSAGE_NEW and event.to_me:
        handle(vk, event)
