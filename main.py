"""
BF-6 Tracker.gg Discord bot
────────────────────────────────────────────────────────────────────────────
Slash & “!” prefix helpers:

• /bf6 leaderboard   – K/D, SPM, …   (cached 30 s)
• /bf6 player        – single-player overview
• /bf6 recent        – last X matches
• /bf6 roster add / remove   (server-admins)
• /restart  and  /sync         (bot-owner only)

Cloudflare is solved with cloudscraper; we keep a 4-concurrency, 30-second
memory cache inside api_handler.py.
"""
from __future__ import annotations

import os, sys, json, time, asyncio, logging, itertools, warnings
warnings.filterwarnings("ignore", category=UserWarning, module="discord")

import discord
from discord.ext   import commands
from discord       import app_commands, Interaction
from dotenv        import load_dotenv
from api_handler   import TrnClient

# ──────────────── logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-4s %(name)s: %(message)s"
)
log = logging.getLogger("bf6bot")

# ──────────────── env / discord client ───────────────────────────────────
load_dotenv()
TOKEN      = os.environ["DISCORD_BOT_TOKEN"]
OWNER_ID   = int(os.getenv("BOT_OWNER_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True

bot  = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # shorthand

# ──────────────── player roster ──────────────────────────────────────────
with open("players.json") as f:
    PLAYERS: list[dict] = json.load(f)

PLAYER_CACHE = {p["name"].lower(): p for p in PLAYERS}
PLATFORMS    = ["steam", "xboxone", "ps"]

# ──────────────── stat mapping & format helper ───────────────────────────
STATMAP = {
    "kd":      ("kdRatio",            "K/D"),
    "spm":     ("scorePerMinute",     "Score/Min"),
    "kpm":     ("killsPerMinute",     "Kills/Min"),
    "kills":   ("kills",              "Kills"),
    "wins":    ("matchesWon",         "Wins"),
    "winrate": ("wlPercentage",       "Win %"),
    "hs":      ("headshotPercentage", "HS %"),
}
def fmt(value: float, key: str) -> str:
    if "Percentage" in key:
        return f"{value:,.2f}%"
    if key in {"kdRatio", "scorePerMinute", "killsPerMinute"}:
        return f"{value:,.2f}"
    return f"{int(value):,}"

# ──────────────── interaction-safety helper ──────────────────────────────
async def safe_defer(inter: Interaction, *, ephemeral: bool | None = None):
    """Try to defer in <3 s, silently ignore UnknownInteraction."""
    try:
        await asyncio.wait_for(
            inter.response.defer(thinking=True, ephemeral=ephemeral), 2.5
        )
    except (discord.NotFound, asyncio.TimeoutError):
        pass                             # already acknowledged or timed-out

# ──────────────── autocomplete helpers (must be *async*) ─────────────────
def _choices(seq, current: str):
    cur = current.lower()
    items = (s for s in seq if cur in s.lower())
    return [app_commands.Choice(name=s, value=s)
            for s in itertools.islice(items, 20)]

async def ac_player(inter: Interaction, cur: str):
    return _choices(PLAYER_CACHE.keys(), cur)

async def ac_platform(inter: Interaction, cur: str):
    return _choices(PLATFORMS, cur)

# small util
def find_player(name: str): return PLAYER_CACHE.get(name.lower())

# ──────────────── Cloudflare warm-up / ID resolver ───────────────────────
async def resolve_ids():
    async with TrnClient() as trn:
        tasks = [
            trn.search_player(p["platform"], p["name"])
            for p in PLAYER_CACHE.values() if "userId" not in p
        ]
        results = await asyncio.gather(*tasks)

    idx = 0
    for p in PLAYER_CACHE.values():
        if "userId" in p:
            continue
        res = results[idx]; idx += 1
        if res:
            p["userId"] = res["titleUserId"]
            log.info("ID for %-15s → %s", p["name"], p["userId"])
        else:
            log.warning("ID lookup failed for %s", p["name"])

    with open("players.json", "w") as f:
        json.dump(list(PLAYER_CACHE.values()), f, indent=2)

# ──────────────── event-logging ──────────────────────────────────────────
@bot.listen("on_app_command_completion")
async def _log_slash(inter: Interaction, cmd: app_commands.Command):
    params = vars(inter.namespace) or {}
    args = " ".join(f"{k}={v}" for k, v in params.items())
    log.info("[SLASH] %s : /%s %s", inter.user, cmd.qualified_name, args)

# ──────────────── embed builders ─────────────────────────────────────────
async def leaderboard_embed(stat_key: str) -> discord.Embed | None:
    field, pretty = STATMAP[stat_key]

    async with TrnClient() as trn:
        profiles = await asyncio.gather(
            *[trn.player_profile(p["platform"], p["userId"])
              for p in PLAYER_CACHE.values() if "userId" in p]
        )

    board = []
    for p, prof in zip(PLAYER_CACHE.values(), profiles):
        try:
            val = float(prof["segments"][0]["stats"][field]["value"]) if prof else None
        except Exception:
            val = None
        if val is not None:
            board.append((p["name"], val))

    if not board:
        return None

    board.sort(key=lambda x: x[1], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    lines  = []
    for i, (name, v) in enumerate(board, 1):
        tag = medals[i-1] if i <= 3 else f"`{i:02}`"
        lines.append(f"{tag} **{name}** — {fmt(v, field)}")

    emb = discord.Embed(
        title=f"Battlefield 6 – {pretty} leaderboard",
        description="\n".join(lines),
        colour=0x0096FF
    )
    emb.set_footer(text="Data • tracker.gg • cached 30 s")
    return emb

# ──────────────── /bf6 command group ─────────────────────────────────────
bf6 = app_commands.Group(
    name="bf6",
    description="Battlefield 6 stats suite"
)
tree.add_command(bf6)

# leaderboard
@bf6.command(name="leaderboard", description="Show a leaderboard for a stat")
@app_commands.choices(
    stat=[app_commands.Choice(name=v[1], value=k) for k, v in STATMAP.items()]
)
async def bf6_leaderboard(inter: Interaction, stat: app_commands.Choice[str]):
    await safe_defer(inter)
    emb = await leaderboard_embed(stat.value)
    await inter.followup.send(embed=emb or discord.Embed(description="No data."))

# single-player overview
@bf6.command(name="player", description="Overview for one player")
@app_commands.autocomplete(name=ac_player)
async def bf6_player(inter: Interaction, name: str):
    await safe_defer(inter)
    p = find_player(name)
    if not p:
        return await inter.followup.send("Player not found.")
    async with TrnClient() as trn:
        prof = await trn.player_profile(p["platform"], p["userId"])
    if not prof:
        return await inter.followup.send("API error.")
    s = prof["segments"][0]["stats"]
    emb = discord.Embed(title=f"BF6 – {p['name']}", colour=0x3498DB)
    for key in ("kdRatio", "kills", "deaths",
                "scorePerMinute", "wlPercentage", "timePlayed"):
        emb.add_field(name=s[key]["displayName"],
                      value=s[key]["displayValue"], inline=True)
    await inter.followup.send(embed=emb)

# recent matches
@bf6.command(name="recent", description="Last X matches (max 10)")
@app_commands.autocomplete(name=ac_player)
async def bf6_recent(inter: Interaction, name: str, count: app_commands.Range[int, 1, 10]):
    await safe_defer(inter)
    p = find_player(name)
    if not p:
        return await inter.followup.send("Player not found.")
    async with TrnClient() as trn:
        matches = await trn.recent_matches(p["platform"], p["userId"], count)
    if not matches:
        return await inter.followup.send(
            f"🕑 No recent public matches for **{name}**.",
            ephemeral=True
        )

    lines = []
    for m in matches:
        seg  = m["segments"][0]
        meta = m.get("metadata", {}) or seg.get("metadata", {})
        date = (meta.get("timestamp") or "")[:10]  # "YYYY-MM-DD" or --
        ks   = seg["stats"]
        lines.append(
            f"**{date or '--------'}** – "
            f"{ks['kills']['displayValue']}/"
            f"{ks['deaths']['displayValue']} K/D `{ks['kdRatio']['displayValue']}`"
        )

# roster management ── admin-only
def is_admin(inter: Interaction):
    return inter.user.guild_permissions.manage_guild

@bf6.command(name="roster_add", description="Add a player to the roster")
@app_commands.default_permissions(manage_guild=True)
@app_commands.check(is_admin)
@app_commands.autocomplete(platform=ac_platform)
async def bf6_add(inter: Interaction, name: str, platform: str):
    platform = platform.lower().strip(",")
    if platform not in PLATFORMS:
        return await inter.followup.send("❌ Unknown platform.", ephemeral=True)    
    await safe_defer(inter, ephemeral=True)
    async with TrnClient() as trn:
        res = await trn.search_player(platform, name)
    if not res:
        return await inter.followup.send("Player not found.")
    PLAYER_CACHE[name.lower()] = {
        "name": name, "platform": platform, "userId": res["titleUserId"]
    }
    with open("players.json", "w") as f:
        json.dump(list(PLAYER_CACHE.values()), f, indent=2)
    await inter.followup.send(f"✅ Added **{name}**")

@bf6.command(name="roster_remove", description="Remove from roster")
@app_commands.default_permissions(manage_guild=True)
@app_commands.check(is_admin)
@app_commands.autocomplete(name=ac_player)
async def bf6_remove(inter: Interaction, name: str):
    await safe_defer(inter, ephemeral=True)
    if PLAYER_CACHE.pop(name.lower(), None) is None:
        return await inter.followup.send("Not in roster.")
    with open("players.json", "w") as f:
        json.dump(list(PLAYER_CACHE.values()), f, indent=2)
    await inter.followup.send(f"🗑️ Removed **{name}**")

# ──────────────── owner-only helpers ──────────────────────────────────────
async def _restart():
    await bot.close()
    await asyncio.sleep(0.1)
    sys.exit(0)

@tree.command(name="restart", description="Restart the bot (owner-only)")
@app_commands.default_permissions(administrator=True)
async def restart_slash(inter: Interaction):
    await inter.response.send_message("♻️ Restarting…", ephemeral=True)
    await _restart()

@bot.command(name="restart")
@commands.is_owner()
async def restart_prefix(ctx): await _restart()

# quick local sync
@bot.command(name="sync")
@commands.is_owner()
async def sync_here(ctx: commands.Context):
    tree.copy_global_to(guild=ctx.guild)
    synced = await tree.sync(guild=ctx.guild)
    await ctx.send(f"Synced {len(synced)} command(s) to **{ctx.guild.name}** ✅")

# ──────────────── on_ready ────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info("✅ Logged in as %s", bot.user)
    await resolve_ids()
    try:
        n = len(await tree.sync())
        log.info("Global sync: %s cmd(s)", n)
    except Exception as e:
        log.warning("Global sync failed: %s", e)

# ──────────────── run ─────────────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(TOKEN)
