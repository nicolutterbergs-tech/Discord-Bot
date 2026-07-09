import asyncio
import sys
import discord
from discord import app_commands
from discord.ext import commands
import re
import os
import shutil
from datetime import timedelta
from flask import Flask
from threading import Thread
import traceback
import io
import json
from dotenv import load_dotenv
import platform
import discord


try:
    import nacl  # noqa: F401
except Exception as exc:
    print(f"PyNaCl import failed: {exc}")
    raise

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
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def load_token() -> str | None:
    token = os.getenv("TOKEN")
    if token:
        return token

    config_path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                token = data.get("token")
                if token:
                    return token
        except Exception as exc:
            print(f"⚠️ Fehler beim Lesen von config.json: {exc}")

    return None


TOKEN = load_token()

if not TOKEN:
    print("❌ TOKEN fehlt!")
    exit()


# =========================
# SETTINGS
# =========================
LOG_CHANNEL_ID = 1509957389674348717
PREFIX = "!"
CREATOR_CHANNEL_ID = 1516541407853281331
TRANSCRIPT_CHANNEL_ID = 1349444934121553971


# =========================
# BOT SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


def load_discord_opus() -> None:
    try:
        if not discord.opus.is_loaded():
            if platform.system() == "Windows":
                discord.opus.load_opus("libopus-0.x64.dll")
            else:
                # Linux
                discord.opus.load_opus("libopus.so.0")

        if discord.opus.is_loaded():
            print("✅ Opus erfolgreich geladen.")
        else:
            print("❌ Opus konnte nicht geladen werden.")

    except Exception as exc:
        print(f"⚠️ Opus-Ladung fehlgeschlagen: {exc}")


load_discord_opus()


def build_invite_url() -> str:
    app_id = getattr(bot, "application_id", None)
    if not app_id:
        return "Bot-Anwendung noch nicht geladen."
    return (
        f"https://discord.com/oauth2/authorize?client_id={app_id}"
        "&permissions=8&scope=bot%20applications.commands"
    )


@bot.command(name="invite")
async def invite_command(ctx: commands.Context):
    await ctx.send(build_invite_url())


# =========================
# MUSIC
# =========================
try:
    import yt_dlp as youtube_dl
except ImportError:
    try:
        import youtube_dl
    except ImportError:
        youtube_dl = None

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "nocheckcertificate": True,
    "ignoreerrors": True,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn"
}


def resolve_ffmpeg_executable() -> str | None:
    env_path = os.getenv("FFMPEG_PATH")
    candidates = []
    if env_path:
        candidates.append(env_path)

    candidates.extend([
        shutil.which("ffmpeg"),
        os.path.join(BASE_DIR, "ffmpeg.exe"),
        os.path.join(BASE_DIR, "bin", "ffmpeg.exe"),
        os.path.join(os.path.expanduser("~"), "ffmpeg", "bin", "ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ])

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def is_audio_url(query: str) -> bool:
    return query.startswith("http://") or query.startswith("https://")


def get_voice_error_message(exc: Exception) -> str:
    message = str(exc).lower()
    if "pynacl" in message or "nacl" in message:
        return "Die Sprachunterstützung ist nicht verfügbar. Bitte installiere PyNaCl über pip."
    if "ffmpeg" in message or "avcodec" in message or "ffprobe" in message:
        return "FFmpeg ist auf dem Server nicht verfügbar. Bitte installiere FFmpeg und stelle es im Pfad bereit."
    if "permission" in message or "permissions" in message:
        return "Der Bot hat keine ausreichenden Rechte für den Voice-Channel. Bitte prüfe die Berechtigungen."
    if "not connected" in message or "voice" in message:
        return "Der Bot konnte keine Sprachverbindung aufbauen. Bitte prüfe den Voice-Channel und die Bot-Rechte."
    return str(exc)


async def ensure_voice_channel_ready(channel: discord.VoiceChannel):
    if channel is None:
        raise RuntimeError("Kein Voice-Channel gefunden.")

    if not discord.opus.is_loaded():
        load_discord_opus()

    bot_member = channel.guild.me
    if bot_member is None:
        raise RuntimeError("Bot-Mitglied konnte nicht ermittelt werden.")

    permissions = channel.permissions_for(bot_member)
    if not permissions.connect:
        raise RuntimeError("Der Bot darf den Voice-Channel nicht betreten.")
    if not permissions.speak:
        raise RuntimeError("Der Bot darf im Voice-Channel nicht sprechen.")

    return channel


async def create_ytdl_source(search: str):
    if youtube_dl is None:
        raise RuntimeError(
            "Musikwiedergabe von YouTube erfordert die Installation von yt_dlp oder youtube_dl."
        )

    loop = asyncio.get_running_loop()

    def extract():
        return youtube_dl.YoutubeDL(YTDL_OPTIONS).extract_info(search, download=False)

    data = await loop.run_in_executor(None, extract)
    if data is None:
        raise RuntimeError("Keine Audioquelle gefunden.")

    if "entries" in data:
        data = next((entry for entry in data["entries"] if entry), None)
        if data is None:
            raise RuntimeError("Keine Audioquelle gefunden.")

    url = data.get("url")
    title = data.get("title") or search
    if url is None:
        raise RuntimeError("Konnte die Audio-URL nicht extrahieren.")

    return url, title


async def get_audio_source(search: str):
    if is_audio_url(search):
        if youtube_dl is not None:
            try:
                return await create_ytdl_source(search)
            except Exception:
                return search, os.path.basename(search)
        return search, os.path.basename(search)

    if youtube_dl is not None:
        return await create_ytdl_source(search)

    raise RuntimeError(
        "Für die Musiksuche benötigst du yt_dlp oder youtube_dl. Alternativ nutze einen direkten MP3/OGG-Link."
    )


@bot.tree.command(name="join", description="Bringt mich in deinen Voice-Channel.")
async def join_slash(interaction: discord.Interaction):
    if interaction.user.voice is None or interaction.user.voice.channel is None:
        return await interaction.response.send_message("Du musst zuerst in einem Voice-Channel sein.", ephemeral=True)

    try:
        channel = await ensure_voice_channel_ready(interaction.user.voice.channel)
        voice_client = interaction.guild.voice_client
        if voice_client is not None:
            await voice_client.move_to(channel)
        else:
            load_discord_opus()
            await channel.connect()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(repr(e))
        await interaction.response.send_message(f"Ich bin dem Kanal {channel.mention} beigetreten.")


@bot.tree.command(name="leave", description="Lässt mich den Voice-Channel verlassen.")
async def leave_slash(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client is None:
        return await interaction.response.send_message("Ich bin in keinem Voice-Channel.", ephemeral=True)

    await voice_client.disconnect()
    await interaction.response.send_message("Ich habe den Voice-Channel verlassen.")


@bot.tree.command(name="play", description="Spielt Musik von YouTube oder einer URL ab.")
@app_commands.describe(query="YouTube-URL oder Suchbegriff")
async def play_slash(interaction: discord.Interaction, query: str):
    if interaction.user.voice is None or interaction.user.voice.channel is None:
        return await interaction.response.send_message("Du musst zuerst in einem Voice-Channel sein.", ephemeral=True)

    try:
        await interaction.response.defer(ephemeral=True)
    except discord.errors.NotFound:
        return

    channel = interaction.user.voice.channel
    voice_client = interaction.guild.voice_client

    try:
        channel = await ensure_voice_channel_ready(channel)
        if voice_client is None:
            load_discord_opus()
            voice_client = await channel.connect()
        elif voice_client.channel != channel:
            await voice_client.move_to(channel)

        if voice_client.is_playing():
            voice_client.stop()

        source_url, title = await get_audio_source(query)
    except Exception as e:
        print(f"Play voice setup failed: {type(e).__name__}: {e}")
        try:
            await interaction.followup.send(f"Fehler beim Laden der Audioquelle: {get_voice_error_message(e)}", ephemeral=True)
        except discord.errors.NotFound:
            pass
        return

    try:
        ffmpeg_path = resolve_ffmpeg_executable()
        if not ffmpeg_path:
            raise RuntimeError("FFmpeg ist nicht verfügbar. Bitte installiere FFmpeg und stelle es im Pfad bereit.")

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(source_url, executable=ffmpeg_path, **FFMPEG_OPTIONS),
            volume=0.5
        )
        voice_client.play(source)
        try:
            await interaction.followup.send(f"🎶 Jetzt wird abgespielt: **{title}**", ephemeral=True)
        except discord.errors.NotFound:
            pass
    except Exception as e:
        try:
            await interaction.followup.send(f"Fehler beim Abspielen: {get_voice_error_message(e)}", ephemeral=True)
        except discord.errors.NotFound:
            pass


@bot.tree.command(name="pause", description="Pausiert die aktuelle Wiedergabe.")
async def pause_slash(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client is None or not voice_client.is_playing():
        return await interaction.response.send_message("Im Moment wird keine Musik abgespielt.", ephemeral=True)

    voice_client.pause()
    await interaction.response.send_message("Musik pausiert.")


@bot.tree.command(name="resume", description="Setzt die pausierte Wiedergabe fort.")
async def resume_slash(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client is None or not voice_client.is_paused():
        return await interaction.response.send_message("Es ist nichts pausiert.", ephemeral=True)

    voice_client.resume()
    await interaction.response.send_message("Musik fortgesetzt.")


@bot.tree.command(name="stop", description="Stoppt die Wiedergabe und verlässt den Voice-Channel.")
async def stop_slash(interaction: discord.Interaction):
    voice_client = interaction.guild.voice_client
    if voice_client is None or not voice_client.is_connected():
        return await interaction.response.send_message("Ich bin in keinem Voice-Channel.", ephemeral=True)

    voice_client.stop()
    await voice_client.disconnect()
    await interaction.response.send_message("Musik wurde gestoppt und ich habe den Voice-Channel verlassen.")


bot.temp_channels = {}
bot.ticket_channels = {}
bot.reaction_roles = {}
bot.active_temp_views = []
bot.active_views = []
bot.tempvoice_setups = {}

TICKET_CATEGORY_NAME = "Support Tickets"
TEMPVOICE_CATEGORY_NAME = "Temp Voice"
TEMPVOICE_OVERLAY_CHANNEL_NAME = "tempvoice-overlay"
TEMPVOICE_CREATOR_CHANNEL_NAME = "➕ Create Voice"
TICKET_PANEL_CHANNEL_NAME = "🎫ticket"
TICKET_CHANNEL_PREFIX = "ticket-"


@bot.tree.command(name="ping", description="Antwortet mit Pong")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")


@bot.tree.command(name="vcdebug", description="Zeigt Voice-Channel-Status und Temp-Channel-Daten")
async def vcdebug(interaction: discord.Interaction):
    member = resolve_member(interaction.user, interaction.guild)
    channel = member.voice.channel if getattr(member, "voice", None) else None
    temp = is_temp_channel(channel)
    data = get_temp_channel_data(channel)
    keys = list(bot.temp_channels.keys())
    msg = (
        f"voice_channel={channel}\n"
        f"channel_id={channel.id if channel else None}\n"
        f"is_temp={temp}\n"
        f"temp_data={data}\n"
        f"known_temp_channel_ids={keys[:50]}"
    )
    await interaction.response.send_message(f"```\n{msg}\n```")


@bot.tree.command(name="sync_commands", description="Synchronisiert die Slash-Commands neu.")
async def sync_commands(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        return await interaction.response.send_message("Nur Moderatoren können diesen Befehl nutzen.", ephemeral=True)

    try:
        await bot.tree.sync(guild=interaction.guild)
        await interaction.response.send_message("Slash-Commands wurden neu synchronisiert.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"Fehler beim Synchronisieren: {e}", ephemeral=True)


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("Unbekannter Befehl. Versuch `!ping`.")
        return
    print(f"Command Error: {type(error).__name__}: {error}")
    try:
        await ctx.send(f"Fehler: {type(error).__name__}: {error}")
    except Exception:
        pass


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
    r"(https?://|www\.|discord\.gg/|discord\.com/invite/)",
    re.IGNORECASE
)

invite_regex = re.compile(
    r"(?:discord(?:app)?\.gg/|discord\.com/invite/)",
    re.IGNORECASE
)

bad_word_list = {
    "arsch", "scheiße", "scheisse", "fuck", "shit", "kacke", "hure", "dummkopf"
}
bad_word_regex = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in bad_word_list) + r")\b",
    re.IGNORECASE
)

MAX_MENTIONS = 5
CAPS_RATIO_THRESHOLD = 0.70
CAPS_MIN_LENGTH = 10


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


def get_temp_channel_data(channel):
    return bot.temp_channels.get(channel.id) if channel else None


def get_tempvoice_setup(guild):
    return bot.tempvoice_setups.get(guild.id) if guild else None


def get_tempvoice_creator_channel(guild):
    setup = get_tempvoice_setup(guild)
    if setup:
        channel = guild.get_channel(setup.get("creator_channel_id")) if guild else None
        if channel:
            return channel
    return guild.get_channel(CREATOR_CHANNEL_ID) if guild else None


async def ensure_tempvoice_setup(guild, interaction=None):
    setup = get_tempvoice_setup(guild) or {}

    category = discord.utils.get(guild.categories, name=TEMPVOICE_CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(TEMPVOICE_CATEGORY_NAME, reason="Temp Voice Setup")

    creator_channel = None
    if setup.get("creator_channel_id"):
        creator_channel = guild.get_channel(setup["creator_channel_id"])
    if creator_channel is None:
        creator_channel = discord.utils.get(guild.voice_channels, name=TEMPVOICE_CREATOR_CHANNEL_NAME)
    if creator_channel is None:
        creator_channel = await guild.create_voice_channel(
            name=TEMPVOICE_CREATOR_CHANNEL_NAME,
            category=category,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(view_channel=True, connect=True)
            },
            reason="Temp Voice Creator Channel erstellt"
        )

    overlay_channel = None
    if setup.get("overlay_channel_id"):
        overlay_channel = guild.get_channel(setup["overlay_channel_id"])
    if overlay_channel is None:
        overlay_channel = discord.utils.get(guild.text_channels, name=TEMPVOICE_OVERLAY_CHANNEL_NAME)
    if overlay_channel is None:
        overlay_channel = await guild.create_text_channel(
            name=TEMPVOICE_OVERLAY_CHANNEL_NAME,
            category=category,
            overwrites={
                guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
            },
            reason="Temp Voice Overlay Channel erstellt"
        )

    embed = discord.Embed(
        title="🎛️ Temp Voice Steuerung",
        description=(
            "Klicke auf die Buttons, um deinen Temp Voice zu konfigurieren.\n"
            "Trete in den Creator-Channel ein, um deinen eigenen Temp Voice zu erstellen."
        ),
        color=discord.Color.blurple()
    )
    embed.add_field(name="Schnell starten", value="Name / Limit / Region / Chat / Privacy", inline=False)
    embed.add_field(name="Zugriff verwalten", value="Trust / Untrust / Invite / Block / Unblock", inline=False)
    embed.add_field(name="Sonstiges", value="Kick / Claim / Transfer / Delete", inline=False)

    view = TempVCOverlay()
    bot.active_temp_views.append(view)
    bot.add_view(view)

    message = None
    if setup.get("overlay_message_id"):
        try:
            message = await overlay_channel.fetch_message(setup["overlay_message_id"])
            await message.edit(embed=embed, view=view)
        except Exception:
            message = None

    if message is None:
        message = await overlay_channel.send(embed=embed, view=view)

    bot.tempvoice_setups[guild.id] = {
        "creator_channel_id": creator_channel.id,
        "overlay_channel_id": overlay_channel.id,
        "overlay_message_id": message.id,
    }

    return creator_channel, overlay_channel, message


def get_voice_temp_channel_member(member):
    channel = member.voice.channel if getattr(member, "voice", None) else None
    return channel if is_temp_channel(channel) else None


def is_temp_channel(channel):
    result = channel is not None and channel.id in bot.temp_channels
    try:
        cid = channel.id if channel is not None else None
    except Exception:
        cid = None
    print(f"is_temp_channel: channel_id={cid} known={result}")
    return result


def is_ticket_channel(channel):
    return channel is not None and channel.id in bot.ticket_channels


def get_ticket_owner(channel):
    return bot.ticket_channels.get(channel.id)


def get_existing_ticket_channel(guild, owner_id):
    for channel_id, user_id in list(bot.ticket_channels.items()):
        if user_id != owner_id:
            continue
        channel = guild.get_channel(channel_id)
        if channel is None:
            bot.ticket_channels.pop(channel_id, None)
            continue
        return channel
    return None


def get_ticket_category(guild):
    category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
    return category


def find_ticket_panel_channel(guild):
    return discord.utils.get(guild.text_channels, name=TICKET_PANEL_CHANNEL_NAME)


def sanitize_channel_name(name):
    sanitized = re.sub(r"[^a-z0-9\-]", "-", name.lower())
    return re.sub(r"-+", "-", sanitized).strip("-")[:80]


def staff_roles(guild):
    return [role for role in guild.roles if role.permissions.administrator or role.permissions.manage_guild or role.permissions.manage_channels or role.permissions.manage_messages]


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket schließen", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="ticket_close")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not is_ticket_channel(channel):
            return await interaction.response.send_message("Dieser Kanal ist kein Ticket-Kanal.", ephemeral=True)

        owner_id = get_ticket_owner(channel)
        if owner_id != interaction.user.id and not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Nur der Ticket-Ersteller oder ein Administrator kann das Ticket schließen.", ephemeral=True)

        await interaction.response.send_message("Ticket wird geschlossen...", ephemeral=True)
        try:
            await create_ticket_transcript(channel)
        except Exception as e:
            print(f"Fehler beim Erstellen des Transkripts: {e}")
        bot.ticket_channels.pop(channel.id, None)
        try:
            await channel.delete()
        except Exception as e:
            print(f"Ticket löschen fehlgeschlagen: {e}")


async def create_ticket_transcript(channel: discord.TextChannel):
    """Fetch channel history and send both a TXT transcript and a JSON export (including bot state) to the transcript channel."""
    try:
        messages = []
        async for m in channel.history(limit=None, oldest_first=True):
            messages.append(m)

        # Plain text transcript lines
        lines = []
        # Structured messages for JSON
        structured = []

        for m in messages:
            timestamp = m.created_at.isoformat()
            author_str = f"{m.author} ({m.author.id})"
            content = m.content or ""
            attachments = []
            for a in m.attachments:
                attachments.append({
                    "filename": a.filename,
                    "url": a.url,
                    "size": getattr(a, "size", None)
                })

            if attachments:
                attach_text = "\n" + "\n".join(f"[attachment] {att['url']}" for att in attachments)
            else:
                attach_text = ""

            lines.append(f"[{timestamp}] {author_str}: {content}{attach_text}")

            structured.append({
                "id": m.id,
                "timestamp": timestamp,
                "author": {"id": m.author.id, "name": str(m.author)},
                "content": content,
                "attachments": attachments,
                "pinned": m.pinned
            })

        txt_body = "(kein Inhalt)" if not lines else "\n".join(lines)
        txt_bio = io.BytesIO(txt_body.encode("utf-8"))
        txt_bio.seek(0)
        txt_filename = f"transcript-{channel.name}-{channel.id}.txt"

        # JSON export with channel metadata and bot state snapshot
        json_data = {
            "channel": {
                "id": channel.id,
                "name": channel.name,
                "topic": getattr(channel, "topic", None),
                "created_at": channel.created_at.isoformat() if getattr(channel, "created_at", None) else None
            },
            "guild": {
                "id": channel.guild.id if channel.guild else None,
                "name": channel.guild.name if channel.guild else None
            },
            "messages": structured,
            "ticket_owner_id": bot.ticket_channels.get(channel.id),
            "bot_state": {
                "ticket_channels": bot.ticket_channels,
                "temp_channels": bot.temp_channels
            }
        }

        json_body = json.dumps(json_data, ensure_ascii=False, default=str, indent=2)
        json_bio = io.BytesIO(json_body.encode("utf-8"))
        json_bio.seek(0)
        json_filename = f"transcript-{channel.name}-{channel.id}.json"

        target = bot.get_channel(TRANSCRIPT_CHANNEL_ID)
        if target is None:
            try:
                target = await bot.fetch_channel(TRANSCRIPT_CHANNEL_ID)
            except Exception:
                target = None

        embed = discord.Embed(
            title="🎫 Ticket-Export",
            description=f"Transkript + JSON-Export für {channel.name} ({channel.id})",
            color=discord.Color.greyple()
        )

        owner_id = bot.ticket_channels.get(channel.id)
        if owner_id:
            embed.add_field(name="Ersteller ID", value=str(owner_id), inline=True)

        if target:
            try:
                await target.send(embed=embed, files=[discord.File(txt_bio, txt_filename), discord.File(json_bio, json_filename)])
            except Exception as e:
                print(f"Fehler beim Senden des Exports: {e}")
        else:
            print("Transkript-Kanal nicht gefunden; Export nicht gesendet.")
    except Exception as e:
        print(f"create_ticket_transcript error: {e}")



def is_temp_owner(member, channel):
    data = get_temp_channel_data(channel)
    return data is not None and data["owner"] == member.id


def get_voice_temp_channel(ctx):
    channel = ctx.author.voice.channel if ctx.author.voice else None
    return channel if is_temp_channel(channel) else None


def get_member_voice_temp_channel(member):
    channel = None
    try:
        channel = member.voice.channel if member.voice else None
    except Exception as e:
        print(f"get_member_voice_temp_channel: error fetching voice for {member}: {e}")

    cid = channel.id if channel is not None else None
    print(f"get_member_voice_temp_channel: member={member} channel_id={cid}")
    return channel if is_temp_channel(channel) else None


def parse_member_guild_member(guild, text):
    text = text.strip()
    match = re.match(r"^<@!?(\d+)>$", text)
    if match:
        return guild.get_member(int(match.group(1)))
    if text.isdigit():
        return guild.get_member(int(text))
    return None


def resolve_member(user_or_member, guild=None):
    """Return a Guild Member if possible, otherwise return the original object.

    This helps when `interaction.user` may be a User proxy without voice state.
    """
    try:
        if guild is not None:
            member = guild.get_member(user_or_member.id)
            if member:
                return member
    except Exception:
        pass
    return user_or_member


class MemberActionModal(discord.ui.Modal, title="Temp Voice Mitglied"):
    member_text = discord.ui.TextInput(
        label="Mitglied",
        placeholder="@Benutzer oder ID",
        style=discord.TextStyle.short,
        required=True,
        max_length=100
    )

    def __init__(self, action: str):
        super().__init__()
        self.action = action

    async def on_submit(self, interaction: discord.Interaction):
        member = resolve_member(interaction.user, interaction.guild)
        channel = get_member_voice_temp_channel(member)
        if channel is None or not is_temp_owner(member, channel):
            return await interaction.response.send_message(
                "Nur der Besitzer kann diese Aktion ausführen.", ephemeral=True
            )

        target = parse_member_guild_member(interaction.guild, self.member_text.value)
        if target is None:
            return await interaction.response.send_message(
                "Benutzer nicht gefunden. Bitte verwende @Benutzer oder seine ID.", ephemeral=True
            )

        data = get_temp_channel_data(channel)
        if self.action == "trust":
            if target.id in data["trusted"]:
                return await interaction.response.send_message(
                    "Dieser Benutzer ist bereits trusted.", ephemeral=True
                )
            data["trusted"].append(target.id)
            await channel.set_permissions(target, connect=True, view_channel=True)
            return await interaction.response.send_message(
                f"{target.mention} ist jetzt trusted.", ephemeral=True
            )

        if self.action == "untrust":
            if target.id not in data["trusted"]:
                return await interaction.response.send_message(
                    "Dieser Benutzer ist nicht trusted.", ephemeral=True
                )
            data["trusted"].remove(target.id)
            await channel.set_permissions(target, overwrite=None)
            return await interaction.response.send_message(
                f"{target.mention} ist nicht mehr trusted.", ephemeral=True
            )

        if self.action == "invite":
            if target.id in data["invited"]:
                return await interaction.response.send_message(
                    "Dieser Benutzer wurde bereits eingeladen.", ephemeral=True
                )
            data["invited"].append(target.id)
            await channel.set_permissions(target, connect=True, view_channel=True)
            return await interaction.response.send_message(
                f"{target.mention} wurde eingeladen.", ephemeral=True
            )

        if self.action == "block":
            if target.id in data["blocked"]:
                return await interaction.response.send_message(
                    "Dieser Benutzer ist bereits blockiert.", ephemeral=True
                )
            data["blocked"].append(target.id)
            await channel.set_permissions(target, connect=False)
            if target.voice and target.voice.channel == channel:
                try:
                    await target.move_to(None)
                except Exception:
                    pass
            return await interaction.response.send_message(
                f"{target.mention} wurde blockiert.", ephemeral=True
            )

        if self.action == "unblock":
            if target.id not in data["blocked"]:
                return await interaction.response.send_message(
                    "Dieser Benutzer ist nicht blockiert.", ephemeral=True
                )
            data["blocked"].remove(target.id)
            await channel.set_permissions(target, overwrite=None)
            return await interaction.response.send_message(
                f"{target.mention} ist nicht mehr blockiert.", ephemeral=True
            )

        if self.action == "kick":
            if target.voice and target.voice.channel == channel:
                try:
                    await target.move_to(None)
                    return await interaction.response.send_message(
                        f"{target.mention} wurde gekickt.", ephemeral=True
                    )
                except Exception as e:
                    return await interaction.response.send_message(
                        f"Fehler beim Kicken: {e}", ephemeral=True
                    )
            return await interaction.response.send_message(
                "Dieser Benutzer ist nicht im Temp Voice.", ephemeral=True
            )

        if self.action == "transfer":
            if target.voice is None or target.voice.channel != channel:
                return await interaction.response.send_message(
                    "Der Benutzer muss im selben Temp Voice sein.", ephemeral=True
                )
            data["owner"] = target.id
            return await interaction.response.send_message(
                f"Besitz wurde an {target.mention} übertragen.", ephemeral=True
            )

        return await interaction.response.send_message(
            "Unbekannte Aktion.", ephemeral=True
        )


class NameModal(discord.ui.Modal, title="Temp Voice Name ändern"):
    name = discord.ui.TextInput(
        label="Neuer Name",
        placeholder="Neuer Raumname",
        required=True,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        member = resolve_member(interaction.user, interaction.guild)
        channel = get_member_voice_temp_channel(member)
        if channel is None or not is_temp_owner(member, channel):
            return await interaction.response.send_message(
                "Nur der Besitzer kann den Namen ändern.", ephemeral=True
            )
        data = get_temp_channel_data(channel)
        try:
            await channel.edit(name=self.name.value)
            if data.get("chat_channel_id"):
                chat_channel = interaction.guild.get_channel(data["chat_channel_id"])
                if chat_channel:
                    await chat_channel.edit(name=f"{self.name.value}-chat")
            await interaction.response.send_message(
                f"Name geändert zu `{self.name.value}`.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler beim Ändern des Namens: {e}", ephemeral=True
            )


class LimitModal(discord.ui.Modal, title="Temp Voice Limit setzen"):
    limit = discord.ui.TextInput(
        label="Maximale Nutzeranzahl",
        placeholder="0-99",
        required=True,
        max_length=3
    )

    async def on_submit(self, interaction: discord.Interaction):
        member = resolve_member(interaction.user, interaction.guild)
        channel = get_member_voice_temp_channel(member)
        if channel is None or not is_temp_owner(member, channel):
            return await interaction.response.send_message(
                "Nur der Besitzer kann das Limit setzen.", ephemeral=True
            )
        try:
            value = int(self.limit.value)
            if value < 0 or value > 99:
                raise ValueError()
            await channel.edit(user_limit=value)
            await interaction.response.send_message(
                f"Limit gesetzt auf {value}.", ephemeral=True
            )
        except ValueError:
            await interaction.response.send_message(
                "Bitte eine Zahl zwischen 0 und 99 eingeben.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler beim Setzen des Limits: {e}", ephemeral=True
            )


class RegionModal(discord.ui.Modal, title="Temp Voice Region setzen"):
    region = discord.ui.TextInput(
        label="Region",
        placeholder="z.B. europe, us-west",
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        member = resolve_member(interaction.user, interaction.guild)
        channel = get_member_voice_temp_channel(member)
        if channel is None or not is_temp_owner(member, channel):
            return await interaction.response.send_message(
                "Nur der Besitzer kann die Region ändern.", ephemeral=True
            )
        try:
            await channel.edit(rtc_region=self.region.value)
            await interaction.response.send_message(
                f"Region gesetzt auf `{self.region.value}`.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler beim Setzen der Region: {e}", ephemeral=True
            )


class TempVCOverlay(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        try:
            member = resolve_member(interaction.user, interaction.guild)
            channel = get_member_voice_temp_channel(member)
            print(f"interaction_check: user={interaction.user} resolved_member={member} user_id={interaction.user.id} channel={channel}")
            if channel is None:
                await interaction.response.send_message(
                    "Du musst dich zuerst in deinem Temp Voice befinden, um diese Aktion zu nutzen. "
                    "Betritt dazu den Erstelle-Channel und erstelle einen Temp Voice.",
                    ephemeral=True
                )
                return False
            return True
        except Exception as e:
            print(f"interaction_check error: {e}")
            try:
                await interaction.response.send_message("Interne Fehler beim Verarbeiten der Interaktion.", ephemeral=True)
            except Exception:
                pass
            return False

    async def _get_temp_channel(self, interaction):
        if not isinstance(interaction, discord.Interaction):
            print(f"_get_temp_channel: erwartet Interaction, erhalten {type(interaction).__name__}: {interaction}")
            return None

        member = resolve_member(interaction.user, interaction.guild)
        channel = get_member_voice_temp_channel(member)
        print(f"_get_temp_channel: user={interaction.user} resolved_member={member} channel={channel}")
        if channel is None:
            await interaction.response.send_message(
                "Du musst dich zuerst in deinem Temp Voice befinden, um diese Aktion zu nutzen. "
                "Betritt dazu den Erstelle-Channel und erstelle einen Temp Voice.",
                ephemeral=True
            )
        return channel

    async def _ask_for_input(self, interaction, prompt: str, timeout: float = 60.0):
        await interaction.response.send_message(prompt, ephemeral=True)

        def check(message):
            return (
                message.author == interaction.user
                and message.channel == interaction.channel
            )

        try:
            message = await bot.wait_for("message", timeout=timeout, check=check)
            content = message.content.strip()
            try:
                await message.delete()
            except Exception:
                pass
            return content
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "Zeit abgelaufen. Bitte erneut versuchen.",
                ephemeral=True
            )
            return None

    async def _ask_for_member(self, interaction, prompt: str):
        content = await self._ask_for_input(interaction, prompt)
        if not content:
            return None
        return parse_member_guild_member(interaction.guild, content)

    @discord.ui.button(label="Name", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="tempvc_name")
    async def name_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return

        value = await self._ask_for_input(interaction, "Bitte schreibe den neuen Namen für deinen Temp Voice Channel in den Chat.")
        if not value:
            return

        try:
            await channel.edit(name=value)
            data = get_temp_channel_data(channel)
            if data.get("chat_channel_id"):
                chat_channel = interaction.guild.get_channel(data["chat_channel_id"])
                if chat_channel:
                    await chat_channel.edit(name=f"{value}-chat")
            await interaction.followup.send(
                f"Name geändert zu `{value}`.", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Ändern des Namens: {e}", ephemeral=True
            )

    @discord.ui.button(label="Limit", style=discord.ButtonStyle.secondary, emoji="🔢", custom_id="tempvc_limit")
    async def limit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return

        try:
            await interaction.response.send_modal(LimitModal())
        except Exception as e:
            print(f"failed to send LimitModal: {e}")
            try:
                await interaction.response.send_message(f"Fehler: {e}", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Region", style=discord.ButtonStyle.secondary, emoji="🌍", custom_id="tempvc_region")
    async def region_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return

        try:
            await interaction.response.send_modal(RegionModal())
        except Exception as e:
            print(f"failed to send RegionModal: {e}")
            try:
                await interaction.response.send_message(f"Fehler: {e}", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Privacy", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="tempvc_privacy")
    async def privacy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        data = get_temp_channel_data(channel)
        data["private"] = not data.get("private", False)
        await apply_privacy_settings(channel, data)
        state = "aktiviert" if data["private"] else "deaktiviert"
        await interaction.response.send_message(
            f"Privatsphäre {state}.", ephemeral=True
        )

    @discord.ui.button(label="Waiting", style=discord.ButtonStyle.secondary, emoji="⏳", custom_id="tempvc_waiting")
    async def waiting_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        data = get_temp_channel_data(channel)
        data["waiting_room"] = not data.get("waiting_room", False)
        state = "aktiviert" if data["waiting_room"] else "deaktiviert"
        await interaction.response.send_message(
            f"Warteraum {state}.", ephemeral=True
        )

    @discord.ui.button(label="Chat", style=discord.ButtonStyle.secondary, emoji="💬", custom_id="tempvc_chat")
    async def chat_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        data = get_temp_channel_data(channel)
        if data.get("chat_channel_id"):
            chat_channel = interaction.guild.get_channel(data["chat_channel_id"])
            if chat_channel:
                await chat_channel.delete()
            data["chat_channel_id"] = None
            await interaction.response.send_message("Chat wurde deaktiviert.", ephemeral=True)
            return
        category = channel.category
        try:
            chat_channel = await interaction.guild.create_text_channel(
                name=f"{channel.name}-chat",
                category=category,
                overwrites={
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
                }
            )
            data["chat_channel_id"] = chat_channel.id
            await interaction.response.send_message(
                f"Chat erstellt: {chat_channel.mention}", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"Fehler beim Erstellen des Chats: {e}", ephemeral=True
            )

    @discord.ui.button(label="Trust", style=discord.ButtonStyle.success, emoji="✅", custom_id="tempvc_trust")
    async def trust_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        target = await self._ask_for_member(interaction, "Bitte sende die Erwähnung oder ID des Benutzers, der trusted werden soll.")
        if target is None:
            return
        data = get_temp_channel_data(channel)
        if target.id in data["trusted"]:
            return await interaction.followup.send("Dieser Benutzer ist bereits trusted.", ephemeral=True)
        data["trusted"].append(target.id)
        await channel.set_permissions(target, connect=True, view_channel=True)
        await interaction.followup.send(f"{target.mention} ist jetzt trusted.", ephemeral=True)

    @discord.ui.button(label="Untrust", style=discord.ButtonStyle.danger, emoji="❌", custom_id="tempvc_untrust")
    async def untrust_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        target = await self._ask_for_member(interaction, "Bitte sende die Erwähnung oder ID des Benutzers, der untrusted werden soll.")
        if target is None:
            return
        data = get_temp_channel_data(channel)
        if target.id not in data["trusted"]:
            return await interaction.followup.send("Dieser Benutzer ist nicht trusted.", ephemeral=True)
        data["trusted"].remove(target.id)
        await channel.set_permissions(target, overwrite=None)
        await interaction.followup.send(f"{target.mention} ist nicht mehr trusted.", ephemeral=True)

    @discord.ui.button(label="Invite", style=discord.ButtonStyle.primary, emoji="📩", custom_id="tempvc_invite")
    async def invite_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        target = await self._ask_for_member(interaction, "Bitte sende die Erwähnung oder ID des Benutzers, der eingeladen werden soll.")
        if target is None:
            return
        data = get_temp_channel_data(channel)
        if target.id in data["invited"]:
            return await interaction.followup.send("Dieser Benutzer wurde bereits eingeladen.", ephemeral=True)
        data["invited"].append(target.id)
        await channel.set_permissions(target, connect=True, view_channel=True)
        await interaction.followup.send(f"{target.mention} wurde eingeladen.", ephemeral=True)

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger, emoji="👢", custom_id="tempvc_kick")
    async def kick_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        target = await self._ask_for_member(interaction, "Bitte sende die Erwähnung oder ID des Benutzers, der gekickt werden soll.")
        if target is None:
            return
        if target.voice and target.voice.channel == channel:
            try:
                await target.move_to(None)
                await interaction.followup.send(f"{target.mention} wurde gekickt.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Fehler beim Kicken: {e}", ephemeral=True)
        else:
            await interaction.followup.send("Dieser Benutzer ist nicht im Temp Voice.", ephemeral=True)

    @discord.ui.button(label="Block", style=discord.ButtonStyle.danger, emoji="⛔", custom_id="tempvc_block")
    async def block_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        target = await self._ask_for_member(interaction, "Bitte sende die Erwähnung oder ID des Benutzers, der blockiert werden soll.")
        if target is None:
            return
        data = get_temp_channel_data(channel)
        if target.id in data["blocked"]:
            return await interaction.followup.send("Dieser Benutzer ist bereits blockiert.", ephemeral=True)
        data["blocked"].append(target.id)
        await channel.set_permissions(target, connect=False)
        if target.voice and target.voice.channel == channel:
            try:
                await target.move_to(None)
            except Exception:
                pass
        await interaction.followup.send(f"{target.mention} wurde blockiert.", ephemeral=True)

    @discord.ui.button(label="Unblock", style=discord.ButtonStyle.success, emoji="🚫", custom_id="tempvc_unblock")
    async def unblock_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        target = await self._ask_for_member(interaction, "Bitte sende die Erwähnung oder ID des Benutzers, der entblockt werden soll.")
        if target is None:
            return
        data = get_temp_channel_data(channel)
        if target.id not in data["blocked"]:
            return await interaction.followup.send("Dieser Benutzer ist nicht blockiert.", ephemeral=True)
        data["blocked"].remove(target.id)
        await channel.set_permissions(target, overwrite=None)
        await interaction.followup.send(f"{target.mention} ist nicht mehr blockiert.", ephemeral=True)

    @discord.ui.button(label="Transfer", style=discord.ButtonStyle.secondary, emoji="🔁", custom_id="tempvc_transfer")
    async def transfer_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        target = await self._ask_for_member(interaction, "Bitte sende die Erwähnung oder ID des neuen Besitzers.")
        if target is None:
            return
        data = get_temp_channel_data(channel)
        if target.voice is None or target.voice.channel != channel:
            return await interaction.followup.send("Der Benutzer muss im selben Temp Voice sein.", ephemeral=True)
        data["owner"] = target.id
        await interaction.followup.send(f"Besitz wurde an {target.mention} übertragen.", ephemeral=True)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="tempvc_delete")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        await cleanup_temp_channel(channel)
        await interaction.response.send_message(
            "Temp Voice wurde gelöscht.", ephemeral=True
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item) -> None:
        try:
            print("TempVCOverlay.on_error:")
            if isinstance(error, Exception):
                traceback.print_exception(type(error), error, error.__traceback__)
            else:
                print(f"Nicht-standardmäßiger Fehlerwert: {error}")

            print(f"item={item} interaction_user={getattr(interaction, 'user', None)} interaction_id={getattr(interaction, 'id', None)}")

            if isinstance(interaction, discord.Interaction):
                if interaction.response.is_done():
                    await interaction.followup.send(
                        f"Ein Fehler ist aufgetreten: {error}", ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        f"Ein Fehler ist aufgetreten: {error}", ephemeral=True
                    )
        except Exception as e:
            print("Failed sending error message to interaction:", e)
            traceback.print_exc()


@bot.tree.command(name="tempvc", description="Zeigt dein Temp Voice Overlay an.")
async def tempvc_slash(interaction: discord.Interaction):
    member = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(member)
    if channel is None:
        return await interaction.response.send_message(
            "Du musst in deinem Temp Voice sein, um das Overlay nutzen zu können.", ephemeral=True
        )
    if not is_temp_owner(member, channel):
        return await interaction.response.send_message(
            "Nur der Besitzer kann das Overlay nutzen.", ephemeral=True
        )

    embed = discord.Embed(
        title="🎛️ Temp Voice Einstellungen",
        description=(
            "Klicke auf die Buttons, um deinen Temp Voice einfach zu konfigurieren.\n"
            "Die Aktionen sind selbsterklärend und nur für dich als Besitzer verfügbar."
        ),
        color=discord.Color.blurple()
    )
    embed.add_field(name="Schnell starten", value="Name / Limit / Region / Chat / Privacy", inline=False)
    embed.add_field(name="Zugriff verwalten", value="Trust / Untrust / Invite / Block / Unblock", inline=False)
    embed.add_field(name="Sonstiges", value="Kick / Claim / Transfer / Delete", inline=False)

    view = TempVCOverlay()
    bot.active_temp_views.append(view)
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="tempvc_name", description="Ändert den Namen deines Temp Voice Channels.")
@app_commands.describe(name="Neuer Raumname")
async def tempvc_name_slash(interaction: discord.Interaction, name: str):
    member = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(member)
    if channel is None or not is_temp_owner(member, channel):
        return await interaction.response.send_message("Nur der Besitzer eines Temp Voice kann den Namen ändern.", ephemeral=True)

    data = get_temp_channel_data(channel)
    try:
        await channel.edit(name=name)
        if data.get("chat_channel_id"):
            chat_channel = interaction.guild.get_channel(data["chat_channel_id"])
            if chat_channel:
                await chat_channel.edit(name=f"{name}-chat")
        await interaction.response.send_message(f"Name wurde geändert zu `{name}`.")
    except Exception as e:
        await interaction.response.send_message(f"Fehler beim Ändern des Namens: {e}")


@bot.tree.command(name="tempvc_limit", description="Setzt das Nutzerlimit deines Temp Voice Channels.")
@app_commands.describe(limit="Maximale Teilnehmeranzahl")
async def tempvc_limit_slash(interaction: discord.Interaction, limit: int):
    member = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(member)
    if channel is None or not is_temp_owner(member, channel):
        return await interaction.response.send_message("Nur der Besitzer kann das Limit setzen.", ephemeral=True)

    if limit < 0 or limit > 99:
        return await interaction.response.send_message("Limit muss zwischen 0 und 99 liegen.", ephemeral=True)

    try:
        await channel.edit(user_limit=limit)
        await interaction.response.send_message(f"Maximale Teilnehmerzahl gesetzt auf {limit}.")
    except Exception as e:
        await interaction.response.send_message(f"Fehler beim Setzen des Limits: {e}")


@bot.tree.command(name="tempvc_privacy", description="Schaltet die Privatsphäre für deinen Temp Voice ein oder aus.")
@app_commands.describe(enabled="Privatsphäre aktivieren")
async def tempvc_privacy_slash(interaction: discord.Interaction, enabled: bool):
    member = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(member)
    if channel is None or not is_temp_owner(member, channel):
        return await interaction.response.send_message("Nur der Besitzer kann die Privatsphäre ändern.", ephemeral=True)

    data = get_temp_channel_data(channel)
    data["private"] = enabled
    await apply_privacy_settings(channel, data)
    await interaction.response.send_message(f"Privatsphäre gesetzt: {enabled}.")


@bot.tree.command(name="tempvc_waiting", description="Schaltet den Warteraum für deinen Temp Voice ein oder aus.")
@app_commands.describe(enabled="Warteraum aktivieren")
async def tempvc_waiting_slash(interaction: discord.Interaction, enabled: bool):
    member = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(member)
    if channel is None or not is_temp_owner(member, channel):
        return await interaction.response.send_message("Nur der Besitzer kann das Warteraum-Verhalten ändern.", ephemeral=True)

    data = get_temp_channel_data(channel)
    data["waiting_room"] = enabled
    await interaction.response.send_message(f"Warteraum gesetzt: {enabled}.")


@bot.tree.command(name="tempvc_chat", description="Schaltet den Chat für deinen Temp Voice ein oder aus.")
@app_commands.describe(enabled="Chat aktivieren")
async def tempvc_chat_slash(interaction: discord.Interaction, enabled: bool):
    member = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(member)
    if channel is None or not is_temp_owner(member, channel):
        return await interaction.response.send_message("Nur der Besitzer kann den Chat ein- oder ausschalten.", ephemeral=True)

    data = get_temp_channel_data(channel)
    if enabled:
        if data.get("chat_channel_id"):
            return await interaction.response.send_message("Der Chat ist bereits aktiviert.", ephemeral=True)

        category = channel.category
        try:
            chat_channel = await interaction.guild.create_text_channel(
                name=f"{channel.name}-chat",
                category=category,
                overwrites={
                    interaction.guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
                }
            )
            data["chat_channel_id"] = chat_channel.id
            await interaction.response.send_message(f"Chat-Kanal erstellt: {chat_channel.mention}")
        except Exception as e:
            await interaction.response.send_message(f"Fehler beim Erstellen des Chats: {e}")
    else:
        if not data.get("chat_channel_id"):
            return await interaction.response.send_message("Der Chat ist bereits deaktiviert.", ephemeral=True)

        chat_channel = interaction.guild.get_channel(data["chat_channel_id"])
        if chat_channel:
            try:
                await chat_channel.delete()
            except Exception as e:
                return await interaction.response.send_message(f"Fehler beim Löschen des Chats: {e}", ephemeral=True)
        data["chat_channel_id"] = None
        await interaction.response.send_message("Chat wurde deaktiviert.")


@bot.tree.command(name="tempvc_trust", description="Vertraut einen Benutzer in deinem Temp Voice.")
@app_commands.describe(member="Mitglied, das trusted werden soll")
async def tempvc_trust_slash(interaction: discord.Interaction, member: discord.Member):
    author = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(author)
    if channel is None or not is_temp_owner(author, channel):
        return await interaction.response.send_message("Nur der Besitzer kann vertrauen.", ephemeral=True)

    data = get_temp_channel_data(channel)
    if member.id in data["trusted"]:
        return await interaction.response.send_message("Dieser Benutzer ist bereits vertrauenswürdig.", ephemeral=True)

    data["trusted"].append(member.id)
    await channel.set_permissions(member, connect=True, view_channel=True)
    await interaction.response.send_message(f"{member.mention} ist jetzt trusted.")


@bot.tree.command(name="tempvc_untrust", description="Entzieht einem Benutzer das Vertrauen in deinem Temp Voice.")
@app_commands.describe(member="Mitglied, dessen Vertrauen entzogen werden soll")
async def tempvc_untrust_slash(interaction: discord.Interaction, member: discord.Member):
    author = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(author)
    if channel is None or not is_temp_owner(author, channel):
        return await interaction.response.send_message("Nur der Besitzer kann Vertrauen entziehen.", ephemeral=True)

    data = get_temp_channel_data(channel)
    if member.id not in data["trusted"]:
        return await interaction.response.send_message("Dieser Benutzer ist nicht trusted.", ephemeral=True)

    data["trusted"].remove(member.id)
    await channel.set_permissions(member, overwrite=None)
    await interaction.response.send_message(f"{member.mention} ist nicht mehr trusted.")


@bot.tree.command(name="tempvc_invite", description="Lädt einen Benutzer in deinen Temp Voice ein.")
@app_commands.describe(member="Mitglied, das eingeladen werden soll")
async def tempvc_invite_slash(interaction: discord.Interaction, member: discord.Member):
    author = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(author)
    if channel is None or not is_temp_owner(author, channel):
        return await interaction.response.send_message("Nur der Besitzer kann Einladungen vergeben.", ephemeral=True)

    data = get_temp_channel_data(channel)
    if member.id in data["invited"]:
        return await interaction.response.send_message("Dieser Benutzer wurde bereits eingeladen.", ephemeral=True)

    data["invited"].append(member.id)
    await channel.set_permissions(member, connect=True, view_channel=True)
    await interaction.response.send_message(f"{member.mention} wurde eingeladen.")


@bot.tree.command(name="tempvc_kick", description="Kick einen Benutzer aus deinem Temp Voice.")
@app_commands.describe(member="Mitglied, das gekickt werden soll")
async def tempvc_kick_slash(interaction: discord.Interaction, member: discord.Member):
    author = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(author)
    if channel is None or not is_temp_owner(author, channel):
        return await interaction.response.send_message("Nur der Besitzer kann jemanden kicken.", ephemeral=True)

    if member.voice and member.voice.channel == channel:
        try:
            await member.move_to(None)
            await interaction.response.send_message(f"{member.mention} wurde aus dem Voice entfernt.")
        except Exception as e:
            await interaction.response.send_message(f"Fehler beim Kicken: {e}")
    else:
        await interaction.response.send_message("Dieser Benutzer ist nicht im Temp Voice.")


@bot.tree.command(name="tempvc_region", description="Ändert die Region deines Temp Voice.")
@app_commands.describe(region="Neue Region")
async def tempvc_region_slash(interaction: discord.Interaction, region: str):
    author = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(author)
    if channel is None or not is_temp_owner(author, channel):
        return await interaction.response.send_message("Nur der Besitzer kann die Region ändern.", ephemeral=True)

    try:
        await channel.edit(rtc_region=region)
        await interaction.response.send_message(f"Region gesetzt auf `{region}`.")
    except Exception as e:
        await interaction.response.send_message(f"Fehler beim Setzen der Region: {e}")


@bot.tree.command(name="tempvc_block", description="Blockiert einen Benutzer für deinen Temp Voice.")
@app_commands.describe(member="Mitglied, das blockiert werden soll")
async def tempvc_block_slash(interaction: discord.Interaction, member: discord.Member):
    author = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(author)
    if channel is None or not is_temp_owner(author, channel):
        return await interaction.response.send_message("Nur der Besitzer kann blockieren.", ephemeral=True)

    data = get_temp_channel_data(channel)
    if member.id in data["blocked"]:
        return await interaction.response.send_message("Dieser Benutzer ist bereits blockiert.", ephemeral=True)

    data["blocked"].append(member.id)
    await channel.set_permissions(member, connect=False)
    if member.voice and member.voice.channel == channel:
        try:
            await member.move_to(None)
        except Exception:
            pass
    await interaction.response.send_message(f"{member.mention} wurde blockiert.")


@bot.tree.command(name="tempvc_unblock", description="Hebt die Blockierung eines Benutzers auf.")
@app_commands.describe(member="Mitglied, das entblockt werden soll")
async def tempvc_unblock_slash(interaction: discord.Interaction, member: discord.Member):
    author = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(author)
    if channel is None or not is_temp_owner(author, channel):
        return await interaction.response.send_message("Nur der Besitzer kann blockieren aufheben.", ephemeral=True)

    data = get_temp_channel_data(channel)
    if member.id not in data["blocked"]:
        return await interaction.response.send_message("Dieser Benutzer ist nicht blockiert.", ephemeral=True)

    data["blocked"].remove(member.id)
    await channel.set_permissions(member, overwrite=None)
    await interaction.response.send_message(f"{member.mention} ist nicht mehr blockiert.")


@bot.tree.command(name="tempvc_claim", description="Claimt ein Temp Voice, wenn der Besitzer weg ist.")
async def tempvc_claim_slash(interaction: discord.Interaction):
    author = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(author)
    if channel is None:
        return await interaction.response.send_message("Du musst in einem Temp Voice sein, um es zu claimen.", ephemeral=True)

    data = get_temp_channel_data(channel)
    owner = channel.guild.get_member(data["owner"])
    if owner and owner.voice and owner.voice.channel == channel:
        return await interaction.response.send_message("Der Besitzer ist noch im Raum.", ephemeral=True)

    data["owner"] = interaction.user.id
    await interaction.response.send_message("Du bist jetzt der Besitzer des Temp Voice Channels.")


@bot.tree.command(name="tempvc_transfer", description="Überträgt dein Temp Voice an einen Benutzer.")
@app_commands.describe(member="Neuer Besitzer")
async def tempvc_transfer_slash(interaction: discord.Interaction, member: discord.Member):
    author = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(author)
    if channel is None or not is_temp_owner(author, channel):
        return await interaction.response.send_message("Nur der Besitzer kann den Raum übertragen.", ephemeral=True)

    if member.voice is None or member.voice.channel != channel:
        return await interaction.response.send_message("Der Benutzer muss im selben Temp Voice sein.", ephemeral=True)

    data = get_temp_channel_data(channel)
    data["owner"] = member.id
    await interaction.response.send_message(f"Besitz wurde an {member.mention} übertragen.")


@bot.tree.command(name="tempvc_delete", description="Löscht dein Temp Voice.")
async def tempvc_delete_slash(interaction: discord.Interaction):
    author = resolve_member(interaction.user, interaction.guild)
    channel = get_voice_temp_channel_member(author)
    if channel is None or not is_temp_owner(author, channel):
        return await interaction.response.send_message("Nur der Besitzer kann den Temp Voice löschen.", ephemeral=True)

    await cleanup_temp_channel(channel)
    await interaction.response.send_message("Temp Voice Channel wurde gelöscht.")


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket erstellen", style=discord.ButtonStyle.success, emoji="🎫", custom_id="ticket_panel_create")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message(
                "Dieses Ticket kann nur auf einem Server erstellt werden.", ephemeral=True
            )

        existing = get_existing_ticket_channel(guild, interaction.user.id)
        if existing:
            return await interaction.response.send_message(
                f"Du hast bereits ein Ticket: {existing.mention}", ephemeral=True
            )

        category = get_ticket_category(guild)
        if category is None:
            category = await guild.create_category(TICKET_CATEGORY_NAME)

        name = f"{TICKET_CHANNEL_PREFIX}{sanitize_channel_name(interaction.user.display_name)}-{interaction.user.id}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        }
        for role in staff_roles(guild):
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        channel = await guild.create_text_channel(
            name=name,
            category=category,
            overwrites=overwrites,
            reason="Support-Ticket erstellt"
        )

        bot.ticket_channels[channel.id] = interaction.user.id

        try:
            await channel.send(
                f"{interaction.user.mention} Danke, dein Ticket wurde erstellt. Ein Support-Mitglied wird sich in Kürze darum kümmern.",
                view=TicketCloseView()
            )
        except Exception:
            pass

        await interaction.response.send_message(
            f"Dein Ticket wurde erstellt: {channel.mention}", ephemeral=True
        )

        await send_log(
            f"🎫 Ticket geöffnet\nBenutzer: {interaction.user} ({interaction.user.id})\nKanal: {channel.name} ({channel.id})\nServer: {guild.name} ({guild.id})"
        )


@bot.tree.command(name="setupticket", description="Richtet das Ticket-System automatisch ein.")
async def setupticket(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "Nur Administratoren können das Setup ausführen.", ephemeral=True
        )

    category = get_ticket_category(interaction.guild)
    if category is None:
        category = await interaction.guild.create_category(TICKET_CATEGORY_NAME)

    panel_channel = find_ticket_panel_channel(interaction.guild)
    if panel_channel is None:
        panel_channel = await interaction.guild.create_text_channel(
            name=TICKET_PANEL_CHANNEL_NAME,
            category=category,
            overwrites={interaction.guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)}
        )

    embed = discord.Embed(
        title="🎫 Ticket-System",
        description="Klicke auf den Button, um ein Support-Ticket zu erstellen.",
        color=discord.Color.green()
    )
    await panel_channel.send(embed=embed, view=TicketPanelView())
    await interaction.response.send_message(
        f"Ticket-Panel wurde eingerichtet in {panel_channel.mention}.", ephemeral=True
    )


@bot.tree.command(name="setupvc", description="Erstellt das Temp-Voice-Overlay und den Creator-Channel für den Server.")
async def setupvc(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "Nur Administratoren können das Setup ausführen.", ephemeral=True
        )

    try:
        creator_channel, overlay_channel, _ = await ensure_tempvoice_setup(interaction.guild)
        await interaction.response.send_message(
            f"Temp Voice Setup abgeschlossen. Overlay: {overlay_channel.mention} | Creator Channel: {creator_channel.mention}",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"Fehler beim Einrichten: {e}", ephemeral=True
        )


@bot.tree.command(name="reactionrole", description="Erstellt eine Reaction Role Nachricht.")
@app_commands.describe(
    channel="Kanal für die Nachricht",
    role="Rolle, die bei Reaktion vergeben wird",
    emoji="Emoji für die Reaction",
    message="Nachrichtentext"
)
async def reaction_role_slash(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    role: discord.Role,
    emoji: str,
    message: str
):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "Nur Administratoren können Reaction Roles einrichten.", ephemeral=True
        )

    try:
        msg = await channel.send(message)
        await msg.add_reaction(emoji)
    except Exception as e:
        return await interaction.response.send_message(
            f"Fehler beim Erstellen der Reaction Role Nachricht: {e}", ephemeral=True
        )

    bot.reaction_roles[msg.id] = {
        "role_id": role.id,
        "emoji": emoji
    }

    await interaction.response.send_message(
        f"Reaction Role Nachricht erstellt in {channel.mention}.", ephemeral=True
    )


@bot.tree.command(name="automod", description="Zeigt die Auto-Mod-Regeln an.")
async def automod_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔧 Auto-Mod Regeln",
        description="Hier siehst du, welche Regeln der Auto-Moderation aktuell prüft.",
        color=discord.Color.orange()
    )
    embed.add_field(name="Beleidigungen", value="Beleidigende Wörter werden entfernt und der Nutzer erhält einen 24-Stunden-Timeout.", inline=False)
    embed.add_field(name="Ausnahme", value="Administratoren werden nicht automatisch moderiert.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================
# READY
# =========================
@bot.event
async def on_ready():
    print(f"✅ Bot online als {bot.user}")
    print("Bot ready - slash commands loaded")

    try:
        print(f"Invite URL: {build_invite_url()}")
        await bot.tree.sync()
        bot.add_view(TempVCOverlay())
        bot.add_view(TicketPanelView())
        bot.add_view(TicketCloseView())
        for guild in bot.guilds:
            try:
                print(f"Syncing commands for guild {guild.id} ({guild.name})")
                await bot.tree.sync(guild=guild)
                # Ensure Temp Voice setup is initialized for each guild
                try:
                    await ensure_tempvoice_setup(guild)
                    print(f"Temp Voice Setup initialized for guild {guild.id}")
                except Exception as e:
                    print(f"Fehler beim Tempvoice-Setup für Guild {guild.id}: {e}")
            except Exception as e:
                print(f"Fehler bei Guild-Sync {guild.id}: {e}")
        command_names = [command.name for command in bot.tree.get_commands()]
        print(f"Slash-Commands registriert ({len(command_names)}): {command_names}")
        print(f"Bot ist in Guilds: {[guild.id for guild in bot.guilds]}")
    except Exception as e:
        print("Fehler beim Synchronisieren der Slash-Commands:", e)

    await send_log("🟢 Bot gestartet")


def format_member_list(guild, ids):
    return ", ".join(guild.get_member(member_id).mention for member_id in ids if guild.get_member(member_id)) or "keine"


async def cleanup_temp_channel(channel):
    data = get_temp_channel_data(channel)
    if data is None:
        return

    chat_channel_id = data.get("chat_channel_id")

    try:
        await channel.delete()
    except Exception as e:
        print("Delete Error:", e)

    if chat_channel_id:
        chat_channel = channel.guild.get_channel(chat_channel_id)
        if chat_channel:
            try:
                await chat_channel.delete()
            except Exception as e:
                print("Chat Delete Error:", e)

    print(f"cleanup_temp_channel: removing temp channel id={channel.id}")
    popped = bot.temp_channels.pop(channel.id, None)
    print(f"cleanup_temp_channel: popped={popped}")
    print(f"temp_channels keys now: {list(bot.temp_channels.keys())}")


async def delayed_cleanup(channel, delay: float = 3.0):
    """Wait a short time before cleaning up a temp channel to avoid race conditions."""
    try:
        await asyncio.sleep(delay)
    except Exception:
        return

    # Re-fetch channel object from guild to ensure it's current
    guild = channel.guild
    channel_ref = guild.get_channel(channel.id) if guild else None

    # If the channel no longer exists but mapping remains, remove mapping
    if channel_ref is None:
        popped = bot.temp_channels.pop(channel.id, None)
        print(f"delayed_cleanup: channel missing, popped={popped}")
        print(f"temp_channels keys now: {list(bot.temp_channels.keys())}")
        return

    # Only cleanup if still empty and still tracked
    if len(channel_ref.members) == 0 and channel.id in bot.temp_channels:
        print(f"delayed_cleanup: cleaning up channel id={channel.id}")
        await cleanup_temp_channel(channel_ref)
    else:
        print(f"delayed_cleanup: aborting cleanup for id={channel.id}, members={len(channel_ref.members)} tracked={channel.id in bot.temp_channels}")


async def apply_privacy_settings(channel, data):
    default_overwrite = channel.overwrites_for(channel.guild.default_role)
    default_overwrite.connect = not data.get("private", False)
    await channel.set_permissions(channel.guild.default_role, overwrite=default_overwrite)

    for member_id in data.get("trusted", []) + data.get("invited", []):
        member = channel.guild.get_member(member_id)
        if member:
            await channel.set_permissions(member, connect=True, view_channel=True)

    for member_id in data.get("blocked", []):
        member = channel.guild.get_member(member_id)
        if member:
            await channel.set_permissions(member, connect=False)


async def enforce_temp_access(member, channel):
    data = get_temp_channel_data(channel)
    if data is None:
        return

    if member.id == data["owner"]:
        return

    if member.id in data.get("blocked", []):
        try:
            await member.move_to(None)
        except Exception:
            pass
        return

    if member.id in data.get("trusted", []) or member.id in data.get("invited", []):
        return

    if data.get("private", False) or data.get("waiting_room", False):
        try:
            await member.move_to(None)
            await member.send(
                f"Dein Zutritt zum Temp Voice `{channel.name}` wurde verweigert. "
                "Bitte warte auf eine Einladung oder einen Trusted-Zugang."
            )
        except Exception:
            pass


def parse_bool(value):
    value = value.lower()
    if value in ("on", "true", "yes", "1", "ein"):
        return True
    if value in ("off", "false", "no", "0", "aus"):
        return False
    return None


def message_has_profanity(content: str) -> bool:
    return bool(bad_word_regex.search(content))


def message_is_caps_spam(content: str) -> bool:
    if len(content) < CAPS_MIN_LENGTH:
        return False
    letters = [c for c in content if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return (upper / len(letters)) >= CAPS_RATIO_THRESHOLD


def message_mention_spam(message: discord.Message) -> bool:
    return len(message.mentions) > MAX_MENTIONS


def message_has_discord_invite(content: str) -> bool:
    return bool(invite_regex.search(content))


class AppealView(discord.ui.View):
    def __init__(self, guild_name: str, original_content: str):
        super().__init__(timeout=None)
        self.guild_name = guild_name
        self.original_content = original_content

    @discord.ui.button(
        label="📝 Einspruch starten",
        style=discord.ButtonStyle.primary
    )
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "✍️ Bitte sende jetzt deinen Einspruch hier in den Chat. "
            "Der Bot leitet ihn automatisch an das Moderationsteam weiter.",
            ephemeral=True
        )

        def check(m):
            return m.author == interaction.user and isinstance(m.channel, discord.DMChannel)

        try:
            msg = await bot.wait_for("message", timeout=300.0, check=check)
            await send_log(
                f"📩 EINSPRUCH ERHALTEN\n"
                f"👤 User: {interaction.user} ({interaction.user.id})\n"
                f"🏛️ Server: {self.guild_name}\n"
                f"📄 Einspruch: {msg.content}\n"
                f"🔗 Originalnachricht: {self.original_content}"
            )
            try:
                await interaction.user.send(
                    "✅ Dein Einspruch wurde an das Moderationsteam weitergeleitet."
                )
            except Exception:
                pass
        except asyncio.TimeoutError:
            try:
                await interaction.user.send("⏳ Zeit abgelaufen. Bitte versuche es erneut.")
            except Exception:
                pass


async def send_auto_mod_log(reason: str, message: discord.Message):
    content = (
        f"🚨 Auto-Mod: {reason}\n"
        f"User: {message.author} ({message.author.id})\n"
        f"Server: {message.guild.name} ({message.guild.id})\n"
        f"Kanal: {message.channel.name} ({message.channel.id})\n"
        f"Inhalt: {message.content[:1500] or '(kein Inhalt)'}"
    )
    await send_log(content)


async def moderate_message(message: discord.Message, reason: str, timeout_minutes: int = 0):
    original_content = message.content or ""
    try:
        await message.delete()
    except Exception:
        pass

    if timeout_minutes > 0:
        try:
            await message.author.timeout(
                timedelta(minutes=timeout_minutes),
                reason=reason
            )
        except Exception:
            pass

    await send_auto_mod_log(reason, message)

    embed = discord.Embed(
        title="🚨 Moderationsmaßnahme",
        description=(
            f"Hallo {message.author.mention},\n\n"
            f"deine Nachricht auf **{message.guild.name}** wurde entfernt."
        ),
        color=discord.Color.orange()
    )
    embed.add_field(name="📋 Grund", value=reason, inline=True)
    if timeout_minutes > 0:
        embed.add_field(name="⏳ Dauer", value=f"{timeout_minutes} Minuten", inline=True)
    embed.add_field(name="🔗 Inhalt", value=original_content[:1024] or "(kein Inhalt)", inline=False)
    embed.set_footer(text="Automatische Moderation")
    if message.guild.icon:
        embed.set_thumbnail(url=message.guild.icon.url)

    try:
        dm_msg = await message.author.send(embed=embed)
        appeal_view = AppealView(message.guild.name, original_content)
        bot.active_views.append(appeal_view)
        try:
            await message.author.send(view=appeal_view)
        except Exception:
            pass
    except Exception:
        pass


async def evaluate_auto_mod(message: discord.Message):
    if message.author.bot or message.author.guild_permissions.administrator:
        return None
    if not message.guild:
        return None

    content = message.content or ""
    if not content.strip() and not message.attachments:
        return None

    if message_has_discord_invite(content):
        return "Discord Invite", 24 * 60

    if message_has_profanity(content):
        return "Beleidigung", 24 * 60

    return None


# =========================
# LINK PROTECTION + DM TICKET SYSTEM
# =========================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.startswith(PREFIX):
        print(f"Received prefix message from {message.author}: {message.content}")

    if not message.author.guild_permissions.administrator:
        result = await evaluate_auto_mod(message)
        if result is not None:
            reason, timeout_minutes = result
            await moderate_message(message, reason, timeout_minutes)
            return

    await bot.process_commands(message)


async def handle_reaction_role(payload: discord.RawReactionActionEvent, add: bool):
    config = bot.reaction_roles.get(payload.message_id)
    if config is None or payload.guild_id is None:
        return

    if str(payload.emoji) != config["emoji"]:
        return

    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return

    role = guild.get_role(config["role_id"])
    if role is None:
        return

    member = payload.member
    if member is None:
        member = guild.get_member(payload.user_id)

    if member is None or member.bot:
        return

    try:
        if add:
            await member.add_roles(role, reason="Reaction Role hinzugefügt")
        else:
            await member.remove_roles(role, reason="Reaction Role entfernt")
    except Exception as e:
        print(f"Reaction Role Fehler: {e}")


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await handle_reaction_role(payload, True)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await handle_reaction_role(payload, False)


@bot.event
async def on_voice_state_update(member, before, after):

    creator_channel = get_tempvoice_creator_channel(member.guild)
    if after.channel and creator_channel and after.channel.id == creator_channel.id:

        guild = member.guild
        category = after.channel.category

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                connect=True
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
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

        await member.move_to(channel)
        bot.temp_channels[channel.id] = {
            "owner": member.id,
            "trusted": [],
            "blocked": [],
            "invited": [],
            "private": False,
            "waiting_room": False,
            "chat_channel_id": None,
            "region": None,
            "limit": 0
        }

        print(f"temp channel created: id={channel.id} owner={member.id}")
        print(f"temp_channels keys now: {list(bot.temp_channels.keys())}")

        await send_log(
            f"🎤 Temp Voice erstellt\n"
            f"👤 Owner: {member} ({member.id})\n"
            f"🏠 Channel: {channel.name} ({channel.id})"
        )
        return

    if before.channel and before.channel.id in bot.temp_channels:
        channel = before.channel
        data = get_temp_channel_data(channel)

        if len(channel.members) == 0:
            # Schedule delayed cleanup to avoid race conditions where members
            # briefly leave/join while interacting with overlays.
            asyncio.create_task(delayed_cleanup(channel, delay=3.0))
            await send_log(
                f"🗑️ Temp Voice gelöscht (scheduled)\n"
                f"🏠 Channel: {channel.name} ({channel.id})\n"
                f"👤 Owner ID: {data['owner']}"
            )

    if before.channel and before.channel.id in bot.ticket_channels and len(before.channel.members) == 0:
        # Optional: cleanup abandoned ticket channels when empty
        bot.ticket_channels.pop(before.channel.id, None)

    if after.channel and after.channel.id in bot.temp_channels:
        await enforce_temp_access(member, after.channel)

    if before.channel:
        await update_alone_role(before.channel)

    if after.channel and after.channel != before.channel:
        await update_alone_role(after.channel)


# =========================
# START
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
