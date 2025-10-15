# BF6 Statistics Discord Bot

A live Discord bot that pulls statistics from tracker.gg, built for ranking a given group of players defined in players.json.

# List of Commands

| Slash / Prefix | Command syntax                                    | What it does                                                          | Permission required                |
|----------------|---------------------------------------------------|-----------------------------------------------------------------------|------------------------------------|
| **/bf6 leaderboard** | `/bf6 leaderboard <stat>`                       | Shows a lifetime stat leaderboard (`kd`, `spm`, `kpm`, `kills`, `wins`, `winrate`, `hs`). | Everyone                           |
| **/bf6 player** | `/bf6 player <name>`                               | Sends an overview embed for one tracked player (K/D, kills, score / min, etc.). | Everyone                           |
| **/bf6 recent** | `/bf6 recent <name> [count]`                       | Lists the last *n* public matches for a player (1-10, default = 3).   | Everyone                           |
| **/bf6 roster_add** | `/bf6 roster_add <name> <platform>`               | Adds a player to the roster (autocomplete for platform).              | “Manage Server” permission         |
| **/bf6 roster_remove** | `/bf6 roster_remove <name>`                       | Removes a player from the roster.                                     | “Manage Server” permission         |
| **/bf6 restart** | `/bf6 restart`                                    | Gracefully restarts the bot.                                          | Administrator                      |
| **!sync**      | `!sync`                                            | Copies global slash-commands to this guild, then syncs them.          | Bot owner only                     |
| **!restart**   | `!restart`                                         | Prefix alias for `/bf6 restart`.                                      | Bot owner only                     |

## Extras
* **Autocomplete** – player arguments suggest tracked names; platform suggests `steam`, `xboxone`, `ps`.
* **Caching** – responses cached for **30 s** to respect Tracker.gg rate limits.