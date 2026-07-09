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
    "default_search": "ytsearch1",
    "noplaylist": True,
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



async def ensure_voice_channel_ready(channel: discord.VoiceChannel):

    if not discord.opus.is_loaded():
        load_discord_opus()

    bot_member = channel.guild.me

    if bot_member is None:
        raise RuntimeError(
            "Bot-Mitglied nicht gefunden."
        )

    permissions = channel.permissions_for(bot_member)

    if not permissions.connect:
        raise RuntimeError(
            "Keine Berechtigung zum Verbinden."
        )

    if not permissions.speak:
        raise RuntimeError(
            "Keine Berechtigung zum Sprechen."
        )

    return channel



async def create_ytdl_source(search: str):

    if youtube_dl is None:
        raise RuntimeError(
            "yt-dlp ist nicht installiert."
        )


    if not is_audio_url(search):
        search = f"ytsearch1:{search}"


    loop = asyncio.get_running_loop()


    def extract():

        return youtube_dl.YoutubeDL(
            YTDL_OPTIONS
        ).extract_info(
            search,
            download=False
        )


    data = await loop.run_in_executor(
        None,
        extract
    )


    if data is None:
        raise RuntimeError(
            "Keine Musik gefunden."
        )


    if "entries" in data:

        data = next(
            (
                entry
                for entry in data["entries"]
                if entry
            ),
            None
        )


    if data is None:
        raise RuntimeError(
            "Kein Treffer gefunden."
        )


    return (
        data["url"],
        data.get("title", search)
    )



async def get_audio_source(query: str):

    return await create_ytdl_source(query)



@bot.tree.command(
    name="play",
    description="Spielt Musik über Suchbegriff oder URL ab."
)
@app_commands.describe(
    query="Songtitel oder Interpret + Songtitel (z.B. Linkin Park Numb)"
)
async def play_slash(
    interaction: discord.Interaction,
    query: str
):

    if interaction.user.voice is None:

        return await interaction.response.send_message(
            "Du musst zuerst in einem Voice-Channel sein.",
            ephemeral=True
        )


    await interaction.response.defer()


    try:

        channel = await ensure_voice_channel_ready(
            interaction.user.voice.channel
        )


        voice_client = interaction.guild.voice_client


        if voice_client is None:

            voice_client = await channel.connect(
                timeout=20,
                reconnect=True
            )

        elif voice_client.channel != channel:

            await voice_client.move_to(channel)



        if voice_client.is_playing():

            voice_client.stop()



        source_url, title = await get_audio_source(query)



        ffmpeg_path = resolve_ffmpeg_executable()


        if not ffmpeg_path:

            raise RuntimeError(
                "FFmpeg wurde nicht gefunden."
            )



        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(
                source_url,
                executable=ffmpeg_path,
                **FFMPEG_OPTIONS
            ),
            volume=0.5
        )


        voice_client.play(source)



        await interaction.followup.send(
            f"🎵 Spiele jetzt: **{title}**"
        )



    except Exception as e:

        traceback.print_exc()

        await interaction.followup.send(
            f"❌ Fehler:\n```{type(e).__name__}: {e}```",
            ephemeral=True
        )



@bot.tree.command(
    name="pause",
    description="Pausiert die aktuelle Wiedergabe."
)
async def pause_slash(
    interaction: discord.Interaction
):

    vc = interaction.guild.voice_client

    if vc is None or not vc.is_playing():

        return await interaction.response.send_message(
            "Es läuft keine Musik.",
            ephemeral=True
        )


    vc.pause()

    await interaction.response.send_message(
        "⏸️ Musik pausiert."
    )



@bot.tree.command(
    name="resume",
    description="Setzt die Wiedergabe fort."
)
async def resume_slash(
    interaction: discord.Interaction
):

    vc = interaction.guild.voice_client

    if vc is None or not vc.is_paused():

        return await interaction.response.send_message(
            "Es ist nichts pausiert.",
            ephemeral=True
        )


    vc.resume()

    await interaction.response.send_message(
        "▶️ Musik fortgesetzt."
    )



@bot.tree.command(
    name="stop",
    description="Stoppt Musik und verlässt den Voice-Channel."
)
async def stop_slash(
    interaction: discord.Interaction
):

    vc = interaction.guild.voice_client


    if vc is None:

        return await interaction.response.send_message(
            "Ich bin in keinem Voice-Channel.",
            ephemeral=True
        )


    vc.stop()

    await vc.disconnect()


    await interaction.response.send_message(
        "⏹️ Musik gestoppt."
    )
