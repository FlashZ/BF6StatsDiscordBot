# Battlefield6 Statistics Discord Bot

A live Discord bot that pulls Battlefield 6 statistics from tracker.gg, built for ranking a group of players defined in `players.json`.

## Features

- **Leaderboard**: View lifetime stat leaderboards for tracked players.
- **Player Overview**: Get detailed stats for any tracked player.
- **Recent Matches**: List recent public matches for a player.
- **Roster Management**: Add or remove players from the tracked roster (admin only).
- **Bot Controls**: Restart the bot or sync commands (admin only).
- **Autocomplete**: Player and platform arguments support autocomplete.
- **Caching**: API responses cached for 30 seconds to respect Tracker.gg rate limits.

## Commands

| Command            | Syntax                                         | Description                                                                 |
|--------------------|------------------------------------------------|-----------------------------------------------------------------------------|
| **/bf6 leaderboard**    | `/bf6 leaderboard <stat>`                       | Shows a lifetime stat leaderboard (`kd`, `spm`, `kpm`, `kills`, `wins`, `winrate`, `hs`). |
| **/bf6 player**         | `/bf6 player <name>`                               | Sends an overview embed for one tracked player.                             |
| **/bf6 recent**         | `/bf6 recent <name> [count]`                       | Lists the last *n* public matches for a player (1-10, default = 3).         |
| **/bf6 roster_add**     | `/bf6 roster_add <name> <platform>`                | Adds a player to the roster (autocomplete for platform).                    |
| **/bf6 roster_remove**  | `/bf6 roster_remove <name>`                        | Removes a player from the roster. (Admin Only)                              |
| **/bf6 restart**        | `/bf6 restart`                                     | Gracefully restarts the bot. (Admin Only)                                   |
| **!sync**               | `!sync`                                            | Copies global slash-commands to this guild, then syncs (Admin Only).        |
| **!restart**            | `!restart`                                         | Prefix alias for `/bf6 restart`. (Admin Only)                               |

## Setup

### 1. Environment Variables

Create a file named `.env` in the project root:

```dotenv
# Discord bot token (Bot settings → Token → Reset → copy)
DISCORD_BOT_TOKEN=YOUR_DISCORD_BOT_TOKEN_HERE
```

### 2. Installation

```sh
git clone https://github.com/FlashZ/BF6StatsDiscordBot.git
cd BF6StatsDiscordBot
python -m venv .venv
.venv\Scripts\activate        # On Windows
pip install -r requirements.txt
python main.py
```

### 3. Invite the Bot

1. Go to Discord Developer Portal → OAuth2 → URL Generator.
2. Scopes: `bot`, `applications.commands`
3. Bot Permissions: Send Messages, Embed Links, Read Message History
4. Visit the generated URL, select your server, and Authorize.

Type `/bf6 leaderboard` in your server to verify the bot is working.

## Notes

- **Autocomplete**: Player arguments suggest tracked names; platform suggests `steam`, `xboxone`, `ps`.
- **Caching**: Responses cached for 30 seconds to respect Tracker.gg rate limits.
