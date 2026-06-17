import asyncio
import discord
from discord.ext import commands
import re
import os
from datetime import timedelta
from flask import Flask
from threading import Thread

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


# =========================
# BOT SETUP
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
bot.temp_channels = {}


@bot.command(name="ping")
async def ping(ctx: commands.Context):
    await ctx.send("Pong!")


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("Unbekannter Befehl. Versuch `!ping`.")
        return
    print(f"Command Error: {error}")
    try:
        await ctx.send(f"Fehler: {error}")
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


def get_temp_channel_data(channel):
    return bot.temp_channels.get(channel.id) if channel else None


def is_temp_channel(channel):
    return channel is not None and channel.id in bot.temp_channels


def is_temp_owner(member, channel):
    data = get_temp_channel_data(channel)
    return data is not None and data["owner"] == member.id


def get_voice_temp_channel(ctx):
    channel = ctx.author.voice.channel if ctx.author.voice else None
    return channel if is_temp_channel(channel) else None


def get_member_voice_temp_channel(member):
    channel = member.voice.channel if member.voice else None
    return channel if is_temp_channel(channel) else None


def parse_member_guild_member(guild, text):
    text = text.strip()
    match = re.match(r"^<@!?(\d+)>$", text)
    if match:
        return guild.get_member(int(match.group(1)))
    if text.isdigit():
        return guild.get_member(int(text))
    return None


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
        channel = get_member_voice_temp_channel(interaction.user)
        if channel is None or not is_temp_owner(interaction.user, channel):
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
        channel = get_member_voice_temp_channel(interaction.user)
        if channel is None or not is_temp_owner(interaction.user, channel):
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
        channel = get_member_voice_temp_channel(interaction.user)
        if channel is None or not is_temp_owner(interaction.user, channel):
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
        channel = get_member_voice_temp_channel(interaction.user)
        if channel is None or not is_temp_owner(interaction.user, channel):
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
    def __init__(self, owner_id: int | None = None):
        super().__init__(timeout=None)
        self.owner_id = owner_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.owner_id is None:
            return True
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Nur der Ersteller kann dieses Overlay benutzen.",
                ephemeral=True
            )
            return False
        return True

    async def _get_temp_channel(self, interaction):
        channel = get_member_voice_temp_channel(interaction.user)
        if channel is None:
            await interaction.response.send_message(
                "Du musst in deinem Temp Voice sein, um diese Aktion zu nutzen.",
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
            return message.content.strip()
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

    @discord.ui.button(label="Name", style=discord.ButtonStyle.secondary, emoji="✏️")
    async def name_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return

        value = await self._ask_for_input(interaction, "Bitte sende den neuen Namen für den Temp Voice Channel.")
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

    @discord.ui.button(label="Limit", style=discord.ButtonStyle.secondary, emoji="🔢")
    async def limit_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return

        value = await self._ask_for_input(interaction, "Bitte sende das neue Nutzerlimit (0-99).")
        if not value:
            return

        try:
            limit = int(value)
            if limit < 0 or limit > 99:
                raise ValueError()
            await channel.edit(user_limit=limit)
            await interaction.followup.send(
                f"Limit gesetzt auf {limit}.", ephemeral=True
            )
        except ValueError:
            await interaction.followup.send(
                "Bitte gib eine Zahl zwischen 0 und 99 an.", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Setzen des Limits: {e}", ephemeral=True
            )

    @discord.ui.button(label="Region", style=discord.ButtonStyle.secondary, emoji="🌍")
    async def region_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return

        value = await self._ask_for_input(interaction, "Bitte sende die gewünschte Region (z.B. europe, us-west).")
        if not value:
            return

        try:
            await channel.edit(rtc_region=value)
            await interaction.followup.send(
                f"Region gesetzt auf `{value}`.", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"Fehler beim Setzen der Region: {e}", ephemeral=True
            )

    @discord.ui.button(label="Privacy", style=discord.ButtonStyle.secondary, emoji="🔒")
    async def privacy_button(self, button: discord.ui.Button, interaction: discord.Interaction):
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

    @discord.ui.button(label="Waiting", style=discord.ButtonStyle.secondary, emoji="⏳")
    async def waiting_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        data = get_temp_channel_data(channel)
        data["waiting_room"] = not data.get("waiting_room", False)
        state = "aktiviert" if data["waiting_room"] else "deaktiviert"
        await interaction.response.send_message(
            f"Warteraum {state}.", ephemeral=True
        )

    @discord.ui.button(label="Chat", style=discord.ButtonStyle.secondary, emoji="💬")
    async def chat_button(self, button: discord.ui.Button, interaction: discord.Interaction):
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

    @discord.ui.button(label="Trust", style=discord.ButtonStyle.success, emoji="✅")
    async def trust_button(self, button: discord.ui.Button, interaction: discord.Interaction):
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

    @discord.ui.button(label="Untrust", style=discord.ButtonStyle.danger, emoji="❌")
    async def untrust_button(self, button: discord.ui.Button, interaction: discord.Interaction):
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

    @discord.ui.button(label="Invite", style=discord.ButtonStyle.primary, emoji="📩")
    async def invite_button(self, button: discord.ui.Button, interaction: discord.Interaction):
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

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger, emoji="👢")
    async def kick_button(self, button: discord.ui.Button, interaction: discord.Interaction):
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

    @discord.ui.button(label="Block", style=discord.ButtonStyle.danger, emoji="⛔")
    async def block_button(self, button: discord.ui.Button, interaction: discord.Interaction):
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

    @discord.ui.button(label="Unblock", style=discord.ButtonStyle.success, emoji="🚫")
    async def unblock_button(self, button: discord.ui.Button, interaction: discord.Interaction):
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

    @discord.ui.button(label="Transfer", style=discord.ButtonStyle.secondary, emoji="🔁")
    async def transfer_button(self, button: discord.ui.Button, interaction: discord.Interaction):
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

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        channel = await self._get_temp_channel(interaction)
        if channel is None:
            return
        await cleanup_temp_channel(channel)
        await interaction.response.send_message(
            "Temp Voice wurde gelöscht.", ephemeral=True
        )

    async def on_error(self, error: Exception, item: discord.ui.Item, interaction: discord.Interaction) -> None:
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Ein Fehler ist aufgetreten: {error}", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    f"Ein Fehler ist aufgetreten: {error}", ephemeral=True
                )
        except Exception:
            pass


@bot.group(name="tempvc", invoke_without_command=True)
async def tempvc(ctx):
    channel = get_voice_temp_channel(ctx)
    if channel is None:
        return await ctx.send(
            "Du musst in deinem Temp Voice sein, um das Overlay zu benutzen."
        )
    if not is_temp_owner(ctx.author, channel):
        return await ctx.send(
            "Nur der Besitzer kann das Overlay benutzen."
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

    view = TempVCOverlay(ctx.author.id)
    bot.add_view(view)
    await ctx.send(embed=embed, view=view)


@bot.command(name="setupvc")
@commands.has_permissions(administrator=True)
async def setupvc_prefix(ctx: commands.Context):
    embed = discord.Embed(
        title="🎛️ Temp Voice Steuerung",
        description=(
            "Klicke auf die Buttons, um deinen Temp Voice zu konfigurieren.\n"
            "Alle können das Overlay nutzen, wenn sie sich in ihrem Temp Voice befinden."
        ),
        color=discord.Color.blurple()
    )
    embed.add_field(name="Schnell starten", value="Name / Limit / Region / Chat / Privacy", inline=False)
    embed.add_field(name="Zugriff verwalten", value="Trust / Untrust / Invite / Block / Unblock", inline=False)
    embed.add_field(name="Sonstiges", value="Kick / Claim / Transfer / Delete", inline=False)

    view = TempVCOverlay(None)
    bot.add_view(view)
    await ctx.send("Temp Voice Overlay wurde eingerichtet.", embed=embed, view=view)


@bot.tree.command(name="setupvc", description="Erstellt das Temp-Voice-Overlay für den Server.")
async def setupvc(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "Nur Administratoren können das Setup ausführen.", ephemeral=True
        )

    embed = discord.Embed(
        title="🎛️ Temp Voice Steuerung",
        description=(
            "Klicke auf die Buttons, um deinen Temp Voice zu konfigurieren.\n"
            "Alle können das Overlay nutzen, wenn sie sich in ihrem Temp Voice befinden."
        ),
        color=discord.Color.blurple()
    )
    embed.add_field(name="Schnell starten", value="Name / Limit / Region / Chat / Privacy", inline=False)
    embed.add_field(name="Zugriff verwalten", value="Trust / Untrust / Invite / Block / Unblock", inline=False)
    embed.add_field(name="Sonstiges", value="Kick / Claim / Transfer / Delete", inline=False)

    view = TempVCOverlay(None)
    bot.add_view(view)
    await interaction.response.send_message(
        "Temp Voice Overlay wurde eingerichtet.", embed=embed, view=view
    )

# =========================
# READY
# =========================
@bot.event
async def on_ready():
    print(f"✅ Bot online als {bot.user}")
    print("Loaded prefix commands:", [cmd.name for cmd in bot.commands])
    print("Loaded slash commands:", [cmd.name for cmd in bot.tree.commands])

    try:
        await bot.tree.sync()
        for guild in bot.guilds:
            try:
                await bot.tree.sync(guild=guild)
            except Exception as e:
                print(f"Fehler bei Guild-Sync {guild.id}: {e}")
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

    bot.temp_channels.pop(channel.id, None)


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


@tempvc.command(name="name")
async def tempvc_name(ctx, *, name: str):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer eines Temp Voice kann den Namen ändern.")

    data = get_temp_channel_data(channel)
    try:
        await channel.edit(name=name)
        if data.get("chat_channel_id"):
            chat_channel = ctx.guild.get_channel(data["chat_channel_id"])
            if chat_channel:
                await chat_channel.edit(name=f"{name}-chat")
        await ctx.send(f"Name wurde geändert zu `{name}`.")
    except Exception as e:
        await ctx.send(f"Fehler beim Ändern des Namens: {e}")


@tempvc.command(name="limit")
async def tempvc_limit(ctx, limit: int):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann das Limit setzen.")

    if limit < 0 or limit > 99:
        return await ctx.send("Limit muss zwischen 0 und 99 liegen.")

    try:
        await channel.edit(user_limit=limit)
        await ctx.send(f"Maximale Teilnehmerzahl gesetzt auf {limit}.")
    except Exception as e:
        await ctx.send(f"Fehler beim Setzen des Limits: {e}")


@tempvc.command(name="privacy")
async def tempvc_privacy(ctx, value: str):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann die Privatsphäre ändern.")

    enabled = parse_bool(value)
    if enabled is None:
        return await ctx.send("Bitte `on` oder `off` angeben.")

    data = get_temp_channel_data(channel)
    data["private"] = enabled
    await apply_privacy_settings(channel, data)
    await ctx.send(f"Privatsphäre gesetzt: {enabled}.")


@tempvc.command(name="waiting")
async def tempvc_waiting(ctx, value: str):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann das Warteraum-Verhalten ändern.")

    enabled = parse_bool(value)
    if enabled is None:
        return await ctx.send("Bitte `on` oder `off` angeben.")

    data = get_temp_channel_data(channel)
    data["waiting_room"] = enabled
    await ctx.send(f"Warteraum gesetzt: {enabled}.")


@tempvc.command(name="chat")
async def tempvc_chat(ctx, value: str):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann den Chat ein- oder ausschalten.")

    enabled = parse_bool(value)
    if enabled is None:
        return await ctx.send("Bitte `on` oder `off` angeben.")

    data = get_temp_channel_data(channel)
    if enabled:
        if data.get("chat_channel_id"):
            return await ctx.send("Der Chat ist bereits aktiviert.")

        category = channel.category
        try:
            chat_channel = await ctx.guild.create_text_channel(
                name=f"{channel.name}-chat",
                category=category,
                overwrites={
                    ctx.guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=True)
                }
            )
            data["chat_channel_id"] = chat_channel.id
            await ctx.send(f"Chat-Kanal erstellt: {chat_channel.mention}")
        except Exception as e:
            await ctx.send(f"Fehler beim Erstellen des Chats: {e}")
    else:
        if not data.get("chat_channel_id"):
            return await ctx.send("Der Chat ist bereits deaktiviert.")

        chat_channel = ctx.guild.get_channel(data["chat_channel_id"])
        if chat_channel:
            try:
                await chat_channel.delete()
            except Exception as e:
                await ctx.send(f"Fehler beim Löschen des Chats: {e}")
                return
        data["chat_channel_id"] = None
        await ctx.send("Chat wurde deaktiviert.")


@tempvc.command(name="trust")
async def tempvc_trust(ctx, member: discord.Member):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann vertrauen.")

    data = get_temp_channel_data(channel)
    if member.id in data["trusted"]:
        return await ctx.send("Dieser Benutzer ist bereits vertrauenswürdig.")

    data["trusted"].append(member.id)
    await channel.set_permissions(member, connect=True, view_channel=True)
    await ctx.send(f"{member.mention} ist jetzt trusted.")


@tempvc.command(name="untrust")
async def tempvc_untrust(ctx, member: discord.Member):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann Vertrauen entziehen.")

    data = get_temp_channel_data(channel)
    if member.id not in data["trusted"]:
        return await ctx.send("Dieser Benutzer ist nicht trusted.")

    data["trusted"].remove(member.id)
    await channel.set_permissions(member, overwrite=None)
    await ctx.send(f"{member.mention} ist nicht mehr trusted.")


@tempvc.command(name="invite")
async def tempvc_invite(ctx, member: discord.Member):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann Einladungen vergeben.")

    data = get_temp_channel_data(channel)
    if member.id in data["invited"]:
        return await ctx.send("Dieser Benutzer wurde bereits eingeladen.")

    data["invited"].append(member.id)
    await channel.set_permissions(member, connect=True, view_channel=True)
    await ctx.send(f"{member.mention} wurde eingeladen.")


@tempvc.command(name="kick")
async def tempvc_kick(ctx, member: discord.Member):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann jemanden kicken.")

    if member.voice and member.voice.channel == channel:
        try:
            await member.move_to(None)
            await ctx.send(f"{member.mention} wurde aus dem Voice entfernt.")
        except Exception as e:
            await ctx.send(f"Fehler beim Kicken: {e}")
    else:
        await ctx.send("Dieser Benutzer ist nicht im Temp Voice.")


@tempvc.command(name="region")
async def tempvc_region(ctx, region: str):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann die Region ändern.")

    try:
        await channel.edit(rtc_region=region)
        await ctx.send(f"Region gesetzt auf `{region}`.")
    except Exception as e:
        await ctx.send(f"Fehler beim Setzen der Region: {e}")


@tempvc.command(name="block")
async def tempvc_block(ctx, member: discord.Member):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann blockieren.")

    data = get_temp_channel_data(channel)
    if member.id in data["blocked"]:
        return await ctx.send("Dieser Benutzer ist bereits blockiert.")

    data["blocked"].append(member.id)
    await channel.set_permissions(member, connect=False)
    if member.voice and member.voice.channel == channel:
        try:
            await member.move_to(None)
        except Exception:
            pass
    await ctx.send(f"{member.mention} wurde blockiert.")


@tempvc.command(name="unblock")
async def tempvc_unblock(ctx, member: discord.Member):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann blockieren aufheben.")

    data = get_temp_channel_data(channel)
    if member.id not in data["blocked"]:
        return await ctx.send("Dieser Benutzer ist nicht blockiert.")

    data["blocked"].remove(member.id)
    await channel.set_permissions(member, overwrite=None)
    await ctx.send(f"{member.mention} ist nicht mehr blockiert.")


@tempvc.command(name="claim")
async def tempvc_claim(ctx):
    channel = get_voice_temp_channel(ctx)
    if channel is None:
        return await ctx.send("Du musst in einem Temp Voice sein, um es zu claimen.")

    data = get_temp_channel_data(channel)
    owner = channel.guild.get_member(data["owner"])
    if owner and owner.voice and owner.voice.channel == channel:
        return await ctx.send("Der Besitzer ist noch im Raum.")

    data["owner"] = ctx.author.id
    await ctx.send("Du bist jetzt der Besitzer des Temp Voice Channels.")


@tempvc.command(name="transfer")
async def tempvc_transfer(ctx, member: discord.Member):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann den Raum übertragen.")

    if member.voice is None or member.voice.channel != channel:
        return await ctx.send("Der Benutzer muss im selben Temp Voice sein.")

    data = get_temp_channel_data(channel)
    data["owner"] = member.id
    await ctx.send(f"Besitz wurde an {member.mention} übertragen.")


@tempvc.command(name="delete")
async def tempvc_delete(ctx):
    channel = get_voice_temp_channel(ctx)
    if channel is None or not is_temp_owner(ctx.author, channel):
        return await ctx.send("Nur der Besitzer kann den Temp Voice löschen.")

    await cleanup_temp_channel(channel)
    await ctx.send("Temp Voice Channel wurde gelöscht.")


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
        if link_regex.search(message.content):
            try:
                original_content = message.content

                await message.delete()

                # =========================
                # TIMEOUT
                # =========================
                await message.author.timeout(
                    timedelta(days=1),
                    reason="Link Spam"
                )

            except Exception as e:
                print(f"Fehler: {e}")
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

    await bot.process_commands(message)






@bot.event
async def on_voice_state_update(member, before, after):

    if after.channel and after.channel.id == CREATOR_CHANNEL_ID:

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
            await cleanup_temp_channel(channel)
            await send_log(
                f"🗑️ Temp Voice gelöscht\n"
                f"🏠 Channel: {channel.name} ({channel.id})\n"
                f"👤 Owner ID: {data['owner']}"
            )

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
