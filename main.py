"""
BF-6 Tracker.gg Discord bot
────────────────────────────────────────────────────────────────────────────
Slash & “!” prefix helpers:

• /bf6 leaderboard   – K/D, SPM, …   (cached 30 s)
• /bf6 player        – single-player overview
• /bf6 recent        – last X matches
• /bf6 roster_add / roster_remove   (server-admins, with UI pick-list)
• /restart  and  /sync              (bot-owner only)
"""
from __future__ import annotations
import os, sys, json, asyncio, logging, itertools, warnings, urllib.parse as _urlparse
warnings.filterwarnings("ignore", category=UserWarning, module="discord")

import discord
from discord.ext import commands
from discord import app_commands, Interaction
from dotenv import load_dotenv
from api_handler import TrnClient            # ← make sure it exposes .search_players()

# ───────────────────────── logging ───────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-4s %(name)s: %(message)s")
log = logging.getLogger("bf6bot")

# ───────────────────────── env & bot ─────────────────────────────────────
load_dotenv()
TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
bot  = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ───────────────────────── roster store ──────────────────────────────────
with open("players.json", encoding="utf8") as f:
    PLAYERS: list[dict] = json.load(f)

PLAYER_CACHE: dict[tuple[str, str], dict] = {
    (p["platform"], p["userId"]): p for p in PLAYERS
}
NAME_INDEX: dict[str, list[dict]] = {}
for p in PLAYERS:
    NAME_INDEX.setdefault(p["name"].lower(), []).append(p)
NAME_CHOICES = sorted(NAME_INDEX.keys())

PLATFORMS = ["steam", "xboxone", "ps"]

# ───────────────────────── stat map ──────────────────────────────────────
STATMAP = {
    "kd":      ("kdRatio",            "K/D"),
    "spm":     ("scorePerMinute",     "Score/Min"),
    "kpm":     ("killsPerMinute",     "Kills/Min"),
    "kills":   ("kills",              "Kills"),
    "wins":    ("matchesWon",         "Wins"),
    "winrate": ("wlPercentage",       "Win %"),
    "hs":      ("headshotPercentage", "HS %"),
}

# ───────────────────────── which overview stats to show ──────────────────
OVERVIEW_KEYS = [
    "careerPlayerRank",  # rank     (gets icon & value)
    "score",
    "matchesPlayed", "matchesWon", "matchesLost", "wlPercentage",
    "timePlayed",
    "kills", "assists", "deaths",
    "kdRatio", "kdaRatio",
    "scorePerMinute", "killsPerMinute", "damagePerMinute",
    "headshotPercentage",
]

def fmt(v: float, key: str) -> str:
    if "Percentage" in key: return f"{v:,.2f}%"
    if key in {"kdRatio", "scorePerMinute", "killsPerMinute"}: return f"{v:,.2f}"
    return f"{int(v):,}"

# ───────────────────────── helpers ───────────────────────────────────────
async def safe_defer(i: Interaction, *, ephemeral=None):
    try:
        await asyncio.wait_for(i.response.defer(thinking=True,
                                                ephemeral=ephemeral), 2.5)
    except (discord.NotFound, asyncio.TimeoutError):
        pass

def _choices(seq, cur):                    # for autocomplete
    cur = cur.lower()
    return [app_commands.Choice(name=s, value=s)
            for s in itertools.islice((s for s in seq if cur in s.lower()), 20)]

async def ac_player(_, cur):   return _choices(NAME_CHOICES, cur)
async def ac_platform(_, cur): return _choices(PLATFORMS, cur)

def find_player_by_name(name: str) -> dict | None:
    lst = NAME_INDEX.get(name.lower())
    return lst[0] if lst else None

def _flag(cc: str | None) -> str:
    """Convert ISO-3166 code → regional-indicator emoji (🇺🇸, 🇳🇿 …)."""
    if not cc: return ""
    return "".join(chr(0x1F1E6 + ord(c) - 0x41) for c in cc.upper())

# ───────────────────────── UI pick-lists ─────────────────────────────────
class PlayerSelect(discord.ui.Select):
    """
    mode = "search"  → items = tracker.gg /search hits
         = "roster"  → items = roster dicts
    """
    def __init__(self, matches: list[dict], *, mode: str):
        self.mode = mode
        self.matches = matches

        if mode == "search":                           # add-player dialog
            opts = [
                discord.SelectOption(
                    label=f"{m['platformUserHandle']} ({m['platformSlug']})",
                    description=(
                        f"{m.get('status','–')} • "
                        f"{m['additionalParameters'].get('countryCode','--')} • "
                        f"ID {m['titleUserId']}"
                    )[:100],                           # Discord ≤100 chars
                    value=str(i)
                ) for i, m in enumerate(matches[:25])
            ]
        else:                                          # remove-player dialog
            opts = [
                discord.SelectOption(
                    label=f"{m['name']} ({m['platform']})",
                    description=f"ID {m['userId']}",
                    value=str(i)
                ) for i, m in enumerate(matches[:25])
            ]

        super().__init__(placeholder="Choose…",
                         min_values=1, max_values=1, options=opts)
        self.chosen: dict | None = None

    async def callback(self, interaction: Interaction):
        self.chosen = self.matches[int(self.values[0])]
        await interaction.response.defer()
        self.view.stop()

class ConfirmView(discord.ui.View):
    def __init__(self, matches: list[dict], author: discord.User, *, mode: str):
        super().__init__(timeout=30)
        self.author_id = author.id
        self.select = PlayerSelect(matches, mode=mode)
        self.add_item(self.select)

    async def interaction_check(self, inter: Interaction) -> bool:
        return inter.user.id == self.author_id

# ───────────────────────── ID resolver (startup) ────────────────────────
async def resolve_ids():
    need = [p for p in PLAYER_CACHE.values() if "userId" not in p]
    if not need: return
    async with TrnClient() as trn:
        tasks = [trn.search_players(p["platform"], p["name"]) for p in need]
        results = await asyncio.gather(*tasks)

    for p, hits in zip(need, results):
        if hits:
            p["userId"] = hits[0]["titleUserId"]
            log.info("ID for %-15s → %s", p["name"], p["userId"])
        else:
            log.warning("ID lookup failed for %s", p["name"])

    with open("players.json", "w", encoding="utf8") as f:
        json.dump(list(PLAYER_CACHE.values()), f, indent=2)

# ───────────────────────── embeds & commands ────────────────────────────
async def leaderboard_embed(stat_key: str):
    field, pretty = STATMAP[stat_key]
    async with TrnClient() as trn:
        profs = await asyncio.gather(
            *[trn.player_profile(p["platform"], p["userId"])
              for p in PLAYER_CACHE.values()]
        )

    board = []
    for p, prof in zip(PLAYER_CACHE.values(), profs):
        try:
            v = float(prof["segments"][0]["stats"][field]["value"])
            board.append((p["name"], v))
        except Exception: pass

    if not board: return None
    board.sort(key=lambda x: x[1], reverse=True)

    medals = ["🥇","🥈","🥉"]
    desc = "\n".join(
        f"{medals[i-1] if i<=3 else f'`{i:02}`'} "
        f"**{name}** — {fmt(v, field)}"
        for i, (name, v) in enumerate(board, 1)
    )
    return (discord.Embed(title=f"Battlefield 6 – {pretty} leaderboard",
                          description=desc, colour=0x0096FF)
            .set_footer(text="Data • tracker.gg • cached 30 s"))

# group
bf6 = app_commands.Group(name="bf6", description="Battlefield 6 stats suite")
tree.add_command(bf6)

@bf6.command(name="leaderboard")
@app_commands.choices(
    stat=[app_commands.Choice(name=v[1], value=k) for k, v in STATMAP.items()]
)
async def bf6_leaderboard(i: Interaction, stat: app_commands.Choice[str]):
    await safe_defer(i)
    emb = await leaderboard_embed(stat.value)
    await i.followup.send(embed=emb or discord.Embed(description="No data."))

@bf6.command(name="player")
@app_commands.autocomplete(name=ac_player)
async def bf6_player(i: Interaction, name: str):
    await safe_defer(i)
    p = find_player_by_name(name)
    if not p:
        return await i.followup.send("Player not found.")

    async with TrnClient() as trn:
        prof = await trn.player_profile(p["platform"], p["userId"])
    if not prof:
        return await i.followup.send("API error.")

    # API sometimes wraps under .data – handle both shapes
    data = prof.get("data", prof)
    segs = data["segments"]
    overview = segs[0]["stats"]

    # country flag
    flag = _flag(data.get("userInfo", {}).get("countryCode"))

    emb = discord.Embed(
        title=f"BF6 – {p['name']} {flag}",
        colour=0x3498DB,
    )

    # rank icon thumbnail (encoded into the imgsvc proxy)
    rank_stat = overview.get("careerPlayerRank")
    if rank_stat and (img := rank_stat.get("metadata", {}).get("imageUrl")):
        encoded = _urlparse.quote(img, safe="")
        thumb = (
            f"https://imgsvc.trackercdn.com/url/max-width(168),quality(70)/"
            f"{encoded}/image.png"
        )
        emb.set_thumbnail(url=thumb)

    # add the selected overview stats
    for key in OVERVIEW_KEYS:
        s = overview.get(key)
        if not s or key == "careerPlayerRank":
            # rank already handled via thumbnail + will still add field below
            pass
        if s:  # add every stat we actually got back
            emb.add_field(
                name=s["displayName"],
                value=s["displayValue"],
                inline=True,
            )

    await i.followup.send(embed=emb)

@bf6.command(name="recent")
@app_commands.autocomplete(name=ac_player)
async def bf6_recent(i: Interaction, name: str,
                     count: app_commands.Range[int,1,10]):
    await safe_defer(i)
    p = find_player_by_name(name)
    if not p: return await i.followup.send("Player not found.")
    async with TrnClient() as trn:
        matches = await trn.recent_matches(p["platform"], p["userId"], count)
    if not matches:
        return await i.followup.send(f"🕑 No recent matches for **{name}**.",
                                     ephemeral=True)

    lines = []
    for m in matches:
        seg = m["segments"][0]
        meta = m.get("metadata",{}) or seg.get("metadata",{})
        date = (meta.get("timestamp") or "")[:10] or "--------"
        ks   = seg["stats"]
        lines.append(
            f"**{date}** – {ks['kills']['displayValue']}/"
            f"{ks['deaths']['displayValue']} "
            f"K/D `{ks['kdRatio']['displayValue']}`"
        )
    await i.followup.send(
        embed=discord.Embed(title=f"Last {len(matches)} – {p['name']}",
                            description="\n".join(lines),
                            colour=0x00AEEF))

# ───────────────────────── roster admin ──────────────────────────────────
def is_admin(i: Interaction): return i.user.guild_permissions.manage_guild

@bf6.command(name="roster_add")
@app_commands.default_permissions(manage_guild=True)
@app_commands.check(is_admin)
@app_commands.autocomplete(platform=ac_platform)
async def bf6_add(i: Interaction, query: str, platform: str):
    await safe_defer(i, ephemeral=True)
    platform = platform.lower().strip()
    if platform not in PLATFORMS:
        return await i.followup.send("❌ Unknown platform.", ephemeral=True)

    async with TrnClient() as trn:
        hits = await trn.search_players(platform, query)
    if not hits:
        return await i.followup.send("Player not found.", ephemeral=True)

    if len(hits) > 1:
        view = ConfirmView(hits, i.user, mode="search")
        await i.followup.send("🔍 Multiple results – pick one:", view=view,
                              ephemeral=True)
        await view.wait()
        chosen = view.select.chosen
        if chosen is None: return
    else:
        chosen = hits[0]

    handle  = chosen["platformUserHandle"]
    user_id = chosen["titleUserId"]
    key = (platform, user_id)
    PLAYER_CACHE[key] = {"name":handle, "platform":platform, "userId":user_id}
    NAME_INDEX.setdefault(handle.lower(), []).append(PLAYER_CACHE[key])
    if handle not in NAME_CHOICES: NAME_CHOICES.append(handle)

    with open("players.json","w",encoding="utf8") as f:
        json.dump(list(PLAYER_CACHE.values()), f, indent=2)

    await i.followup.send(f"✅ Added **{handle}** ({platform})", ephemeral=True)

@bf6.command(name="roster_remove")
@app_commands.default_permissions(manage_guild=True)
@app_commands.check(is_admin)
async def bf6_remove(i: Interaction, name: str):
    await safe_defer(i, ephemeral=True)
    matches = [p for p in PLAYER_CACHE.values()
               if p["name"].lower()==name.lower()]
    if not matches:
        return await i.followup.send("Not in roster.", ephemeral=True)

    if len(matches) > 1:
        view = ConfirmView(matches, i.user, mode="roster")
        await i.followup.send("Duplicates found – choose one to delete:",
                              view=view, ephemeral=True)
        await view.wait()
        choice = view.select.chosen
        if choice is None: return
    else:
        choice = matches[0]

    PLAYER_CACHE.pop((choice["platform"], choice["userId"]), None)
    NAME_INDEX[choice["name"].lower()].remove(choice)
    with open("players.json","w",encoding="utf8") as f:
        json.dump(list(PLAYER_CACHE.values()), f, indent=2)

    await i.followup.send(f"🗑️ Removed **{choice['name']}** ({choice['platform']})",
                          ephemeral=True)

# ───────────────────────── owner helpers ────────────────────────────────
async def _restart():
    await bot.close(); await asyncio.sleep(0.1); sys.exit(0)

@tree.command(name="restart")
@app_commands.default_permissions(administrator=True)
async def restart_slash(i: Interaction):
    await i.response.send_message("♻️ Restarting…", ephemeral=True); await _restart()

@bot.command(name="restart")
@commands.is_owner()
async def restart_prefix(_): await _restart()

@bot.command(name="sync")
@commands.is_owner()
async def sync_here(ctx):
    tree.copy_global_to(guild=ctx.guild)
    await tree.sync(guild=ctx.guild)
    await ctx.send("Slash commands synced ✅")

# ───────────────────────── bot ready ────────────────────────────────────
@bot.event
async def on_ready():
    log.info("✅ Logged in as %s", bot.user)
    await resolve_ids()
    try:
        log.info("Global sync: %s cmd(s)", len(await tree.sync()))
    except Exception as e:
        log.warning("Global sync failed: %s", e)

# ───────────────────────── run ───────────────────────────────────────────
if __name__ == "__main__":
    bot.run(TOKEN)
