import discord
from discord.ext import commands
import json
import re
from datetime import timedelta

# Config laden
with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

TOKEN = config["token"]
PREFIX = config["prefix"]

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# ROLLENNAME HIER EINTRAGEN
ROLLEN_NAME = "Alleine Im Call"

# 🔥 Link Regex (Discord Invite + normale Links)
link_regex = re.compile(r"(https?://|www\.|discord\.gg/|discord\.com/invite/)")

@bot.event
async def on_ready():
    print(f"Bot online als {bot.user}")


# 💥 NEU: Nachrichten-Überwachung (LINK DETECTION)
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Link erkannt?
    if link_regex.search(message.content):
        try:
            # 7 Tage Timeout
            timeout_duration = timedelta(days=7)

            await message.author.timeout(
                timeout_duration,
                reason="Posting links in chat"
            )

            await message.channel.send(
                f"🚫 {message.author.mention} wurde für 7 Tage getimeoutet wegen eines Links."
            )

        except discord.Forbidden:
            print("Keine Rechte für Timeout.")
        except Exception as e:
            print(f"Fehler: {e}")

    # wichtig: Commands weiterhin erlauben
    await bot.process_commands(message)


@bot.event
async def on_voice_state_update(member, before, after):

    guild = member.guild
    rolle = discord.utils.get(guild.roles, name=ROLLEN_NAME)

    if rolle is None:
        print("Rolle nicht gefunden")
        return

    # Alle Voice-Channels prüfen
    for channel in guild.voice_channels:

        menschen = [
            m for m in channel.members
            if not m.bot
        ]

        # Wenn genau 1 Person im Call
        if len(menschen) == 1:

            user = menschen[0]

            if rolle not in user.roles:
                await user.add_roles(rolle)
                print(f"{user} hat die Rolle bekommen")

        # Wenn mehr als 1 Person im Call
        else:
            for user in menschen:

                if rolle in user.roles:
                    await user.remove_roles(rolle)
                    print(f"{user} Rolle entfernt")


bot.run(TOKEN)
