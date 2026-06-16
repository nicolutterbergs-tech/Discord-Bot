import discord
from discord.ext import commands
import re
import os
from datetime import timedelta
from flask import Flask
from threading import Thread
from datetime import timedelta

# =========================
# KEEP ALIVE
# =========================
app = Flask("")

@app.route("/")
def home():
    return "Bot läuft!"

def run():
    app.run(host="0.0.0.0", port=5000)

def keep_alive():
    Thread(target=run).start()


# =========================
# TOKEN
# =========================
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    print("❌ TOKEN fehlt!")
    exit()


# =========================
# SETTINGS
# =========================
LOG_CHANNEL_ID = 1509957389674348717
PREFIX = "!"

CREATOR_CHANNEL_ID = 1516541407853281331
CATEGORY_ID = 1349426167266017384

# =========================
# BOT SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# =========================
# Voice
# =========================
@bot.event
async def on_voice_state_update(member, before, after):

    # === Creator Channel betreten ===
    if after.channel and after.channel.id == CREATOR_CHANNEL_ID:

        guild = member.guild
        category = guild.get_channel(CATEGORY_ID)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
            member: discord.PermissionOverwrite(
                connect=True,
                manage_channels=True,
                move_members=True,
                mute_members=True,
                deafen_members=True
            )
        }

        channel = await guild.create_voice_channel(
            name=f"🔊 {member.display_name}'s Room",
            category=category,
            overwrites=overwrites
        )

        # User direkt in neuen Channel verschieben
        await member.move_to(channel)

        # Channel merken (wichtig für späteres Löschen)
        if not hasattr(bot, "temp_channels"):
            bot.temp_channels = {}

        bot.temp_channels[channel.id] = member.id


    # === Channel löschen wenn leer ===
    if before.channel:

        channel = before.channel

        if hasattr(bot, "temp_channels") and channel.id in bot.temp_channels:

            if len(channel.members) == 0:
                await channel.delete()
                del bot.temp_channels[channel.id]


# =========================
# LOG FUNCTION
# =========================
async def send_log(content):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if channel:
        try:
            await channel.send(content)
        except Exception as e:
            print("Log Fehler:", e)


# =========================
# REGEX
# =========================
link_regex = re.compile(
    r"(https?://|www\.|discord\.gg/|discord\.com/invite/)"
)


# =========================
#  Rollen vergabe
# =========================
ROLE_NAME = "Alleine Im Call"


async def send_log_embed(embed):
    channel = bot.get_channel(LOG_CHANNEL_ID)

    if channel:
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print("Log Fehler:", e)


async def log_role_given(member, role):
    embed = discord.Embed(
        title="➕ Rolle vergeben",
        color=discord.Color.green()
    )

    embed.add_field(
        name="Mitglied",
        value=f"{member.mention}\n`{member}`",
        inline=True
    )

    embed.add_field(
        name="Rolle",
        value=role.mention,
        inline=True
    )

    embed.set_footer(text=f"User ID: {member.id}")

    await send_log_embed(embed)


async def log_role_removed(member, role):
    embed = discord.Embed(
        title="➖ Rolle entfernt",
        color=discord.Color.red()
    )

    embed.add_field(
        name="Mitglied",
        value=f"{member.mention}\n`{member}`",
        inline=True
    )

    embed.add_field(
        name="Rolle",
        value=role.mention,
        inline=True
    )

    embed.set_footer(text=f"User ID: {member.id}")

    await send_log_embed(embed)


async def update_alone_role(channel):
    if channel is None:
        return

    role = discord.utils.get(channel.guild.roles, name=ROLE_NAME)

    if role is None:
        return

    aktive_user = []

    for member in channel.members:
        voice = member.voice

        if voice is None:
            continue

        if (
            not voice.self_mute
            and not voice.self_deaf
            and not voice.mute
            and not voice.deaf
        ):
            aktive_user.append(member)

    ziel_user = None

    if len(channel.members) == 1:
        ziel_user = channel.members[0]

    elif len(aktive_user) == 1:
        ziel_user = aktive_user[0]

    for member in channel.members:

        hat_rolle = role in member.roles
        soll_rolle_haben = member == ziel_user

        if soll_rolle_haben and not hat_rolle:
            try:
                await member.add_roles(
                    role,
                    reason="Alleine im Call"
                )

                await log_role_given(member, role)

            except Exception as e:
                print(e)

        elif not soll_rolle_haben and hat_rolle:
            try:
                await member.remove_roles(
                    role,
                    reason="Nicht mehr alleine im Call"
                )

                await log_role_removed(member, role)

            except Exception as e:
                print(e)


@bot.event
async def on_voice_state_update(member, before, after):

    if before.channel:
        await update_alone_role(before.channel)

    if after.channel and after.channel != before.channel:
        await update_alone_role(after.channel)

# =========================
# READY
# =========================
@bot.event
async def on_ready():
    print(f"✅ Bot online als {bot.user}")

    await send_log("🟢 Bot gestartet")


# =========================
# LINK PROTECTION + DM TICKET SYSTEM
# =========================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if not message.author.guild_permissions.administrator:
        if link_regex.search(message.content):
            try:
                original_content = message.content

                await message.delete()

                # =========================
                # TIMEOUT
                # =========================
                td = timedelta(days=1)
                print("DEBUG TIMEOUT:", td)
                
                    await message.author.timeout(td, reason="Link Spam")

                # =========================
                # DM EMBED
                # =========================
                embed = discord.Embed(
                    title="🚨 Moderationsmaßnahme",
                    description=(
                        f"Hallo {message.author.mention},\n\n"
                        f"du wurdest auf **{message.guild.name}** "
                        f"für 1 Tag eingeschränkt."
                    ),
                    color=discord.Color.orange()
                )

                embed.add_field(name="📋 Grund", value="Link Spam", inline=True)
                embed.add_field(name="⏳ Dauer", value="1 Tag", inline=True)

                embed.add_field(
                    name="🔗 Inhalt",
                    value=original_content[:1024],
                    inline=False
                )

                embed.set_footer(text="Automatische Moderation")

                if message.guild.icon:
                    embed.set_thumbnail(url=message.guild.icon.url)


                # =========================
                # DM SENDEN
                # =========================
                try:
                    dm_msg = await message.author.send(embed=embed)
                except discord.Forbidden:
                    dm_msg = None


                # =========================
                # DM TICKET SYSTEM
                # =========================
                class AppealView(discord.ui.View):
                    def __init__(self):
                        super().__init__(timeout=None)

                    @discord.ui.button(
                        label="📝 Einspruch starten",
                        style=discord.ButtonStyle.primary
                    )
                    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):

                        await interaction.response.send_message(
                            "✍️ Bitte schreibe jetzt deinen Einspruch hier in den Chat.\n"
                            "Der Bot sendet ihn automatisch an das Moderationsteam.",
                            ephemeral=True
                        )

                        def check(m):
                            return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

                        try:
                            msg = await bot.wait_for("message", timeout=300.0, check=check)

                            await send_log(
                                f"📩 EINSPRUCH ERHALTEN\n"
                                f"👤 User: {interaction.user} ({interaction.user.id})\n"
                                f"🏛️ Server: {message.guild.name}\n"
                                f"📄 Inhalt: {msg.content}\n"
                                f"🔗 Original Nachricht: {original_content}"
                            )

                            await interaction.user.send(
                                "✅ Dein Einspruch wurde an das Moderationsteam weitergeleitet."
                            )

                        except Exception:
                            await interaction.user.send("⏳ Zeit abgelaufen. Bitte erneut versuchen.")


                # Button nur in DM schicken
                if dm_msg:
                    try:
                        await message.author.send(view=AppealView())
                    except:
                        pass


                # =========================
                # LOG
                # =========================
                await send_log(
                    f"🚨 Link gelöscht & Timeout vergeben\n"
                    f"👤 User: {message.author} ({message.author.id})\n"
                    f"📄 Nachricht: {original_content}\n"
                    f"📍 Kanal: {message.channel.mention}\n"
                    f"⏰ Timeout: 1 Tag"
                )

            except Exception as e:
                await send_log(f"❌ Fehler: {e}")

    await bot.process_commands(message)


# =========================
# START
# =========================
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
