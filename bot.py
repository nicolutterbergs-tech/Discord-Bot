import discord
from discord.ext import commands
import re
import os
import sys
from datetime import timedelta
import subprocess
from flask import Flask
from threading import Thread
import signal
import asyncio

# Flask Webserver für UptimeRobot
#app = Flask('')

@app.route('/')
def home():
    return "Bot läuft!"

def run():
    app.run(host='0.0.0.0', port=5000)

#def keep_alive():
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


# 🔁 NEU
@bot.event
async def on_disconnect():
    print("🔴 Bot disconnected!")

    try:
        await send_log("🔴 Bot hat die Verbindung verloren / geht möglicherweise in Sleep-Modus.")
    except:
        pass


# 🔁 NEU
@bot.event
async def on_resumed():
    print("🟢 Bot hat Verbindung wiederhergestellt!")

    try:
        await send_log("🟢 Bot hat sich wieder verbunden (Resumed).")
    except:
        pass


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
            await message.delete()

            timeout_duration = timedelta(days=7)

            await message.author.timeout(
                timeout_duration,
                reason="Posting links in chat"
            )

            try:
                await message.author.send(
                    f"⚠️ **Du wurdest verwarnt!**\n\n"
                    f"Du wurdest auf dem Server für **7 Tage** getimeoutet, "
                    f"weil du einen Link gepostet hast.\n\n"
                    f"📨 Deine Nachricht:\n{message.content}"
                )
            except discord.Forbidden:
                pass

            await send_log(
                f"⚠️ **Verwarnung ausgesprochen**\n\n"
                f"👤 User: {message.author.mention} (`{message.author}`)\n"
                f"⏱️ Timeout: 7 Tage\n"
                f"📨 Nachricht: {message.content}\n"
                f"📍 Channel: {message.channel.mention}"
            )

        except discord.Forbidden:

            print("Keine Rechte für Timeout.")

            await send_log("❌ Keine Rechte für Timeout.")

        except Exception as e:

            print(f"Fehler: {e}")

            await send_log(f"❌ Fehler: {e}")

    await bot.process_commands(message)


# Voice Rollen System
@bot.event
async def on_voice_state_update(member, before, after):

    guild = member.guild
    rolle = discord.utils.get(guild.roles, name=ROLLEN_NAME)

    if rolle is None:

        print("Rolle nicht gefunden")

        await send_log("❌ Rolle nicht gefunden.")

        return

    for channel in guild.voice_channels:

        menschen = [m for m in channel.members if not m.bot]

        if len(menschen) == 1:

            user = menschen[0]

            if rolle not in user.roles:

                await user.add_roles(rolle)

                print(f"{user} hat die Rolle bekommen")

                await send_log(
                    f"🎧 {user} hat die Rolle '{ROLLEN_NAME}' bekommen."
                )

        else:

            for user in menschen:

                if rolle in user.roles:

                    await user.remove_roles(rolle)

                    print(f"{user} Rolle entfernt")

                    await send_log(
                        f"❌ {user} Rolle '{ROLLEN_NAME}' entfernt."
                    )


# 🔁 NEU (Shutdown Handler)
def handle_shutdown(signum, frame):
    print("⚠️ Bot wird beendet!")

    try:
        loop = bot.loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                send_log("⚠️ Bot wird beendet (Shutdown / Sleep / Restart)."),
                loop
            )
    except:
        pass


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)




# =========================
# /write SYSTEM (EINFACH)
# =========================
reaction_roles = {}

class WriteModal(discord.ui.Modal, title="Nachricht erstellen"):
    message_text = discord.ui.TextInput(
        label="Nachricht",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.channel.send(self.message_text.value)
        await interaction.response.send_message(
            "✅ Nachricht gesendet.",
            ephemeral=True
        )

@bot.tree.command(
    name="write",
    description="Nachricht senden"
)
async def write(interaction: discord.Interaction):

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            "❌ Keine Berechtigung.",
            ephemeral=True
        )
        return

    await interaction.response.send_modal(WriteModal())

# Keep Alive starten
keep_alive()


# 🔄 ERSETZT (Bot Start sicherer gemacht)
try:
    bot.run(TOKEN)

except KeyboardInterrupt:
    print("⚠️ Bot manuell gestoppt")

except Exception as e:
    print(f"❌ Kritischer Fehler: {e}")

    try:
        asyncio.run(send_log(f"❌ Bot abgestürzt: {e}"))
    except:
        pass
