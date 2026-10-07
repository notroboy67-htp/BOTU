import os, sqlite3, secrets, string, logging, asyncio
from datetime import datetime, timezone
from pathlib import Path
import requests
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN=os.getenv("DISCORD_TOKEN","").strip()
PANEL_URL=os.getenv("NRB_PANEL_URL","").rstrip("/")
ADMIN_USERNAME=os.getenv("NRB_ADMIN_USERNAME","admin").strip()
ADMIN_PASSWORD=os.getenv("NRB_ADMIN_PASSWORD","admin")
GUILD_ID=os.getenv("GUILD_ID","").strip()
ADMIN_USER_IDS={x.strip() for x in os.getenv("ADMIN_USER_IDS","").split(",") if x.strip()}
ADMIN_ROLE_IDS={x.strip() for x in os.getenv("ADMIN_ROLE_IDS","").split(",") if x.strip()}
LOG_CHANNEL_ID=os.getenv("LOG_CHANNEL_ID","").strip()
DEFAULT_NODE_ID=int(os.getenv("DEFAULT_NODE_ID","0") or 0)
DEFAULT_OS=os.getenv("DEFAULT_OS","ubuntu:22.04")
DEFAULT_CPU=int(os.getenv("DEFAULT_CPU","2"))
DEFAULT_RAM=int(os.getenv("DEFAULT_RAM","2"))
DEFAULT_DISK=int(os.getenv("DEFAULT_DISK","20"))
DB_PATH=os.getenv("DB_PATH","data/nrb_hosting.db")

if not TOKEN: raise SystemExit("DISCORD_TOKEN is missing")
if not PANEL_URL: raise SystemExit("NRB_PANEL_URL is missing")

Path(DB_PATH).parent.mkdir(parents=True,exist_ok=True)
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(message)s",
 handlers=[logging.FileHandler("logs/bot.log"),logging.StreamHandler()])
log=logging.getLogger("nrb")

def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c
def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS accounts(
        id INTEGER PRIMARY KEY AUTOINCREMENT, discord_id TEXT NOT NULL,
        discord_name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL, email TEXT NOT NULL, vps_id INTEGER,
        container_name TEXT, created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active')""")
        c.execute("""CREATE TABLE IF NOT EXISTS audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT, discord_id TEXT NOT NULL,
        action TEXT NOT NULL, target TEXT, created_at TEXT NOT NULL)""")
        c.commit()
def rand_user():
    a=string.ascii_letters+string.digits
    while True:
        u="NRB_"+''.join(secrets.choice(a) for _ in range(8))
        with db() as c:
            if not c.execute("SELECT 1 FROM accounts WHERE username=?",(u,)).fetchone(): return u
def rand_pass():
    a=string.ascii_letters+string.digits+"!@#$%^&*_-+="
    while True:
        p=''.join(secrets.choice(a) for _ in range(16))
        if all([any(x.islower() for x in p),any(x.isupper() for x in p),any(x.isdigit() for x in p),any(x in "!@#$%^&*_-+=" for x in p)]): return p
def audit(uid,action,target=""):
    with db() as c:
        c.execute("INSERT INTO audit(discord_id,action,target,created_at) VALUES(?,?,?,?)",
                  (str(uid),action,target,datetime.now(timezone.utc).isoformat())); c.commit()

def panel_create(username,password,email):
    s=requests.Session()
    r=s.post(PANEL_URL+"/login",data={"username":ADMIN_USERNAME,"password":ADMIN_PASSWORD,"remember":"on"},timeout=20,allow_redirects=True)
    if r.status_code>=400 or "/login" in r.url:
        raise RuntimeError(f"NRB admin login failed (HTTP {r.status_code})")
    r=s.post(PANEL_URL+"/admin/users/create",json={
        "username":username,"email":email,"password":password,
        "is_admin":False,"port_quota":10},timeout=30)
    if not r.ok: raise RuntimeError(f"NRB user creation failed: {r.text[:300]}")
    data=r.json()
    if not data.get("success"): raise RuntimeError(data.get("error","NRB user creation failed"))
    return int(data["user_id"]),s

def panel_nodes(s):
    r=s.get(PANEL_URL+"/admin/nodes",timeout=20)
    if not r.ok: raise RuntimeError(f"NRB node request failed: HTTP {r.status_code}")
    # The admin page is HTML, so use the panel's nodes API if available; otherwise query the DB is not possible remotely.
    # Prefer the JSON endpoint used by the panel if present.
    for path in ("/api/admin/nodes","/api/nodes"):
        try:
            x=s.get(PANEL_URL+path,timeout=15)
            if x.ok:
                d=x.json()
                if isinstance(d,dict) and isinstance(d.get("nodes"),list): return d["nodes"]
                if isinstance(d,list): return d
        except Exception: pass
    raise RuntimeError("Could not discover an NRB node automatically. Set DEFAULT_NODE_ID in .env.")

def panel_create_vps(s,user_id,node_id):
    r=s.post(PANEL_URL+"/admin/vps/create",json={
        "user_id":user_id,"node_id":node_id,"hostname":"",
        "os_version":DEFAULT_OS,"cpu":DEFAULT_CPU,"ram":DEFAULT_RAM,"disk":DEFAULT_DISK,
        "ip_address":None,"ip_alias":None,"auto_suspend_enabled":False,"expiration_days":0
    },timeout=180)
    if not r.ok: raise RuntimeError(f"NRB VPS creation failed: HTTP {r.status_code} {r.text[:300]}")
    d=r.json()
    if not d.get("success"): raise RuntimeError(d.get("error","NRB VPS creation failed"))
    return d

def create_account_and_vps():
    u,p=rand_user(),rand_pass()
    email=f"{u.lower()}@nrb.host"
    user_id,s=panel_create(u,p,email)
    node_id=DEFAULT_NODE_ID
    if not node_id:
        nodes=panel_nodes(s)
        active=[n for n in nodes if n.get("status","").lower() in ("online","active","ready") or n.get("is_local")]
        if not active: raise RuntimeError("No active NRB node was found.")
        node_id=int(active[0]["id"])
    vps=panel_create_vps(s,user_id,node_id)
    return u,p,email,vps

class Bot(commands.Bot):
    def __init__(self): super().__init__(command_prefix="!",intents=discord.Intents.default())
    async def setup_hook(self):
        init_db()
        if GUILD_ID:
            g=discord.Object(id=int(GUILD_ID)); self.tree.copy_global_to(guild=g); await self.tree.sync(guild=g)
        else: await self.tree.sync()
    async def on_ready(self): log.info("Online as %s",self.user)
bot=Bot()

def is_admin(i):
    if str(i.user.id) in ADMIN_USER_IDS:return True
    return isinstance(i.user,discord.Member) and any(str(r.id) in ADMIN_ROLE_IDS for r in i.user.roles)

@bot.tree.command(name="create",description="Create an NRB user and VPS.")
async def create(i):
    with db() as c:
        if c.execute("SELECT 1 FROM accounts WHERE discord_id=? AND status='active'",(str(i.user.id),)).fetchone():
            return await i.response.send_message("You already have an active NRB VPS. Use `/myaccount`.",ephemeral=True)
    await i.response.defer(ephemeral=True,thinking=True)
    try:
        u,p,email,vps=await asyncio.to_thread(create_account_and_vps)
        with db() as c:
            c.execute("""INSERT INTO accounts(discord_id,discord_name,username,password,email,vps_id,container_name,created_at)
                         VALUES(?,?,?,?,?,?,?,?)""",
                      (str(i.user.id),str(i.user),u,p,email,vps.get("vps_id"),vps.get("container_name"),
                       datetime.now(timezone.utc).isoformat())); c.commit()
        audit(i.user.id,"CREATE_VPS",str(vps.get("vps_id")))
        await i.followup.send(
            f"**NRB VPS Created Successfully**\n\n"
            f"Panel: `{PANEL_URL}`\nUsername: `{u}`\nPassword: `{p}`\n"
            f"VPS: `{vps.get('container_name','-')}`\nVPS ID: `{vps.get('vps_id','-')}`\n\nKeep these credentials private.",
            ephemeral=True)
    except Exception as e:
        log.exception("create failed")
        await i.followup.send(f"❌ VPS creation failed: `{str(e)[:500]}`",ephemeral=True)

@bot.tree.command(name="myaccount",description="Show your NRB VPS account.")
async def myaccount(i):
    with db() as c:r=c.execute("SELECT username,status,vps_id,container_name FROM accounts WHERE discord_id=? ORDER BY id DESC LIMIT 1",(str(i.user.id),)).fetchone()
    if not r:return await i.response.send_message("No account. Use `/create`.",ephemeral=True)
    await i.response.send_message(f"**NRB VPS**\nUsername: `{r['username']}`\nStatus: `{r['status']}`\nVPS ID: `{r['vps_id']}`\nServer: `{r['container_name']}`",ephemeral=True)

@bot.tree.command(name="status",description="Show bot status.")
async def status(i):
    with db() as c:n=c.execute("SELECT COUNT(*) FROM accounts WHERE status='active'").fetchone()[0]
    await i.response.send_message(f"🟢 **NRB Bot Online**\nActive VPS accounts: `{n}`\nPanel: `{PANEL_URL}`\nLatency: `{round(bot.latency*1000)}ms`",ephemeral=True)

@bot.tree.command(name="admin_stats",description="Admin: show statistics.")
async def admin_stats(i):
    if not is_admin(i):return await i.response.send_message("Admin only.",ephemeral=True)
    with db() as c:
        total=c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]; active=c.execute("SELECT COUNT(*) FROM accounts WHERE status='active'").fetchone()[0]
    await i.response.send_message(f"**NRB Admin**\nTotal accounts: `{total}`\nActive: `{active}`",ephemeral=True)

@bot.tree.command(name="admin_accounts",description="Admin: list accounts.")
async def admin_accounts(i):
    if not is_admin(i):return await i.response.send_message("Admin only.",ephemeral=True)
    with db() as c:rows=c.execute("SELECT discord_name,username,vps_id,status FROM accounts ORDER BY id DESC LIMIT 25").fetchall()
    out="**Latest accounts**\n"+"\n".join(f"`{r['username']}` — {r['discord_name']} — VPS `{r['vps_id']}` — {r['status']}" for r in rows)
    await i.response.send_message(out[:1900] or "No accounts.",ephemeral=True)

@bot.tree.command(name="admin_logs",description="Admin: show audit logs.")
async def admin_logs(i):
    if not is_admin(i):return await i.response.send_message("Admin only.",ephemeral=True)
    with db() as c:rows=c.execute("SELECT action,target,discord_id,created_at FROM audit ORDER BY id DESC LIMIT 20").fetchall()
    await i.response.send_message(("**Audit Logs**\n"+"\n".join(f"`{r['created_at'][:19]}` {r['action']} `{r['target']}`" for r in rows))[:1900],ephemeral=True)

@bot.tree.command(name="admin_revoke",description="Admin: revoke a bot-managed account.")
@app_commands.describe(username="NRB username")
async def admin_revoke(i,username:str):
    if not is_admin(i):return await i.response.send_message("Admin only.",ephemeral=True)
    with db() as c:
        cur=c.execute("UPDATE accounts SET status='revoked' WHERE username=? AND status='active'",(username,));c.commit()
    if not cur.rowcount:return await i.response.send_message("Account not found.",ephemeral=True)
    audit(i.user.id,"REVOKE_ACCOUNT",username)
    await i.response.send_message(f"Revoked `{username}` in bot records. The NRB VPS itself is not deleted by this command.",ephemeral=True)

bot.run(TOKEN)
