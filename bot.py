import asyncio
import re
import os
import json
import telethon.sync
import requests
import random
import time
import traceback
from telethon import TelegramClient, events, functions, types, errors, Button

# --- Credentials ---
API_ID = 27699293
API_HASH = '2f0aa06fe4f782c5ebd5454c19774c79'
BOT_TOKEN = '8333382101:AAE3lB8B_LOtU7_7ES5Tp-e2u5OHNc8Qwow'
DEFAULT_ADMIN = 6908091275

DB_FILE = 'bot_db.json'
SESSION_DIR = 'sessions'

if not os.path.exists(SESSION_DIR): os.makedirs(SESSION_DIR)

# Initialize Bot Client with unique session name to avoid local/repo conflicts
bot_session_name = f'bot_main_session_{BOT_TOKEN.split(":")[0]}'
bot = TelegramClient(bot_session_name, API_ID, API_HASH)

# Global Managers
user_clients = {} 
session_waits = {} 
users_in_conversation = set()
pending_notices = {}
pending_recharges = {}
processed_msgs = set() # To prevent double processing
SERVER_TAG = " [Cloud] 🌐" if os.environ.get("RAILWAY_ENVIRONMENT") else " [Local] 💻"

db_lock = asyncio.Lock()

def get_db():
    default_db = {"users": [], "blocked": [], "sessions": [], "user_data": {}, "session_stats": {}, "config": {"admin_id": DEFAULT_ADMIN, "support_id": "@rikton16", "check_delay": 0.5}}
    if not os.path.exists(DB_FILE): return default_db
    try:
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if not isinstance(data, dict): return default_db
            for k in default_db:
                if k not in data: data[k] = default_db[k]
            return data
    except: return default_db

def save_db(data):
    try:
        with open(DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e: print(f"DB Save Error: {e}")

def get_admin_id(): return get_db().get("config", {}).get("admin_id", DEFAULT_ADMIN)
def get_support_id(): return get_db().get("config", {}).get("support_id", "@rikton16")
def get_check_delay(): return get_db().get("config", {}).get("check_delay", 0.5)

def get_user_stats(user_id, name="User"):
    db = get_db(); uid_s = str(user_id)
    if uid_s not in db["user_data"]:
        db["user_data"][uid_s] = {"name": name, "points": 10, "total_tested": 0, "healthy_found": 0, "show_mode": "sort_by_order", "receive_mode": "copy"}
        save_db(db)
    elif name != "User":
        db["user_data"][uid_s]["name"] = name; save_db(db)
    return db["user_data"][uid_s]

def update_user_stats(user_id, tested=0, healthy=0, points=0, show_mode=None, receive_mode=None):
    db = get_db(); uid_s = str(user_id)
    if uid_s not in db["user_data"]: get_user_stats(user_id)
    db["user_data"][uid_s]["total_tested"] += tested
    db["user_data"][uid_s]["healthy_found"] += healthy
    db["user_data"][uid_s]["points"] += points
    if show_mode: db["user_data"][uid_s]["show_mode"] = show_mode
    if receive_mode: db["user_data"][uid_s]["receive_mode"] = receive_mode
    save_db(db)

def update_session_stats(phone, tested=1):
    db = get_db(); p = str(phone)
    if p not in db["session_stats"]: db["session_stats"][p] = {"tested": 0}
    db["session_stats"][p]["tested"] += tested
    save_db(db)

async def init_sessions():
    db = get_db()
    for sess in db.get("sessions", []):
        phone = sess["phone"]; sid = sess["session_id"]; path = os.path.join(SESSION_DIR, sid)
        if phone in user_clients: continue
        client = TelegramClient(path, API_ID, API_HASH)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                print(f"Session {phone} not authorized. Skipping.")
                await client.disconnect(); continue
                
            await client(functions.help.GetConfigRequest())
            user_clients[phone] = client
        except (errors.AuthKeyDuplicatedError, errors.AuthKeyUnregisteredError, errors.AuthKeyInvalidError):
            print(f"Session {phone} is conflicted or invalid. Skipping.")
            try: await client.disconnect()
            except: pass
        except Exception as e:
            print(f"Session {phone} error: {e}")
            try: await client.disconnect()
            except: pass

def normalize_number(phone):
    if not phone: return ""
    clean = re.sub(r'[^\d]', '', str(phone))
    return '+' + clean if not str(phone).startswith('+') else '+' + clean.lstrip('+')

country_flags = {
    "+1": "🇺🇸", "+7": "🇷🇺", "+20": "🇪🇬", "+27": "🇿🇦", "+30": "🇬🇷", "+31": "🇳🇱", "+32": "🇧🇪", "+33": "🇫🇷",
    "+34": "🇪🇸", "+36": "🇭🇺", "+39": "🇮🇹", "+40": "🇷🇴", "+41": "🇨🇭", "+43": "🇦🇹", "+44": "🇬🇧", "+45": "🇩🇰",
    "+46": "🇸🇪", "+47": "🇳🇴", "+48": "🇵🇱", "+49": "🇩🇪", "+51": "🇵🇪", "+52": "🇲🇽", "+53": "🇨🇺", "+54": "🇦🇷",
    "+55": "🇧🇷", "+56": "🇨🇱", "+57": "🇨🇴", "+58": "🇻🇪", "+60": "🇲🇾", "+61": "🇦🇺", "+62": "🇮🇩", "+63": "🇵🇭",
    "+64": "🇳🇿", "+65": "🇸🇬", "+66": "🇹🇭", "+81": "🇯🇵", "+82": "🇰🇷", "+84": "🇻🇳", "+86": "🇨🇳", "+90": "🇹🇷",
    "+91": "🇮🇳", "+92": "🇵🇰", "+98": "🇮🇷", "+212": "🇲🇦", "+213": "🇩🇿", "+216": "🇹🇳", "+218": "🇱🇾", "+234": "🇳🇬",
    "+254": "🇰🇪", "+880": "🇧🇩", "+971": "🇦🇪", "+255": "🇹🇿", "+256": "🇺🇬"
}

def get_flag(phone):
    for code in sorted(country_flags.keys(), key=len, reverse=True):
        if phone.startswith(code): return country_flags[code]
    return "🌐"

def get_main_keyboard():
    return [
        [Button.text("ℹ️ Info", resize=True)],
        [Button.text("🔋 Recharge"), Button.text("🎁 Invite & Earn")],
        [Button.text("📄 Select Result Type"), Button.text("📩 Receive Mode")],
        [Button.text("📞 Contact Support"), Button.text("⭐ Transfer Points")]
    ]

# --- Admin ---

async def show_admin_panel(event, edit=False):
    buttons = [
        [Button.inline("📢 Send Notice", b"adm_notice"), Button.inline("⚙️ Sessions Manager", b"adm_list_sess")],
        [Button.inline("👥 User List", b"adm_users_0"), Button.inline("📊 Stats", b"adm_stats")],
        [Button.inline("🔧 Bot Settings", b"adm_settings"), Button.inline("🚫 Block List", b"adm_blk_list_0")]
    ]
    txt = "🛠 **Admin Control Panel**"
    if edit: await event.edit(txt, buttons=buttons)
    else: await event.reply(txt, buttons=buttons)

async def admin_u_info(event, u_id):
    u_st = get_user_stats(u_id); db = get_db(); is_blk = int(u_id) in db["blocked"]
    msg = (f"👤 **User:** {u_st.get('name', 'N/A')}\n🆔 **ID:** `{u_id}`\n💰 **Balance:** {u_st['points']} points\n"
           f"🔎 **Tested:** {u_st['total_tested']}\n✅ **Healthy:** {u_st['healthy_found']}")
    btns = [[Button.inline("💰 Recharge Points", f"uset_{u_id}_pts".encode()), Button.inline("🔄 Reset Balance", f"uset_{u_id}_rst".encode())],
            [Button.inline("🔓 Unblock User" if is_blk else "🚫 Block User", f"uset_{u_id}_{'unb' if is_blk else 'blk'}".encode())],
            [Button.inline("⬅️ Back to List", b"adm_users_0")]]
    if hasattr(event, 'edit'):
        try:
            await event.edit(msg, buttons=btns)
        except errors.MessageNotModifiedError:
            pass
    else:
        await bot.send_message(get_admin_id(), msg, buttons=btns)

# --- Logic ---

async def check_number(phone, client, client_phone):
    try:
        flag = get_flag(phone)
        clean_phone = re.sub(r'\D', '', phone)
        # client_id should be random to avoid conflicts
        c_contact = types.InputPhoneContact(client_id=random.randint(100000, 999999), phone=phone, first_name="Check", last_name=str(time.time())[-4:])
        res_imp = await client(functions.contacts.ImportContactsRequest([c_contact]))
        
        exists = False
        is_ban = False
        target_u = None
        
        if res_imp.users:
            for u in res_imp.users:
                u_p = getattr(u, 'phone', None)
                if u_p:
                    if u_p in clean_phone or clean_phone in u_p:
                        target_u = u; break
                else: 
                    # Fallback for some sessions
                    target_u = u; break
            
            if target_u:
                if getattr(target_u, 'deleted', False):
                    is_ban = True
                else:
                    exists = True
                
                # Immediate Contact Cleanup
                try: await client(functions.contacts.DeleteContactsRequest(id=[target_u.id]))
                except: pass
        
        update_session_stats(client_phone)
        
        # Correct Icons Logic
        if is_ban: icon = "⬛️"
        elif exists: icon = "✅"
        else: icon = "❌"
        
        txt_b = f"{flag} {phone} {icon}              "
        return {"phone": phone, "exists": exists, "is_ban": is_ban, "btn_text": txt_b, "client_phone": client_phone}
    except errors.FloodWaitError as e: return {"phone": phone, "error": True, "wait_time": e.seconds, "client_phone": client_phone}
    except errors.AuthKeyDuplicatedError:
        if client_phone in user_clients: 
            try: del user_clients[client_phone]
            except: pass
        return {"phone": phone, "error": True, "wait_time": 0, "client_phone": client_phone}
    except: return {"phone": phone, "exists": False, "is_ban": False, "btn_text": f"{get_flag(phone)} {phone} ❌              ", "client_phone": client_phone}

# --- Handlers ---

@bot.on(events.NewMessage(pattern=r'/admin', incoming=True))
async def admin_cmd(event):
    if event.sender_id == get_admin_id():
        users_in_conversation.discard(event.sender_id); await show_admin_panel(event)
    raise events.StopPropagation

@bot.on(events.NewMessage(pattern=r'/start', incoming=True))
async def start_cmd(event):
    users_in_conversation.discard(event.sender_id); db = get_db(); name = event.sender.first_name or "User"
    if event.sender_id not in db['users']: db['users'].append(event.sender_id); save_db(db)
    get_user_stats(event.sender_id, name=name)
    if event.sender_id in db['blocked']:
         return await event.reply(f"❌ You are currently blocked. Please contact the admin: {get_support_id()}")
    await event.reply(f"👋 Welcome to Number Checker Bot!", buttons=get_main_keyboard())
    raise events.StopPropagation

@bot.on(events.NewMessage(pattern=r'/login', incoming=True))
async def login_cmd(event):
    if event.sender_id != get_admin_id(): return
    try:
        users_in_conversation.add(event.sender_id)
        async with bot.conversation(event.chat_id, timeout=300) as conv:
            await conv.send_message("📞 **Enter Number:**"); n = (await conv.get_response()).text.strip()
            sid = f"s_{int(time.time())}"; p = os.path.join(SESSION_DIR, sid); cl = TelegramClient(p, API_ID, API_HASH); await cl.connect()
            try:
                await cl.send_code_request(n); await conv.send_message("📩 **Enter OTP:**")
                o = (await conv.get_response()).text.strip(); await cl.sign_in(n, o); user_clients[n] = cl
                db = get_db(); db["sessions"].append({"phone": n, "session_id": sid}); save_db(db); await conv.send_message("✅ **Session Added!**")
            except Exception as e: await conv.send_message(f"❌ Error: {e}")
    except: pass
    finally: users_in_conversation.discard(event.sender_id)
    raise events.StopPropagation

@bot.on(events.NewMessage(incoming=True))
async def msg_handler(event):
    if not event.is_private or event.sender_id in users_in_conversation: return
    if event.id in processed_msgs: return
    processed_msgs.add(event.id)
    if len(processed_msgs) > 1000: processed_msgs.pop() # Keep it small
    
    u_id = event.sender_id; db = get_db(); text = event.text
    if u_id in db['blocked']: 
         return await event.reply(f"❌ You are currently blocked. Please contact the admin: {get_support_id()}")
    
    if text == "ℹ️ Info":
        s = get_user_stats(u_id); me = await bot.get_me()
        msg = (f"🆔 Your Id: `{u_id}`\n💰 Your Balance: {s['points']} points\n"
               f"🔎 Tested: {s['total_tested']}\n✅ Healthy: {s['healthy_found']}\n\n@{me.username}")
        return await event.reply(msg)
    elif text == "📩 Receive Mode":
        s = get_user_stats(u_id); rm = s.get('receive_mode', 'copy')
        btns = [[Button.inline(f"{'✅ ' if rm=='text' else ''}📝 As Text", b"m_rcv_text")],
                [Button.inline(f"{'✅ ' if rm=='copy' else ''}📋 As Copy Button", b"m_rcv_copy")],
                [Button.inline(f"{'✅ ' if rm=='file' else ''}📁 As a File", b"m_rcv_file")]]
        return await event.reply("📲 Select display mode:", buttons=btns)
    elif text == "📄 Select Result Type":
        s = get_user_stats(u_id); md = s['show_mode']
        btns = [[Button.inline(f"{'✅ ' if md=='green_first' else ''}🟢 Green First", b"m_sh_gr_f")],
                [Button.inline(f"{'✅ ' if md=='sort_by_order' else ''}🔢 By Order", b"m_sh_ord")],
                [Button.inline(f"{'✅ ' if md=='only_green' else ''}✅ Only ✅", b"m_sh_on_gr")],
                [Button.inline(f"{'✅ ' if md=='only_used' else ''}🔐 Only 🔐", b"m_sh_on_ud")]]
        return await event.reply("📲 Select result type:", buttons=btns)
    elif text == "🎁 Invite & Earn": return await event.reply(f"Referral: t.me/{(await bot.get_me()).username}?start={u_id}")
    elif text == "📞 Contact Support":
        msg = (f"🆘 Need help or have questions?\nYou can contact our support team for assistance.\n\n"
               f"📩 Message the admin directly at:\n🆔 {get_support_id()}")
        return await event.reply(msg)
    elif text == "🔋 Recharge":
        btn = [[Button.url("👤 Pay Admin", f"https://t.me/{get_support_id().replace('@','')}")]]
        return await event.reply("$1 = 10000 points🔥", buttons=btn)
    elif text == "⭐ Transfer Points":
        try:
            users_in_conversation.add(u_id); s = get_user_stats(u_id)
            if s['points'] <= 0: return await event.reply("❌ 0 points available.")
            async with bot.conversation(u_id, timeout=120) as conv:
                await conv.send_message("🆔 Please enter the numeric User ID:\nℹ️ To get the numeric User ID, you can use this bot: @userinfo_bot")
                r = await conv.get_response(); t_id = r.text.strip()
                if not t_id.isdigit(): return await conv.send_message("❌ Invalid ID.")
                await conv.send_message(f"💰 How many points do you want to transfer? (Available: {s['points']})")
                r = await conv.get_response(); amt_s = r.text.strip()
                if not amt_s.isdigit(): return await conv.send_message("❌ Invalid amount.")
                amt = int(amt_s)
                if amt > s['points'] or amt <= 0: return await conv.send_message("❌ Balance error.")
                update_user_stats(u_id, points=-amt); update_user_stats(int(t_id), points=amt)
                await conv.send_message(f"✅ Successfully transferred {amt} points to {t_id}.")
                try: await bot.send_message(int(t_id), f"🎁 You received {amt} points!")
                except: pass
        except: pass
        finally: users_in_conversation.discard(u_id); return
    
    # Check Logic
    if text.startswith('/') or len(text) < 5: return
    if not user_clients: return await event.reply("⚠️ No Active Sessions.")
    nums = [normalize_number(l.strip()) for l in text.split('\n') if len(normalize_number(l.strip())) > 7]
    if not nums: return
    s = get_user_stats(u_id); to_chk = nums[:s['points']] if s['points'] < len(nums) else nums
    if not to_chk: return await event.reply("❌ Insufficient points.")
    
    st_msg = await event.reply(f"⚙️ Processing... ⌛"); results = []; pending = list(to_chk); start_t = time.time(); delay = get_check_delay()
    anim_frames = ["🔄", "🔃", "🔄", "🔃"]
    while pending:
        now = time.time(); avl = [p for p in user_clients if session_waits.get(p, 0) < now]
        if not avl: 
             await asyncio.sleep(2); now = time.time()
             if all(session_waits.get(p, 0) > now for p in user_clients):
                  try: await st_msg.edit(f"⏳ Waiting for High Traffic...")
                  except: pass
             continue
        batch_size = min(len(avl), len(pending)); batch = [pending.pop(0) for _ in range(batch_size)]
        tasks = [asyncio.wait_for(check_number(batch[i], user_clients[avl[i]], avl[i]), timeout=20) for i in range(batch_size)]
        try:
            batch_res = await asyncio.gather(*tasks, return_exceptions=True)
            for r in batch_res:
                if isinstance(r, dict) and not r.get("error"): results.append(r)
                elif isinstance(r, dict) and r.get("phone"): 
                     pending.insert(0, r["phone"])
                     if r.get("error") and not r.get("remove_sess"): 
                          session_waits[r.get("client_phone")] = now + r.get("wait_time", 10)
                     if r.get("remove_sess"):
                          # Remove from DB too
                          db = get_db()
                          db["sessions"] = [s for s in db["sessions"] if s["phone"] != r.get("client_phone")]
                          save_db(db)
        except: pass
        try: 
             pct = (len(results) * 10) // len(to_chk); bar = "■" * pct + "□" * (10 - pct)
             frame = anim_frames[len(results) % len(anim_frames)]
             await st_msg.edit(f"⚙️ **Processing hoitese...** {frame}\n\n📊 Progress: [{bar}] {len(results)}/{len(to_chk)}")
        except: pass
        await asyncio.sleep(delay)
    
    duration = round(time.time() - start_t, 2); await st_msg.delete()
    update_user_stats(u_id, tested=len(to_chk), healthy=len([r for r in results if r["exists"]]), points=-len(to_chk))
    st = get_user_stats(u_id); final = results; md = st['show_mode']; rm = st.get('receive_mode', 'copy')
    if md == "only_green": final = [r for r in results if not r["exists"] and not r["is_ban"]]
    elif md == "only_used": final = [r for r in results if r["exists"]]
    elif md == "green_first": final = sorted(results, key=lambda x: x["exists"])
    
    c_ok = len([r for r in results if r["exists"]]); c_no = len([r for r in results if not r["exists"] and not r["is_ban"]]); c_bn = len([r for r in results if r["is_ban"]])
    res_h = (f"অ্যাকাউন্ট থাকলে: 🔐 | না থাকলে: ✅ | ব্যান: ⬛️\n⏱️ Time Taken: {duration}s\n📊 Results :{SERVER_TAG}\n🔐:{c_ok:02}\n✅:{c_no:02}\n⬛️:{c_bn:02}")
    if rm == "copy":
        for i in range(0, len(final), 100):
            pld = {"chat_id": event.chat_id, "text": res_h, "reply_markup": {"inline_keyboard": [[{"text": r["btn_text"], "copy_text": {"text": r["phone"]}}] for r in final[i:i+100]]}}
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=pld, timeout=10)
    elif rm == "text":
        txt = res_h + "\n\n" + "\n".join([r['btn_text'] for r in final]); await event.reply(txt[:4096])
    elif rm == "file":
        out = res_h + "\n\n" + "\n".join([f"{r['phone']} {'🔐' if r['exists'] else '✅' if not r['is_ban'] else '⬛️'}" for r in final])
        with open("res.txt", "w", encoding="utf-8") as f: f.write(out)
        await event.reply(f"📊 Results File:", file="res.txt"); os.remove("res.txt")
    if len(to_chk) < len(nums): await event.reply(f"⚠️ {len(nums)-len(to_chk)} numbers skipped (Balance).")

@bot.on(events.CallbackQuery)
async def callback_handler(event):
    try:
        data = event.data; uid = event.sender_id; db = get_db(); admir = get_admin_id()
        await event.answer()
        
        if data.startswith(b"m_"):
            mode = data.decode().replace("m_", "")
            if mode.startswith("rcv_"): update_user_stats(uid, receive_mode=mode.replace("rcv_", ""))
            elif mode.startswith("sh_"): 
                m_m = {"sh_gr_f": "green_first", "sh_ord": "sort_by_order", "sh_on_gr": "only_green", "sh_on_ud": "only_used"}
                update_user_stats(uid, show_mode=m_m.get("sh_"+mode.replace("sh_",""), "sort_by_order"))
            s = get_user_stats(uid); rm = s.get('receive_mode', 'copy'); md = s['show_mode']
            if "rcv_" in mode: btns = [[Button.inline(f"{'✅ ' if rm=='text' else ''}📝 As Text", b"m_rcv_text")], [Button.inline(f"{'✅ ' if rm=='copy' else ''}📋 As Copy Button", b"m_rcv_copy")], [Button.inline(f"{'✅ ' if rm=='file' else ''}📁 As a File", b"m_rcv_file")]]
            else: btns = [[Button.inline(f"{'✅ ' if md=='green_first' else ''}🟢 Green First", b"m_sh_gr_f")], [Button.inline(f"{'✅ ' if md=='sort_by_order' else ''}🔢 By Order", b"m_sh_ord")], [Button.inline(f"{'✅ ' if md=='only_green' else ''}✅ Only ✅", b"m_sh_on_gr")], [Button.inline(f"{'✅ ' if md=='only_used' else ''}🔐 Only 🔐", b"m_sh_on_ud")]]
            return await event.edit("✅ Updated!", buttons=btns)

        if uid != admir: return
        if data == b"adm_main": await show_admin_panel(event, edit=True)
        elif data == b"adm_settings":
            btns = [[Button.inline(f"🆔 Admin ID: {get_admin_id()}", b"set_adm_id")], [Button.inline(f"👤 Support: {get_support_id()}", b"set_supp_id")], [Button.inline(f"⚡ Speed (Delay: {get_check_delay()}s)", b"set_speed")], [Button.inline("⬅️ Back", b"adm_main")]]
            await event.edit("⚙️ **Bot Settings:**", buttons=btns)
        elif data == b"set_speed":
            async with bot.conversation(admir, timeout=300) as conv:
                await conv.send_message("Enter delay in seconds:"); r = await conv.get_response()
                try: db["config"]["check_delay"] = float(r.text); save_db(db); await conv.send_message("✅ Done!"); await show_admin_panel(event, edit=True)
                except: pass
        elif data.startswith(b"set_"):
            if data == b"set_adm_id":
                 async with bot.conversation(admir, timeout=300) as conv:
                     await conv.send_message("Enter new Admin ID:"); r = await conv.get_response()
                     if r.text.isdigit(): db["config"]["admin_id"] = int(r.text); save_db(db); await conv.send_message("✅ Done!"); await show_admin_panel(event, edit=True)
            elif data == b"set_supp_id":
                 async with bot.conversation(admir, timeout=300) as conv:
                     await conv.send_message("Enter Support ID (with @):"); r = await conv.get_response()
                     if r.text.startswith("@"): db["config"]["support_id"] = r.text; save_db(db); await conv.send_message("✅ Done!"); await show_admin_panel(event, edit=True)
        elif data == b"rc_conf":
            inf = pending_recharges.pop(admir, None)
            if inf:
                u = inf["uid"]; amt = inf["amt"]; update_user_stats(u, points=amt)
                try: await event.edit(f"✅ Recharge complete!")
                except: pass
                try: await bot.send_message(int(u), f"🎉 Balance recharged with {amt} points!")
                except: pass
        elif data == b"adm_stats":
            s_ph = [s['phone'] for s in db.get('sessions', [])]; ok = len([p for p in s_ph if p in user_clients])
            await event.edit(f"👥 Users: {len(db['users'])}\n📱 Sessions: {len(s_ph)} ({ok} Active)", buttons=[[Button.inline("⬅️ Back", b"adm_main")]])
        elif data == b"adm_notice":
            async with bot.conversation(admir, timeout=300) as conv:
                await conv.send_message("📝 Notice message:"); msg = (await conv.get_response()).text
                pending_notices[admir] = msg; btns = [[Button.inline("✅ Send", b"nt_send"), Button.inline("❌ Cancel", b"adm_main")]]
                await conv.send_message(f"📢 Preview:\n\n{msg}", buttons=btns)
        elif data == b"nt_send":
            m = pending_notices.pop(admir, None); 
            if m: 
                await event.edit("⏳ Sending..."); c = 0
                for u in db['users']:
                    try: await bot.send_message(u, f"📢 **NOTICE:**\n\n{m}"); c += 1
                    except: pass
                await event.edit(f"✅ Sent to {c} users!", buttons=[[Button.inline("⬅️ Back", b"adm_main")]])
        elif data == b"adm_list_sess":
            btns = [[Button.inline(f"{'🟢' if s['phone'] in user_clients else '🔴'} {s['phone']}", f"si_{s['phone']}".encode())] for s in db.get('sessions', [])]
            btns.append([Button.inline("⬅️ Back", b"adm_main")]); await event.edit("Sessions:", buttons=btns)
        elif data.startswith(b"si_"):
            p = data.decode().split("_")[1]; st_s = db.get("session_stats", {}).get(p, {"tested": 0})
            btns = [[Button.inline("🔓 Logout", f"lo_{p}".encode())], [Button.inline("⬅️ Back", b"adm_list_sess")]]
            await event.edit(f"📱 {p}\nTested: {st_s['tested']}", buttons=btns)
        elif data.startswith(b"lo_"):
            p = data.decode().split("_")[1]; db["sessions"] = [s for s in db["sessions"] if s["phone"] != p]
            if p in user_clients: cs = user_clients.pop(p); await cs.disconnect()
            save_db(db); await show_admin_panel(event, edit=True)
        elif data.startswith(b"adm_users_"):
            pg = int(data.decode().split("_")[2]); usrs = list(db['user_data'].keys()); batch = usrs[pg*20:(pg+1)*20]
            btns = [[Button.inline(f"👤 {db['user_data'][u].get('name', u)}", f"us_{u}".encode())] for u in batch]
            btns.append([Button.inline("⬅️ Back", b"adm_main")]); await event.edit("User List:", buttons=btns)
        elif data.startswith(b"us_"):
            u = data.decode().split("_")[1]; await admin_u_info(event, u)
        elif data.startswith(b"uset_"):
            u, act = data.decode().split("_")[1:3]
            if act == "pts":
                 async with bot.conversation(admir, timeout=300) as conv:
                     await conv.send_message(f"💰 Amount for {u}:"); r = await conv.get_response()
                     if r.text.isdigit(): 
                         amt = int(r.text); pending_recharges[admir] = {"uid": u, "amt": amt}
                         btns_c = [[Button.inline("✅ Yes", b"rc_conf"), Button.inline("❌ No", f"us_{u}".encode())]]
                         await conv.send_message(f"❓ Confirm recharge of **{amt}** points for `{u}`?", buttons=btns_c)
            elif act == "rst": update_user_stats(u, points=-get_user_stats(u)['points']); await admin_u_info(event, u)
            elif act == "blk": 
                 if int(u) not in db['blocked']: db['blocked'].append(int(u)); save_db(db); await admin_u_info(event, u)
            elif act == "unb":
                 db['blocked'] = [i for i in db['blocked'] if i != int(u)]; save_db(db); await admin_u_info(event, u)
        elif data.startswith(b"adm_blk_list_"):
            btns = [[Button.inline(f"🔓 Unblock {u}", f"ub_{u}".encode())] for u in db['blocked']]
            btns.append([Button.inline("⬅️ Back", b"adm_main")]); await event.edit("Blocked Users:", buttons=btns)
        elif data.startswith(b"ub_"):
            u = int(data.decode().split("_")[1]); db['blocked'] = [i for i in db['blocked'] if i != u]; save_db(db); await show_admin_panel(event, edit=True)
    except errors.MessageNotModifiedError: pass
    except Exception:
        print(f"Callback Error Traceback:\n{traceback.format_exc()}")

async def global_error_handler(event):
    err = str(event)
    if "two different IP addresses" in err or "AuthKeyDuplicatedError" in err:
        print(f"Background session Issue: {err}")
bot.add_event_handler(global_error_handler, events.Raw)

async def main():
    while True:
        try:
            if not bot.is_connected():
                await bot.start(bot_token=BOT_TOKEN)
            await init_sessions()
            print("--- Bot Is Now Online (Cloud Stable Mode) ---")
            await bot.run_until_disconnected()
        except Exception as e:
            err_msg = str(e).lower()
            if any(x in err_msg for x in ["ip addresses", "authkeyduplicated", "authorization key", "getconfigrequest"]):
                 print(f"CLOUD CONFLICT DETECTED: {e}")
                 try:
                     await bot.disconnect()
                     # Try to remove the main bot session file
                     for f in os.listdir("."):
                         if f.startswith(bot_session_name) and f.endswith(".session"):
                             os.remove(f)
                             print(f"Fixed: Removed conflicted bot session file {f}")
                 except: pass
                 await asyncio.sleep(2)
            elif "getdifferencerequest" in err_msg or "update" in err_msg:
                 print(f"Background Sync (Non-Critical): {e}")
                 await asyncio.sleep(2)
            else:
                 print(f"Global Error: {e}")
                 await asyncio.sleep(5)

if __name__ == '__main__':
    asyncio.run(main())
