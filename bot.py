import discord
from discord.ext import commands
import re
import os
from datetime import timedelta

# TOKEN aus Render Environment Variables
TOKEN = os.getenv("TOKEN")

# Prefix
PREFIX = "!"

# Discord Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Rollenname
ROLLEN_NAME = "Alleine Im Call"

# Discord Invite + normale Links erkennen
link_regex = re.compile(
    r"(https?://|www\.|discord\.gg/|discord\.com/invite/)"
)

@bot.event
async def on_ready():
    print(f"Bot online als {bot.user}")

# Nachrichten überwachen
@bot.event
async def on_message(message):

    # Bots ignorieren
    if message.author.bot:
        return

    # Admins ignorieren (optional)
    if message.author.guild_permissions.administrator:
        return

    # Link erkannt?
    if link_regex.search(message.content):

        try:
            # Nachricht löschen
            await message.delete()

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

    await bot.process_commands(message)

# Voice Rollen System
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

        # Genau 1 Person im Call
        if len(menschen) == 1:

            user = menschen[0]

            if rolle not in user.roles:
                await user.add_roles(rolle)
                print(f"{user} hat die Rolle bekommen")

        # Mehr als 1 Person
        else:

            for user in menschen:

                if rolle in user.roles:
                    await user.remove_roles(rolle)
                    print(f"{user} Rolle entfernt")

# Bot starten
bot.run(TOKEN)

