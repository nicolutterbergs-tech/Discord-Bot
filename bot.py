import discord
from discord.ext import commands
import re
import os
import sys
from datetime import timedelta
import subprocess
from flask import Flask
from threading import Thread

# Flask Webserver für UptimeRobot
app = Flask('')

@app.route('/')
def home():
    return "Bot läuft!"

def run():
    app.run(host='0.0.0.0', port=5000)

def keep_alive():
    t = Thread(target=run)
    t.start()

# TOKEN aus Environment Variable
TOKEN = os.getenv("TOKEN")

# Prefix
PREFIX = "!"

# LOG CHANNEL ID HIER EINTRAGEN
LOG_CHANNEL_ID = 1509957389674348717

# Discord Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Rollenname
ROLLEN_NAME = "Alleine Im Call"

# Link Regex
link_regex = re.compile(
    r"(https?://|www\.|discord\.gg/|discord\.com/invite/)"
)

# Log Funktion
async def send_log(message):

    channel = bot.get_channel(LOG_CHANNEL_ID)

    if channel:
        await channel.send(message)

# Bot gestartet
@bot.event
async def on_ready():

    await bot.tree.sync()

    print(f"Bot online als {bot.user}")

    await send_log(
        f"🟢 Bot gestartet als {bot.user}"
    )

# Restart Command
@bot.tree.command(
    name="restart",
    description="Restartet den Bot"
)
async def restart(interaction: discord.Interaction):

    # Nur Admins
    if not interaction.user.guild_permissions.administrator:

        await interaction.response.send_message(
            "❌ Keine Berechtigung.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(
        "🔄 Bot wird neugestartet..."
    )

    await send_log(
        f"🔄 Bot Neustart durch {interaction.user}"
    )

    await bot.close()

    os.execv(sys.executable, [sys.executable] + sys.argv)

# Nachrichten überwachen
@bot.event
async def on_message(message):

    # Bots ignorieren
    if message.author.bot:
        return

    # Admins ignorieren
    if message.author.guild_permissions.administrator:
        return

    # Link erkannt?
    if link_regex.search(message.content):

        try:
            # Nachricht löschen
            await message.delete()

            # Timeout
            timeout_duration = timedelta(days=7)

            await message.author.timeout(
                timeout_duration,
                reason="Posting links in chat"
            )

            # DM an den User
            try:
                await message.author.send(
                    f"⚠️ **Du wurdest verwarnt!**\n\n"
                    f"Du wurdest auf dem Server für **7 Tage** getimeoutet, "
                    f"weil du einen Link gepostet hast.\n\n"
                    f"📨 Deine Nachricht:\n{message.content}"
                )
            except discord.Forbidden:
                pass

            # Log senden
            await send_log(
                f"⚠️ **Verwarnung ausgesprochen**\n\n"
                f"👤 User: {message.author.mention} (`{message.author}`)\n"
                f"⏱️ Timeout: 7 Tage\n"
                f"📨 Nachricht: {message.content}\n"
                f"📍 Channel: {message.channel.mention}"
            )

        except discord.Forbidden:

            print("Keine Rechte für Timeout.")

            await send_log(
                "❌ Keine Rechte für Timeout."
            )

        except Exception as e:

            print(f"Fehler: {e}")

            await send_log(
                f"❌ Fehler: {e}"
            )

    await bot.process_commands(message)

# Voice Rollen System
@bot.event
async def on_voice_state_update(member, before, after):

    guild = member.guild
    rolle = discord.utils.get(
        guild.roles,
        name=ROLLEN_NAME
    )

    if rolle is None:

        print("Rolle nicht gefunden")

        await send_log(
            "❌ Rolle nicht gefunden."
        )

        return

    # Alle Voice-Channels prüfen
    for channel in guild.voice_channels:

        menschen = [
            m for m in channel.members
            if not m.bot
        ]

        # Genau 1 Person
        if len(menschen) == 1:

            user = menschen[0]

            if rolle not in user.roles:

                await user.add_roles(rolle)

                print(
                    f"{user} hat die Rolle bekommen"
                )

                await send_log(
                    f"🎧 {user} hat die Rolle "
                    f"'{ROLLEN_NAME}' bekommen."
                )

        # Mehr als 1 Person
        else:

            for user in menschen:

                if rolle in user.roles:

                    await user.remove_roles(rolle)

                    print(
                        f"{user} Rolle entfernt"
                    )

                    await send_log(
                        f"❌ {user} Rolle "
                        f"'{ROLLEN_NAME}' entfernt."
                    )

# Keep Alive starten
keep_alive()

# Bot starten
bot.run(TOKEN)
