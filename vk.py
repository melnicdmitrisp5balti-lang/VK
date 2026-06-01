import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
import psycopg2
import os
from datetime import date, datetime

TOKEN = "vk1.a.HC0dIDDvX_S11Rvu0v_z8XIuv9uzPIPqS_O9Xu4dMF_T_6FEYBqvkK7jqFiNrntG65esMnAzvdgNa08eJ3Cqp2e3BMmFXzVjrmjwoTvtCou-1XZCPaaE46giu1s1QPz7iRHbfjdAYtdrDkFFA6X1RGHZcbjlhMdrethcP4INDYkw6hd_ryR0l-PjnlTwGKQJARfm0jdJX9_VT2KiWAGYfA"

# ID группы (число без минуса, например если группа -123456789 → GROUP_ID = 123456789)
GROUP_ID = 239267601  # ← ЗАМЕНИ НА ID СВОЕЙ ГРУППЫ

# ─── Проверка создателя группы через VK API ────────────────
def is_group_creator(vk, user_id):
    try:
        info = vk.groups.getById(group_id=GROUP_ID, fields="")[0]
        return info.get("is_admin") and info.get("admin_level") == 3 or False
    except:
        pass
    try:
        members = vk.groups.getMembers(group_id=GROUP_ID, filter="managers", fields="role")
        for m in members.get("items", []):
            if m["id"] == user_id and m.get("role") == "creator":
                return True
    except:
        pass
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
        f"📊 Ваша персональная статистика:\n\n"
        f"👤 Ваш ник: [id{vk_id}|{nick}]\n"
        f"🎖 Ваша должность: {rank}\n"
        f"⭐ Уровень прав администратора: {admin_level}\n\n"
        f"⚠️ Выговоры: {warns}/{max_warns}\n"
        f"🔔 Предупреждения: {reprimands}/{max_reprimands}\n\n"
        f"📅 Дата назначения: {date_app}\n"
        f"📅 Дата повышения: {date_prom}\n"
        f"⏳ Дней после повышения: {days_str}\n\n"
        f"🏆 Баллы: {points} баллов\n"
        f"😴 Неактивы: {inactives}"
    )

# ─── Отправка сообщения ────────────────────────────────────
def send(vk, user_id, message):
    vk.messages.send(user_id=user_id, message=message, random_id=0)

# ─── Поиск пользователя (ник / id / @ник) ─────────────────
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

# ─── Обработка команд ──────────────────────────────────────
def handle(vk, event):
    uid = event.user_id
    text = event.text.strip()
    parts = text.split()
    cmd = parts[0].lower() if parts else ""

    ADMINS = get_admins()
    is_admin = uid in ADMINS
    is_creator = is_group_creator(vk, uid)

    # ── Команды для всех ──────────────────────────────────
    if cmd == "/stats":
        row = get_user(uid)
        if not row:
            send(vk, uid, "❌ Вас нет в базе данных. Обратитесь к администратору.")
            return
        send(vk, uid, format_stats(row))

    # ── Команды администратора ────────────────────────────
    elif cmd == "/statsof" and is_admin:
        if len(parts) < 2:
            send(vk, uid, "❌ Используй: /statsof [id, @ник или ник из базы]")
            return
        row = find_user(vk, parts[1])
        if not row:
            send(vk, uid, "❌ Пользователь не найден в базе")
        else:
            send(vk, uid, format_stats(row))

    elif cmd == "/list" and is_admin:
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

    elif cmd == "/adduser" and is_admin:
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

    elif cmd == "/setnick" and is_admin:
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

    elif cmd == "/warn" and is_admin:
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

    elif cmd == "/reprimand" and is_admin:
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

    elif cmd == "/inactive" and is_admin:
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

    elif cmd == "/points" and is_admin:
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

    elif cmd == "/setrank" and is_admin:
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

    elif cmd == "/setadmin" and is_admin:
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

    elif cmd == "/promote" and is_admin:
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

    elif cmd == "/setpromote" and is_admin:
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

    elif cmd == "/setappointed" and is_admin:
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

    # ── Команды Спец Администратора (только создатель группы) ──
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
        if is_admin:
            msg += (
                "\n\n🔧 Команды администратора:\n"
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
